from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from app.domain.errors import ChromiumError
from app.domain.models.browser_configuration import BrowserConfiguration
from app.domain.models.proxy import Proxy
from app.infrastructure.chromium.paths import discover_chromium
from app.infrastructure.chromium.proxy_shim import LocalProxyShim
from app.infrastructure.proxy.transport import probe_proxy

if TYPE_CHECKING:
    from app.application.ports import LogSink

_PROXY_PROBE_TIMEOUT = 6.0

# Allowlisted launch switches. Anything outside this set must go through an
# explicit code change + test update — silent flag drift is how profiles end
# up half-spoofed (UA without Client Hints) and Google flags them as bots.
_STEALTH_FLAGS = (
    "--disable-blink-features=AutomationControlled",
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--disable-features=Translate",
    "--no-first-run",
    "--no-default-browser-check",
)
# Ephemeral DevTools endpoint for the CDP stealth layer (user-agent hints,
# timezone, WebGL overrides). Chrome accepts a bare port only here (the
# host:port form is ignored and DevTools never starts); port 0 picks a free
# ephemeral port and Chrome binds it to 127.0.0.1 (verified via lsof), so it
# is never exposed on LAN.
_REMOTE_DEBUGGING_FLAG = "--remote-debugging-port=0"

# Windows has no SIGKILL semantics (os.kill == TerminateProcess); resolve the
# constant defensively so merely referencing it never raises AttributeError.
_SIGKILL: int = getattr(signal, "SIGKILL", signal.SIGTERM)
_SIGTERM: int = getattr(signal, "SIGTERM", signal.SIGTERM)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _running_as_root() -> bool:
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def _running_in_docker() -> bool:
    try:
        if Path("/.dockerenv").exists():
            return True
        cgroup = Path("/proc/self/cgroup")
        if cgroup.is_file() and "docker" in cgroup.read_text(errors="ignore"):
            return True
    except OSError:
        pass
    return False


def _needs_no_sandbox() -> bool:
    """Linux root/docker cannot use the Chromium sandbox (`Running as root
    without --no-sandbox is not supported`). Also honours ANTIDETECT_NO_SANDBOX."""
    if os.environ.get("ANTIDETECT_NO_SANDBOX", "").strip().lower() in ("1", "true", "yes"):
        return True
    return sys.platform.startswith("linux") and (_running_as_root() or _running_in_docker())


def _popen_kwargs() -> dict:
    """Platform-specific Popen options (no console window on Windows)."""
    if _is_windows():
        kwargs: dict = {}
        # CREATE_NO_WINDOW exists on Windows only; DETACHED_PROCESS would
        # detach from the console but still flash one — prefer NO_WINDOW.
        creation_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creation_flag:
            kwargs["creationflags"] = creation_flag
        return kwargs
    return {"start_new_session": True}


