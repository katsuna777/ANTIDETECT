from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from antidetect.application.fingerprint import privacy
from antidetect.domain.errors import ChromiumError
from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.domain.models.proxy import Proxy
from antidetect.infrastructure.chromium.paths import discover_chromium
from antidetect.infrastructure.chromium import preferences
from antidetect.infrastructure.chromium.proxy_shim import LocalProxyShim
from antidetect.infrastructure.proxy.transport import probe_proxy

if TYPE_CHECKING:
    from antidetect.application.ports import LogSink

_PROXY_PROBE_TIMEOUT = 6.0

# Allowlisted launch switches. Anything outside this set must go through an
# explicit code change + test update — silent flag drift is how profiles end
# up half-spoofed (UA without Client Hints) and get flagged as bots.
_STEALTH_FLAGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-features=Translate",
    "--no-first-run",
    "--no-default-browser-check",
    "--hide-crash-restore-bubble",
)
# NB: --force-webrtc-ip-handling-policy is deliberately absent. Chrome 154 ignores it (the real
# public IP still leaked as a WebRTC srflx candidate); the policy is written to the profile's
# Preferences instead, see infrastructure/chromium/preferences.py.
# Ephemeral DevTools endpoint for the CDP stealth layer. Chrome accepts a bare
# port only here (the host:port form is ignored and DevTools never starts);
# port 0 picks a free ephemeral port and Chrome binds it to 127.0.0.1, so it is
# never exposed on LAN.
_REMOTE_DEBUGGING_FLAG = "--remote-debugging-port=0"
# With stealth on, the browser starts with no window at all: the stealth layer
# attaches first and opens the first (already patched) tab itself, so no page —
# not even a restored one — can load before the fingerprint is in place.
_NO_STARTUP_WINDOW_FLAG = "--no-startup-window"

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
        stealth_factory=None,
        restore_session: bool = True,
        managed_browsers=None,
    ) -> None:
        self._chromium_path = chromium_path
        # The Chrome the app downloaded itself (None: the app downloads nothing, e.g. in tests).
        self._managed = managed_browsers
        self._logs_dir = logs_dir
        self._stop_timeout = stop_timeout
        # Optional application log funnel (see antidetect.application.log_service).
        self._log = log_sink
        # Injected proxy liveness probe (tests stub it; production uses the
        # real end-to-end check from transport.probe_proxy).
        self._proxy_probe = proxy_probe
        # CDP stealth layer (tests disable it or inject a factory; the default
        # is antidetect.infrastructure.stealth.cdp.start_daemon).
        self._enable_stealth = enable_stealth and os.environ.get(
            "ANTIDETECT_DISABLE_STEALTH", ""
        ).strip().lower() not in ("1", "true", "yes")
        self._stealth_factory = stealth_factory
        self._restore_session = restore_session
        # pid -> persistent target manager keeping every tab/frame/worker spoofed.
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
        start_url: str | None = None,
    ) -> int:
        binary, binary_source = self._locate()
        profile_path.mkdir(parents=True, exist_ok=True)
        binary_version = chromium_binary_version(Path(str(binary)))
        self._log_info(
            "chromium",
            f"Launching Chromium for {profile_path.name}",
            extra={
                "binary": str(binary),
                "binary_version": binary_version,
                "binary_source": binary_source,
                "profile": str(profile_path),
                "configuration": _log_configuration(configuration),
            },
        )

        spec = None
        if self._enable_stealth:
            spec = self._build_spec(binary, binary_version, profile_path, configuration)
        args = [
            str(binary),
            f"--user-data-dir={profile_path}",
            *_STEALTH_FLAGS,
            _REMOTE_DEBUGGING_FLAG,
        ]
        if spec is not None:
            args.append(_NO_STARTUP_WINDOW_FLAG)
        if _needs_no_sandbox():
            args.extend(("--no-sandbox", "--disable-dev-shm-usage"))
        args.extend(_configuration_flags(configuration, spec))
        args.extend(_scrollbar_arguments(spec))
        from antidetect.infrastructure.stealth.cdp import clear_stale_port_file

        clear_stale_port_file(profile_path)
        self._apply_webrtc_policy(profile_path, configuration, proxy)
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

            daemon = self._attach_stealth(process, profile_path, spec, start_url)
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
        if daemon is not None:
            self._stealth_daemons[process.pid] = daemon
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

    def set_chromium_path(self, path: Path | None) -> None:
        """Use ``path`` as the browser (``None`` = the app's own Chrome when it has one, else auto-discover)."""
        self._chromium_path = Path(path) if path else None

    def _locate(self) -> tuple[Path, str]:
        """The browser that will run profiles and where it came from.

        The user's explicit choice wins; then the Chrome the app downloaded (a version that does not
        move under the fingerprint); then whatever is installed on the computer.
        Raises :class:`ChromiumNotFoundError` when there is none.
        """
        if self._chromium_path is not None:
            return Path(self._chromium_path), "configured"
        if self._managed is not None:
            active = self._managed.active()
            if active is not None:
                return Path(active.executable), "managed"
        return Path(str(discover_chromium())), "auto"

    def browser_source(self) -> str:
        """``configured`` (the user's path), ``managed`` (downloaded by the app), ``auto`` (installed) or ``none``."""
        from antidetect.domain.errors import ChromiumNotFoundError

        try:
            return self._locate()[1]
        except ChromiumNotFoundError:
            return "none"

    def resolved_binary(self) -> Path | None:
        """The browser that would launch now, or None when none is installed."""
        from antidetect.domain.errors import ChromiumNotFoundError

        try:
            return self._locate()[0]
        except ChromiumNotFoundError:
            return None

    def binary_full_version(self) -> str | None:
        """Full version (``154.0.8037.93``) of the browser that will be launched."""
        import re

        binary = self.resolved_binary()
        if binary is None:
            return None
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", chromium_binary_version(Path(str(binary))) or "")
        return match.group(1) if match else None

    def binary_major(self) -> int | None:
        """Major version of the configured/discovered browser binary (if probed)."""
        binary = self.resolved_binary()
        return chromium_binary_major(Path(str(binary))) if binary is not None else None

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

    def _build_spec(self, binary, binary_version, profile_path: Path, configuration):
        """Resolve the stored configuration against the browser that will run."""
        import re

        from antidetect.application.fingerprint.identity import brand_for_binary
        from antidetect.infrastructure.stealth.spec import spec_from_configuration

        full_version = None
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", binary_version or "")
        if match:
            full_version = match.group(1)
        return spec_from_configuration(
            configuration,
            browser_version=full_version,
            browser_brand=brand_for_binary(str(binary)),
            seed=_profile_seed(profile_path),
        )

    def _attach_stealth(
        self, process: subprocess.Popen, profile_path: Path, spec, start_url: str | None = None
    ):
        """Attach the stealth layer and open the first patched tab.

        Fail-closed: any failure kills the just-launched browser before its pid
        is registered, so callers never receive a half-spoofed profile.
        """
        if spec is None:
            return None
        from antidetect.domain.errors import StealthError

        factory = self._stealth_factory or _default_stealth_factory
        daemon = None
        try:
            kwargs = {"restore_session": self._restore_session}
            if start_url:
                kwargs["start_urls"] = [start_url]
            daemon = factory(Path(profile_path), spec, **kwargs)
            if daemon is not None and hasattr(daemon, "wait_ready"):
                daemon.wait_ready()
        except BaseException as exc:
            self._log_error(
                "chromium",
                f"Stealth layer failed, terminating pid {process.pid}: {exc}",
            )
            if daemon is not None:
                try:
                    daemon.close()
                except Exception:
                    pass
            try:
                self._signal_group(process.pid, _SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._signal_group(process.pid, _SIGKILL)
            except Exception:
                pass
            if isinstance(exc, StealthError):
                raise
            raise StealthError(f"Stealth layer failed: {exc}") from exc
        self._log_info(
            "chromium",
            f"Stealth layer active for {profile_path.name}",
            extra={
                "platform": spec.platform_key,
                "user_agent": spec.user_agent,
                "timezone": spec.timezone_id,
                "locale": spec.locale,
            },
        )
        return daemon

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
            if not self._quit_gracefully(pid, process, min(timeout, 4.0)):
                self._stop_process(process, bound_dir, timeout)
            else:
                self._wait_profile_lock_released(bound_dir, timeout)
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

    def is_protected(self, pid: int) -> bool:
        """True when a live stealth layer is attached to ``pid``.

        The layer lives in *this* process: if the host program exits, tabs opened
        afterwards are no longer patched, so one-shot callers (the CLI) stay alive.
        """
        daemon = self._stealth_daemons.get(pid)
        return bool(daemon is not None and getattr(daemon, "running", True))

    def open_url(self, pid: int, url: str) -> bool:
        """Open ``url`` in a new tab of the running profile ``pid``."""
        daemon = self._stealth_daemons.get(pid)
        request = getattr(daemon, "request_open", None)
        if request is None:
            return False
        request(url)
        return True

    def _quit_gracefully(self, pid: int, process: subprocess.Popen, timeout: float) -> bool:
        """Browser.close through the stealth layer (tabs are snapshotted first).

        Returns True when the process exited; False means "fall back to signals".
        """
        daemon = self._stealth_daemons.get(pid)
        request = getattr(daemon, "request_close", None)
        if request is None:
            return False
        try:
            request()
            process.wait(timeout=timeout)
        except Exception:
            return process.poll() is not None
        return True

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

    def _apply_webrtc_policy(
        self, profile_path: Path, configuration: BrowserConfiguration, proxy: Proxy | None
    ) -> None:
        """Keep WebRTC from reaching the network around the proxy, as the profile's mode asks.

        ``auto`` blocks it behind a proxy and leaves it alone without one; ``block`` and ``allow``
        are the user's explicit choice. Fail closed: if a protection that is wanted cannot be put
        in place the launch is refused, because a started browser would show the real address
        next to the proxy's.
        """
        mode = privacy.resolve(configuration.privacy_settings)["webrtc"]
        policy = preferences.policy_for(mode, proxy is not None)
        try:
            preferences.set_webrtc_policy(profile_path, policy)
        except OSError as exc:
            if policy is None:
                self._log_error("chromium", f"Could not reset the WebRTC policy: {exc}")
                return
            self._log_error("chromium", f"Could not apply the WebRTC policy: {exc}")
            raise ChromiumError(f"Could not protect WebRTC for {profile_path.name}: {exc}") from exc
        if policy is not None:
            self._log_info("chromium", "WebRTC limited to proxied traffic", extra={"policy": policy, "mode": mode})
        elif mode == privacy.WEBRTC_ALLOW and proxy is not None:
            self._log_info("chromium", "WebRTC left open for this profile (mode: allow)", extra={"mode": mode})

    # ------------------------------------------------------------ logging

    def _log_info(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.info(source, message, extra)

    def _log_error(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.error(source, message, extra)


def _configuration_flags(configuration: BrowserConfiguration, spec=None) -> list[str]:
    """Launch switches that must be right *before* the CDP layer attaches.

    UA / language flags cover contexts CDP emulation does not reach (service
    workers, requests made before attach). Timezone, screen size and DPR are
    handled natively by the stealth layer and deliberately not forged here.
    """
    flags: list[str] = []
    if spec is not None and spec.screen is not None:
        # Decides (color-gamut) and (dynamic-range) natively: without it a Windows profile on a
        # P3/HDR Mac reports a wide-gamut HDR display, and every profile shares the host's.
        flags.append(f"--force-color-profile={spec.screen.color_profile}")
    user_agent = spec.user_agent if spec is not None else configuration.user_agent
    if user_agent:
        flags.append(f"--user-agent={user_agent}")
    if spec is not None and spec.languages:
        flags.append(f"--lang={spec.languages[0]}")
        flags.append(f"--accept-lang={','.join(spec.languages)}")
    elif configuration.language_tag:
        flags.append(f"--lang={configuration.language_tag}")
        if configuration.locale and configuration.language:
            flags.append(f"--accept-lang={configuration.locale},{configuration.language}")
    return flags


def _scrollbar_arguments(spec) -> list[str]:
    """Classic (always visible) scroll bars for a Windows or Linux profile on a Mac.

    macOS hides them until you scroll, so a page measuring ``offsetWidth - clientWidth`` gets 0,
    which no Windows or Linux Chrome ever reports (15 on a Mac with classic bars, 17 on Windows).
    Chrome has no switch for it; Cocoa reads ``-AppleShowScrollBars Always`` from the arguments as
    a setting of this one process, leaving the user's own Chrome alone. The value is also a loose
    argument to Chrome, which would open it as a page ("http://always/") - harmless only because
    the stealth layer starts Chrome with ``--no-startup-window`` (measured: no page is created).
    """
    from antidetect.application.fingerprint import data as fd

    if spec is None or spec.platform_key == "macos" or fd.host_platform() != "macos":
        return []
    return ["-AppleShowScrollBars", "Always"]


def _profile_seed(profile_path: Path) -> int:
    """Stable per-profile random seed (drives canvas/audio noise, jitter).

    Stored beside the profile so it survives restarts and config changes, and
    differs between profiles even when they share one configuration.
    """
    import secrets

    seed_file = Path(profile_path) / ".antidetect-seed"
    try:
        value = int(seed_file.read_text(encoding="utf-8").strip())
        if value > 0:
            return value
    except (OSError, ValueError):
        pass
    value = secrets.randbits(32) or 1
    try:
        seed_file.write_text(str(value), encoding="utf-8")
    except OSError:
        pass
    return value


def _default_stealth_factory(
    profile_path: Path, spec, restore_session: bool = True, start_urls=None
):
    """Production entry point (lazy import keeps this module importable
    without the websocket-client dependency installed)."""
    from antidetect.infrastructure.stealth.cdp import start_daemon

    return start_daemon(
        profile_path, spec, restore_session=restore_session, start_urls=start_urls
    )


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