def _terminate_pid(pid: int, force: bool = False) -> None:
    """Terminate by pid on any OS (taskkill on Windows, signal elsewhere)."""
    if _is_windows():
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid)] + (["/F"] if force else []),
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.kill(pid, _SIGKILL if force else _SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


_BINARY_VERSION_CACHE: dict[str, str | None] = {}


def chromium_binary_version(binary: Path) -> str | None:
    """Best-effort `binary --version` probe (never raises, cached, 5s timeout).

    Returns the raw version string (e.g. "Google Chrome 152.0.7977.83") or
    None when the binary does not answer (broken installs, timeouts).
    Results are cached per path so repeated profile starts stay fast.
    """
    key = str(binary)
    if key in _BINARY_VERSION_CACHE:
        return _BINARY_VERSION_CACHE[key]
    try:
        completed = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        # Never let version probing break a launch: mocked Popen in tests,
        # missing binaries and timeouts all degrade to "unknown version".
        _BINARY_VERSION_CACHE[key] = None
        return None
    text = (completed.stdout or completed.stderr or "").strip()
    _BINARY_VERSION_CACHE[key] = text or None
    return _BINARY_VERSION_CACHE[key]


def chromium_binary_major(binary: Path) -> int | None:
    """Major Chrome version of the launch binary, if it can be probed."""
    import re

    text = chromium_binary_version(binary)
    if not text:
        return None
    match = re.search(r"(\d+)\.", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


class ChromiumManager:
    """Launches and supervises a single Chromium process bound to one profile.

    Every launched process receives ``--user-data-dir=<profile_path>`` so each
    profile keeps its own cookies, localStorage, IndexedDB, cache, permissions
    and open tabs across restarts. Different profiles never share a directory,
    and a profile is never started twice while its pid is alive.
    """

    def __init__(
        self,
        chromium_path: Path | None = None,
        logs_dir: Path | None = None,
        stop_timeout: float = 10.0,
        proxy_probe=None,
        log_sink: "LogSink | None" = None,
        enable_stealth: bool = True,
        stealth_applier=None,
        stealth_daemon_factory=None,
    ) -> None:
        self._chromium_path = chromium_path
        self._logs_dir = logs_dir
        self._stop_timeout = stop_timeout
        # Optional application log funnel (see app.application.log_service).
        self._log = log_sink
        # Injected proxy liveness probe (tests stub it; production uses the
        # real end-to-end check from transport.probe_proxy).
        self._proxy_probe = proxy_probe
        # CDP stealth injection (tests disable it or stub the applier; see
        # app.infrastructure.stealth.cdp.apply_stealth for the default).
        self._enable_stealth = enable_stealth
        self._stealth_applier = stealth_applier
        self._stealth_daemon_factory = stealth_daemon_factory
        # pid -> persistent tab-patcher keeping every new tab spoofed.
        self._stealth_daemons: dict[int, object] = {}
        # pid -> (Popen, profile dir) of every process this manager launched.
        # Keeping the handles lets us reap children (no zombies) and distinguish
        # our own browser processes from recycled pids.
        self._processes: dict[int, tuple[subprocess.Popen, Path]] = {}
        # pid -> local proxy shim injected for that profile's upstream proxy.
        self._shims: dict[int, LocalProxyShim] = {}

    # ------------------------------------------------------------------ start

    def start(
        self,
        profile_path: Path,
        configuration: BrowserConfiguration,
        proxy: Proxy | None = None,
    ) -> int:
        binary = self._chromium_path or discover_chromium()
        profile_path.mkdir(parents=True, exist_ok=True)
        binary_version = chromium_binary_version(Path(str(binary)))
        self._log_info(
            "chromium",
            f"Launching Chromium for {profile_path.name}",
            extra={
                "binary": str(binary),
                "binary_version": binary_version,
                "binary_source": "configured" if self._chromium_path else "auto",
                "profile": str(profile_path),
                "configuration": _log_configuration(configuration),
            },
        )

        args = [
            str(binary),
            f"--user-data-dir={profile_path}",
            *_STEALTH_FLAGS,
            _REMOTE_DEBUGGING_FLAG,
        ]
        if _needs_no_sandbox():
            args.extend(("--no-sandbox", "--disable-dev-shm-usage"))
        args.extend(_configuration_flags(configuration))
        shim: LocalProxyShim | None = None
        if proxy is not None:
            # Fail fast instead of handing Chromium a proxy that will make it
            # spin forever (e.g. HTTP-only proxies that cannot CONNECT to 443,
            # which the search page is served over).
            self._log_info(
                "proxy",
                f"Probing proxy {_log_proxy(proxy)} before launch",
                extra={"proxy_id": proxy.id, "proxy": _log_proxy(proxy)},
            )
            self._probe_or_raise(proxy)
            self._log_info("proxy", f"Proxy {_log_proxy(proxy)} is usable")
            if proxy.username:
                # Chromium ignores credentials embedded in --proxy-server, so a
                # proxy requiring auth would spin forever (endless 407 retry).
                # Route the profile through a local shim that authenticates to
                # the real upstream instead of relying on Chromium to do it.
                try:
                    shim = LocalProxyShim(proxy).start()
                except OSError as exc:
                    self._log_error(
                        "proxy",
                        f"Failed to start proxy shim for {_log_proxy(proxy)}: {exc}",
                    )
                    raise ChromiumError(
                        f"Failed to start proxy shim: {exc}"
                    ) from exc
                args.append(f"--proxy-server={shim.proxy_server_url}")
                self._log_info(
                    "proxy",
                    "Authenticating proxy routed through local shim",
                    extra={"shim_url": shim.proxy_server_url, "proxy": _log_proxy(proxy)},
                )
            else:
                args.append(f"--proxy-server={_proxy_server_url(proxy)}")
                self._log_info(
                    "proxy",
                    f"Applying --proxy-server for {_log_proxy(proxy)}",
                    extra={"proxy": _log_proxy(proxy)},
                )

        stdout_path, stderr_path = self._log_files(profile_path)
        stdout_file = open(stdout_path, "ab")
        stderr_file = open(stderr_path, "ab")
        files_open = True
        try:
            try:
                process = subprocess.Popen(
                    args,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    **_popen_kwargs(),
                )
            except OSError as exc:
                self._log_error("chromium", f"Failed to launch Chromium: {exc}")
                raise ChromiumError(f"Failed to launch Chromium: {exc}") from exc
            finally:
                # The child duplicates the fds; close the parent copies right
                # away so log files are not locked (Windows) / leaked (POSIX).
                if files_open:
                    try:
                        stdout_file.close()
                    except OSError:
                        pass
                    try:
                        stderr_file.close()
                    except OSError:
                        pass
                    files_open = False

            # Some Chromium launchers fork and the direct child exits
            # immediately. Require the process to survive a short stabilization
            # window; the follow-up confirmation poll catches a binary that was
            # still loading during the window and only then exited (classic
            # slow-exec + instant exit race) into a launch failure.
            deadline = time.monotonic() + 10.0
            first_seen: float | None = None
            while time.monotonic() < deadline:
                code = process.poll()
                if code is not None:
                    self._log_error(
                        "chromium",
                        f"Chromium exited immediately with code {code}",
                        extra={"stderr": str(stderr_path)},
                    )
                    raise ChromiumError(
                        f"Chromium exited immediately with code {code}. "
                        f"See {stderr_path}"
                    )
                if first_seen is None:
                    first_seen = time.monotonic()
                if time.monotonic() - first_seen >= 0.25:
                    break
                time.sleep(0.05)
            else:
                self._log_error(
                    "chromium",
                    "Chromium did not start within the timeout",
                    extra={"stderr": str(stderr_path)},
                )
                raise ChromiumError(
                    f"Chromium did not start within the timeout. See {stderr_path}"
                )

            for _ in range(2):
                time.sleep(0.05)
                if process.poll() is not None:
                    self._log_error(
                        "chromium",
                        f"Chromium exited immediately with code {process.returncode}",
                        extra={"stderr": str(stderr_path)},
                    )
                    raise ChromiumError(
                        f"Chromium exited immediately with code {process.returncode}. "
                        f"See {stderr_path}"
                    )

            self._inject_stealth_or_raise(process, profile_path, configuration)
        except BaseException:
            if shim is not None:
                shim.close()
            if files_open:
                try:
                    stdout_file.close()
                except OSError:
                    pass
                try:
                    stderr_file.close()
                except OSError:
                    pass
            raise

        self._processes[process.pid] = (process, Path(profile_path))
        if shim is not None:
            self._shims[process.pid] = shim
        try:
            self._start_stealth_daemon(process.pid, Path(profile_path), configuration)
        except BaseException as exc:
            self._stop_process(process, Path(profile_path), self._stop_timeout)
            self._processes.pop(process.pid, None)
            if shim is not None:
                self._shims.pop(process.pid, None)
                shim.close()
            raise
        self._log_info(
            "chromium",
            f"Chromium started (pid {process.pid})",
            extra={
                "pid": int(process.pid),
                "profile": str(profile_path),
                "stdout_log": str(stdout_path),
                "stderr_log": str(stderr_path),
            },
        )
        # Stream the browser's own output into the same log so errors raised
        # inside Chromium are visible next to the launch/proxy entries.
        if self._log is not None and hasattr(self._log, "tail_file"):
            self._log.tail_file("chromium.stdout", stdout_path)
            self._log.tail_file("chromium.stderr", stderr_path)
        return int(process.pid)

    def binary_major(self) -> int | None:
        """Major version of the configured/discovered browser binary (if probed)."""
        from app.infrastructure.chromium.paths import discover_chromium

        from app.domain.errors import ChromiumNotFoundError

        binary = self._chromium_path
        if binary is None:
            try:
                binary = discover_chromium()
            except ChromiumNotFoundError:
                return None
        return chromium_binary_major(Path(str(binary)))

    def _probe_or_raise(self, proxy: Proxy) -> None:
        probe = self._proxy_probe or probe_proxy
        try:
            usable = probe(proxy, _PROXY_PROBE_TIMEOUT)
        except Exception as exc:
            self._log_error(
                "proxy",
                f"Proxy {_log_proxy(proxy)} unusable: {exc}",
                extra={"proxy": _log_proxy(proxy), "error": str(exc)},
            )
            raise ChromiumError(
                f"Proxy {proxy.host}:{proxy.port} is unusable: {exc}"
            ) from exc
        if not usable:
            self._log_error(
                "proxy",
                f"Proxy {_log_proxy(proxy)} is not working (no end-to-end request)",
                extra={"proxy": _log_proxy(proxy)},
            )
            raise ChromiumError(
                f"Proxy {proxy.host}:{proxy.port} is not working — it failed "
                "an end-to-end request (dead, or unable to reach HTTPS sites)."
            )

    def _inject_stealth_or_raise(
        self,
        process: subprocess.Popen,
        profile_path: Path,
        configuration: BrowserConfiguration,
    ) -> None:
        """Apply CDP stealth overrides; fail-closed with process teardown.

        Bare configurations (no spoofed fields) skip injection entirely. Any
        injection failure kills the just-launched browser before its pid is
        registered, so callers never receive a half-spoofed profile.
        """
        from app.infrastructure.stealth.cdp import needs_stealth

        if not self._enable_stealth or not needs_stealth(configuration):
            return
        applier = self._stealth_applier or _default_stealth_applier
        try:
            applied = applier(Path(profile_path), configuration)
        except BaseException as exc:
            self._log_error(
                "chromium",
                f"Stealth injection failed, terminating pid {process.pid}: {exc}",
            )
            try:
                self._signal_group(process.pid, _SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._signal_group(process.pid, _SIGKILL)
            except Exception:
                pass
            from app.domain.errors import StealthError

            if isinstance(exc, StealthError):
                raise
            raise StealthError(f"Stealth injection failed: {exc}") from exc
        self._log_info(
            "chromium",
            f"Stealth overrides applied for {profile_path.name}",
            extra={"applied": applied},
        )

    # ------------------------------------------------------------------- stop

    def stop(self, profile_path: Path, pid: int, timeout: float | None = None) -> None:
        timeout = timeout or self._stop_timeout
        self._log_info(
            "chromium",
            f"Stopping Chromium pid {pid}",
            extra={"pid": pid, "profile": str(profile_path)},
        )
        registered = self._processes.get(pid)
        if registered is not None:
            process, bound_dir = registered
            self._stop_process(process, bound_dir, timeout)
            self._processes.pop(pid, None)
            self._close_shim(pid)
            self._close_stealth(pid)
            self._log_info("chromium", f"Chromium pid {pid} stopped")
            return

        # Unknown to this manager instance (e.g. the CLI restarted). Fall back
        # to a raw signal + liveness poll.
        self._close_shim(pid)
        self._close_stealth(pid)
        if not self._is_pid_alive(pid):
            return
        try:
            _terminate_pid(pid, force=False)
        except PermissionError as exc:
            raise ChromiumError(f"Cannot terminate pid {pid}: {exc}") from exc
        except ProcessLookupError:
            return

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._is_alive_after_reap(pid):
            time.sleep(0.05)
        if self._is_alive_after_reap(pid):
            self._force_kill(pid)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self._is_alive_after_reap(pid):
                time.sleep(0.05)
        self._wait_profile_lock_released(profile_path, timeout)

    def _close_shim(self, pid: int) -> None:
        """Stop and forget the proxy shim bound to a profile's pid (if any)."""
        shim = self._shims.pop(pid, None)
        if shim is not None:
            shim.close()

    def _start_stealth_daemon(
        self, pid: int, profile_path: Path, configuration: BrowserConfiguration
    ) -> None:
        """Launch the persistent tab-patcher; fail-closed like the injection."""
        from app.infrastructure.stealth.cdp import needs_stealth

        if not self._enable_stealth or not needs_stealth(configuration):
            return
        factory = self._stealth_daemon_factory or _default_daemon_factory
        try:
            daemon = factory(Path(profile_path), configuration)
        except BaseException as exc:
            self._log_error(
                "chromium",
                f"Stealth daemon failed to start: {exc}",
            )
            from app.domain.errors import StealthError

            if isinstance(exc, StealthError):
                raise
            raise StealthError(f"Stealth daemon failed to start: {exc}") from exc
        if daemon is not None:
            self._stealth_daemons[pid] = daemon

    def _close_stealth(self, pid: int) -> None:
        """Stop and forget the stealth daemon bound to a profile's pid."""
        daemon = self._stealth_daemons.pop(pid, None)
        if daemon is not None:
            try:
                daemon.close()
            except Exception:
                pass

    def _stop_process(self, process: subprocess.Popen, bound_dir: Path, timeout: float) -> None:
        # The whole process group is signalled so renderer/zygote children are
        # torn down together with the main browser process, not left behind.
        pgid = process.pid
        self._signal_group(pgid, _SIGTERM)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._signal_group(pgid, _SIGKILL)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                raise ChromiumError(
                    f"Chromium pid {process.pid} did not exit after force kill"
                )
        self._wait_profile_lock_released(bound_dir, timeout)

    def _signal_group(self, pgid: int, sig: int) -> None:
        if _is_windows():
            # No POSIX process groups on Windows: kill the whole job tree so
            # renderer/zygote children die together with the main process.
            force = sig == _SIGKILL
            try:
                subprocess.run(
                    ["taskkill", "/T", "/PID", str(pgid)] + (["/F"] if force else []),
                    capture_output=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError):
                self._force_kill(pgid)
            return
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _wait_profile_lock_released(self, profile_path: Path, timeout: float) -> None:
        """Wait for Chromium to drop its per-profile singleton lock.

        A freshly restarted profile must not race the previous instance's
        shutdown, or the new browser would exit immediately seeing the lock.
        Windows holds SingletonCookie/SingletonSocket in addition to
        SingletonLock, so wait on all of them.
        """
        locks = (
            profile_path / "SingletonLock",
            profile_path / "SingletonCookie",
            profile_path / "SingletonSocket",
        )
        deadline = time.monotonic() + min(timeout, 5.0)
        while time.monotonic() < deadline and any(lock.exists() for lock in locks):
            time.sleep(0.05)

    def _force_kill(self, pid: int) -> None:
        if _is_windows():
            _terminate_pid(pid, force=True)
            return
        try:
            os.kill(pid, _SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    # ---------------------------------------------------------- liveness check

    def is_running(self, profile_path: Path, pid: int | None) -> bool:
        if pid is None or pid <= 0:
            return False
        registered = self._processes.get(pid)
        if registered is not None:
            process, bound_dir = registered
            if process.poll() is not None:
                self._processes.pop(pid, None)
                self._close_shim(pid)
                self._close_stealth(pid)
                return False
            return os.path.normcase(str(bound_dir)) == os.path.normcase(str(profile_path))
        if not self._is_alive_after_reap(pid):
            return False
        # Guard against pid reuse: verify the live process actually owns this
        # profile directory before reporting RUNNING.
        return user_data_dir_arg_contains(pid, profile_path)

    # ---------------------------------------------------------------- helpers

    def _is_pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            # Windows raises OSError (not ProcessLookupError) for dead pids
            # in some configurations — fall back to tasklist.
            if _is_windows():
                return _windows_pid_alive(pid)
            return False
        if _is_windows():
            # os.kill(pid, 0) on Windows only checks permissions, not liveness.
            return _windows_pid_alive(pid)
        return True

    def _is_alive_after_reap(self, pid: int) -> bool:
        """Liveness check that also reaps zombies of this child when possible."""
        registered = self._processes.get(pid)
        if registered is not None:
            return registered[0].poll() is None
        if not self._is_pid_alive(pid):
            return False
        if _is_windows():
            return True
        try:
            from os import WNOHANG, waitpid

            reaped_pid, status = waitpid(pid, WNOHANG)
        except ChildProcessError:
            # ECHILD: not one of our children (external process); the signal
            # probe above already confirmed it is alive.
            return True
        except ProcessLookupError:
            return False
        if reaped_pid == 0:
            return True  # still running, not yet exited
        return not (os.WIFEXITED(status) or os.WIFSIGNALED(status))

    def _log_files(self, profile_path: Path) -> tuple[Path, Path]:
        base = self._logs_dir or profile_path / ".logs"
        base.mkdir(parents=True, exist_ok=True)
        return base / "chromium.stdout.log", base / "chromium.stderr.log"

    # ------------------------------------------------------------ logging

    def _log_info(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.info(source, message, extra)

    def _log_error(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.error(source, message, extra)


def _configuration_flags(configuration: BrowserConfiguration) -> list[str]:
    """Map a stored configuration onto Chromium command-line switches.

    Everything Chromium can do via launch switches is applied here; the
    fingerprint fields that only a live renderer can change (WebGL vendor /
    renderer, hardware concurrency, colour depth) are stored for the future
    GUI/CDP layer and deliberately *not* forged via flags.
    """
    flags: list[str] = []
    if configuration.user_agent:
        flags.append(f"--user-agent={configuration.user_agent}")
    lang = configuration.language_tag
    if lang:
        flags.append(f"--lang={lang}")
    if configuration.locale and configuration.language:
        flags.append(
            f"--accept-lang={configuration.locale},{configuration.language}"
        )
    if configuration.timezone:
        flags.append(f"--timezone-id={configuration.timezone}")
    if configuration.screen_width and configuration.screen_height:
        flags.append(
            f"--window-size={configuration.screen_width},{configuration.screen_height}"
        )
    if configuration.device_pixel_ratio:
        flags.append(
            f"--force-device-scale-factor={configuration.device_pixel_ratio:g}"
        )
    return flags


def _default_stealth_applier(profile_path: Path, configuration: BrowserConfiguration):
    """Production CDP injection entry point (lazy import keeps the module
    importable without the websocket-client dependency installed)."""
    from app.infrastructure.stealth.cdp import apply_stealth

    return apply_stealth(profile_path, configuration)


def _default_daemon_factory(profile_path: Path, configuration: BrowserConfiguration):
    """Production persistent tab-patcher entry point (lazy import, see above)."""
    from app.infrastructure.stealth.cdp import start_daemon

    return start_daemon(profile_path, configuration)


def _proxy_server_url(proxy: Proxy) -> str:
    """Encode a stored proxy into Chromium's ``--proxy-server`` URI.

    ``scheme://user:pass@host:port`` is understood by Chromium for HTTP(S) and
    ``socks5://`` for SOCKS5. Credentials are percent-encoded so passwords with
    ``@`` or ``:`` do not corrupt the URI.
    """
    scheme = proxy.protocol.value.lower()
    credentials = ""
    if proxy.username:
        credentials = (
            f"{quote(proxy.username, safe='')}:{quote(proxy.password or '', safe='')}@"
        )
    return f"{scheme}://{credentials}{proxy.host}:{proxy.port}"


def _log_proxy(proxy: Proxy) -> str:
    """Human-safe proxy descriptor that never exposes the password."""
    scheme = proxy.protocol.value.lower()
    return f"{scheme}://{proxy.host}:{proxy.port}"


def _log_configuration(configuration: BrowserConfiguration) -> dict:
    """Condensed configuration snapshot for log `extra` payloads."""
    hints = configuration.client_hints or {}
    return {
        "name": configuration.name,
        "user_agent": bool(configuration.user_agent),
        "client_hints": (
            f"{hints.get('platform')}/{hints.get('fullVersion')}" if hints else None
        ),
        "language": configuration.language_tag,
        "timezone": configuration.timezone,
        "screen": (
            f"{configuration.screen_width}x{configuration.screen_height}"
            if configuration.screen_width and configuration.screen_height
            else None
        ),
    }


def _windows_pid_alive(pid: int) -> bool:
    """Confirm a pid really exists via tasklist (os.kill(pid,0) is not enough)."""
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return True  # fail-open: do not report a live browser as dead
    return str(pid) in (completed.stdout or "")


def _cmdline_matches(cmdline: str, profile_path: Path) -> bool:
    """Exact --user-data-dir match (avoids profile_001 ⊂ profile_0010 bug)."""
    import re

    text = cmdline.strip()
    if not text:
        return False
    # Chrome passes --user-data-dir=<path>, possibly quoted on Windows.
    candidates = {str(profile_path), str(Path(profile_path))}
    try:
        resolved = str(Path(profile_path).resolve())
        candidates.add(resolved)
    except OSError:
        pass
    # Fallback: tokenise and compare the flag value exactly.
    for match in re.finditer(r"--user-data-dir=(\"[^\"]+\"|\S+)", text):
        value = match.group(1).strip().strip('"')
        if value in candidates:
            return True
        if _is_windows() and value.casefold() in {c.casefold() for c in candidates}:
            return True
    return False


def _linux_proc_cmdline(pid: int) -> str | None:
    """Read /proc/<pid>/cmdline when `ps` is missing (minimal containers)."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return raw.replace(b"\x00", b" ").decode(errors="ignore")


def user_data_dir_arg_contains(pid: int, profile_path: Path) -> bool:
    """Return True if the command line of ``pid`` references ``profile_path``.

    Implemented per-platform:
      * Windows: PowerShell CIM query, fallback to `tasklist` verbose.
      * Linux: /proc/<pid>/cmdline first (full, untruncated), then `ps`.
      * Other POSIX (macOS): `ps -o command=`.
    Matching is an exact --user-data-dir comparison, not a substring.
    """
    if _is_windows():
        # ``wmic`` is deprecated/removed on modern Windows, so query the
        # command line through PowerShell's CIM provider instead.
        for command in (
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\").CommandLine",
            ],
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-Process -Id {pid}).Path"],
        ):
            try:
                output = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout or ""
            except (OSError, subprocess.SubprocessError):
                continue
            if output.strip() and _cmdline_matches(output, profile_path):
                return True
            # PowerShell present but returned empty (constrained language,
            # no CIM) — try the next probe rather than failing closed.
            if output.strip():
                return False
        return False

    # NOTE: /proc goes first on Linux because `ps -o command=` truncates
    # the command line to display width (no tty in CI/services), cutting
    # off --user-data-dir and producing false "not running" verdicts.
    # The old order (ps first, /proc only when ps output is empty) never
    # reached the fallback: truncated output is still non-empty.
    proc = _linux_proc_cmdline(pid)
    if proc is not None and proc.strip():
        return _cmdline_matches(proc, profile_path)
    try:
        output = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout or ""
    except (OSError, subprocess.SubprocessError):
        output = ""
    if output.strip():
        return _cmdline_matches(output, profile_path)
    if proc is not None:
        return _cmdline_matches(proc, profile_path)
    return False