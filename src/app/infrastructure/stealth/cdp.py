"""CDP stealth injection for launched Chromium profiles.

Why this module exists: ``--user-agent=...`` only changes the HTTP
``User-Agent`` header and part of ``navigator.userAgent``. Google (and
2ip-style checkers) read the *renderer* surface instead:

* ``Sec-CH-UA`` / ``navigator.userAgentData`` (come from the real binary),
* ``navigator.platform`` (``MacIntel`` on macOS regardless of the UA flag),
* WebGL ``UNMASKED_VENDOR/RENDERER`` (real GPU, e.g. Apple M2),
* ``navigator.hardwareConcurrency`` / ``deviceMemory`` / ``webdriver``.

All of these are overridden here over the DevTools protocol right after the
browser process stabilizes and *before* the user navigates anywhere. Any
protocol failure raises :class:`StealthError` (fail-closed): a half-spoofed
profile is exactly what Google rejects with "browser is not secure".
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.errors import StealthError
from app.domain.models.browser_configuration import BrowserConfiguration

_DEVTOOLS_PORT_FILE = "DevToolsActivePort"
_DISCOVERY_TIMEOUT = 15.0
_DISCOVERY_POLL = 0.25
_CDP_TIMEOUT = 10.0

_JS_PLATFORM = {"windows": "Win32", "macos": "MacIntel", "linux": "Linux x86_64"}


@dataclass(frozen=True)
class StealthSpec:
    """Renderer-facing fingerprint derived from a stored configuration."""

    user_agent: str
    brands: tuple[dict[str, str], ...]
    full_version: str
    hints_platform: str
    hints_platform_version: str
    architecture: str
    bitness: str
    accept_language: str
    languages: tuple[str, ...]
    timezone_id: str | None
    js_platform: str
    webgl_vendor: str | None
    webgl_renderer: str | None
    cores: int | None
    device_memory: int | None
    color_depth: int | None


def needs_stealth(configuration: BrowserConfiguration) -> bool:
    """Whether a configuration carries spoofed fields requiring CDP injection."""
    return bool(
        configuration.user_agent
        or configuration.client_hints
        or configuration.webgl_settings
        or configuration.hardware_settings
    )


def spec_from_configuration(
    configuration: BrowserConfiguration,
) -> StealthSpec | None:
    """Build the renderer spec, or None for a bare (non-spoofed) configuration."""
    if not needs_stealth(configuration):
        return None
    if not configuration.user_agent:
        raise StealthError(
            "Configuration spoofs renderer fields (WebGL/hardware/hints) "
            "without a user_agent; regenerate it coherently."
        )
    hints = configuration.client_hints or {}
    brands = hints.get("brands") or [
        {"brand": "Chromium", "version": "152"},
        {"brand": "Google Chrome", "version": "152"},
        {"brand": "Not-A.Brand", "version": "99"},
    ]
    full_version = str(hints.get("fullVersion") or "152.0.0.0")
    hints_platform = str(hints.get("platform") or "Windows")
    webgl = configuration.webgl_settings or {}
    hardware = configuration.hardware_settings or {}
    languages: list[str] = []
    if configuration.locale:
        languages.append(configuration.locale)
    if configuration.language and configuration.language not in languages:
        languages.append(configuration.language)
    if not languages:
        languages.append("en-US")
    accept = ", ".join(languages)
    if configuration.locale and configuration.language:
        accept = f"{configuration.locale},{configuration.language};q=0.9"
    return StealthSpec(
        user_agent=configuration.user_agent,
        brands=tuple(dict(b) for b in brands),
        full_version=full_version,
        hints_platform=hints_platform,
        hints_platform_version=str(hints.get("platformVersion") or "15.0.0"),
        architecture=str(hints.get("architecture") or "x86"),
        bitness=str(hints.get("bitness") or "64"),
        accept_language=accept,
        languages=tuple(languages),
        timezone_id=configuration.timezone,
        js_platform=_JS_PLATFORM.get(configuration.platform or "", "Win32"),
        webgl_vendor=webgl.get("vendor"),
        webgl_renderer=webgl.get("renderer"),
        cores=hardware.get("cores"),
        device_memory=hardware.get("device_memory_gb"),
        color_depth=configuration.color_depth,
    )


def _stealth_js(spec: StealthSpec) -> str:
    """JS evaluated on every new document before page scripts run."""
    payload = {
        "platform": spec.js_platform,
        "brands": [dict(b) for b in spec.brands],
        "mobile": False,
        "hintsPlatform": spec.hints_platform,
        "platformVersion": spec.hints_platform_version,
        "architecture": spec.architecture,
        "bitness": spec.bitness,
        "languages": list(spec.languages),
        "webglVendor": spec.webgl_vendor,
        "webglRenderer": spec.webgl_renderer,
        "cores": spec.cores,
        "deviceMemory": spec.device_memory,
        "colorDepth": spec.color_depth,
    }
    return (
        "(function(spec){"
        "try{Object.defineProperty(navigator,'webdriver',{get:function(){return false;},configurable:true});}catch(e){}"
        "try{Object.defineProperty(navigator,'platform',{get:function(){return spec.platform;},configurable:true});}catch(e){}"
        "try{"
        "var data={brands:spec.brands,mobile:spec.mobile,platform:spec.hintsPlatform,"
        "getHighEntropyValues:function(){return Promise.resolve({"
        "brands:spec.brands,mobile:spec.mobile,platform:spec.hintsPlatform,"
        "platformVersion:spec.platformVersion,architecture:spec.architecture,"
        "bitness:spec.bitness,model:'',fullVersionList:spec.brands});}};"
        "Object.defineProperty(navigator,'userAgentData',{get:function(){return data;},configurable:true});"
        "}catch(e){}"
        "try{Object.defineProperty(navigator,'languages',{get:function(){return spec.languages.slice();},configurable:true});}catch(e){}"
        "try{Object.defineProperty(navigator,'language',{get:function(){return spec.languages[0];},configurable:true});}catch(e){}"
        "if(spec.cores){try{Object.defineProperty(navigator,'hardwareConcurrency',{get:function(){return spec.cores;},configurable:true});}catch(e){}}"
        "if(spec.deviceMemory){try{Object.defineProperty(navigator,'deviceMemory',{get:function(){return spec.deviceMemory;},configurable:true});}catch(e){}}"
        "if(spec.colorDepth){try{Object.defineProperty(screen,'colorDepth',{get:function(){return spec.colorDepth;},configurable:true});}catch(e){}}"
        "try{if(!window.chrome){window.chrome={};}if(!window.chrome.runtime){window.chrome.runtime={};}}catch(e){}"
        "try{"
        "var hook=function(proto){if(!proto||!proto.getParameter){return;}"
        "var orig=proto.getParameter;"
        "proto.getParameter=function(p){"
        "if(p===0x9245&&spec.webglVendor){return spec.webglVendor;}"
        "if(p===0x9246&&spec.webglRenderer){return spec.webglRenderer;}"
        "return orig.call(this,p);};};"
        "hook(window.WebGLRenderingContext&&WebGLRenderingContext.prototype);"
        "hook(window.WebGL2RenderingContext&&WebGL2RenderingContext.prototype);"
        "}catch(e){}"
        "})(" + json.dumps(payload, ensure_ascii=False) + ");"
    )


def _devtools_port(profile_path: Path, timeout: float) -> int:
    """Read the loopback DevTools port Chromium wrote into the profile dir."""
    port_file = Path(profile_path) / _DEVTOOLS_PORT_FILE
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            text = port_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        first = (text.splitlines() or [""])[0].strip()
        if first.isdigit():
            return int(first)
        time.sleep(_DISCOVERY_POLL)
    raise StealthError(
        f"DevTools port file {port_file} did not appear within {timeout:g}s; "
        "the browser may have been launched without remote debugging."
    )


def _http_json(url: str, timeout: float) -> Any:
    """GET a DevTools HTTP endpoint, retrying until timeout (browser warmup)."""
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            last_error = str(exc)
            time.sleep(_DISCOVERY_POLL)
    raise StealthError(f"DevTools endpoint {url} unreachable: {last_error}")


def discover_page_target(profile_path: Path, timeout: float = _DISCOVERY_TIMEOUT) -> str:
    """Return the first page target's debugger WebSocket URL."""
    targets = discover_page_targets(profile_path, timeout=timeout)
    return targets[0]


def discover_page_targets(
    profile_path: Path, timeout: float = _DISCOVERY_TIMEOUT
) -> list[str]:
    """Return debugger WebSocket URLs of *all* page targets (every open tab)."""
    port = _devtools_port(Path(profile_path), timeout)
    targets = _http_json(f"http://127.0.0.1:{port}/json/list", timeout)
    if not isinstance(targets, list):
        raise StealthError("DevTools target list returned non-list payload.")
    pages = [
        str(target["webSocketDebuggerUrl"])
        for target in targets
        if isinstance(target, dict)
        and target.get("type") == "page"
        and target.get("webSocketDebuggerUrl")
    ]
    if pages:
        return pages
    fallbacks = [
        str(target["webSocketDebuggerUrl"])
        for target in targets
        if isinstance(target, dict) and target.get("webSocketDebuggerUrl")
    ]
    if fallbacks:
        return fallbacks
    raise StealthError("No debuggable page target found.")


def discover_browser_endpoint(
    profile_path: Path, timeout: float = _DISCOVERY_TIMEOUT
) -> str:
    """Return the browser-level debugger WebSocket URL (for auto-attach)."""
    port = _devtools_port(Path(profile_path), timeout)
    info = _http_json(f"http://127.0.0.1:{port}/json/version", timeout)
    if isinstance(info, dict) and info.get("webSocketDebuggerUrl"):
        return str(info["webSocketDebuggerUrl"])
    raise StealthError("No browser debugger endpoint found.")


class _CdpConnection:
    """Minimal blocking CDP client over websocket-client."""

    def __init__(self, ws_url: str, timeout: float = _CDP_TIMEOUT) -> None:
        try:
            import websocket  # type: ignore[import-not-found]
        except ImportError as exc:
            raise StealthError(
                "websocket-client is required for stealth injection; "
                "install it with: pip install 'websocket-client>=1.8'"
            ) from exc
        try:
            # No Origin header: Chrome 111+ rejects websocket handshakes with
            # a non-allowlisted Origin (403) but accepts origin-less clients
            # like curl — and the socket is loopback-only anyway.
            self._ws = websocket.create_connection(
                ws_url, timeout=timeout, suppress_origin=True
            )
        except Exception as exc:
            raise StealthError(f"Could not connect to {ws_url}: {exc}") from exc
        self._next_id = 0

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._next_id += 1
        call_id = self._next_id
        envelope: dict[str, Any] = {"id": call_id, "method": method, "params": params or {}}
        if session_id is not None:
            envelope["sessionId"] = session_id
        self._ws.send(json.dumps(envelope))
        deadline = time.monotonic() + _CDP_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StealthError(f"CDP {method} timed out waiting for a reply.")
            self._ws.settimeout(remaining)
            try:
                raw = self._ws.recv()
            except Exception as exc:
                raise StealthError(f"CDP {method} connection failed: {exc}") from exc
            try:
                message = json.loads(raw)
            except ValueError:
                continue  # ignore non-JSON frames
            if (
                not isinstance(message, dict)
                or message.get("id") != call_id
                or message.get("sessionId") != session_id
            ):
                continue  # event broadcast or another session, not our reply
            if "error" in message:
                raise StealthError(f"CDP {method} rejected: {message['error']}")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


def apply_stealth(
    profile_path: Path,
    configuration: BrowserConfiguration,
    timeout: float = _DISCOVERY_TIMEOUT,
) -> dict[str, Any]:
    """Inject the full fingerprint into a running profile's renderer.

    Returns a summary of applied overrides. Skips (``{"skipped": True}``) bare
    configurations without spoofed fields. Raises :class:`StealthError` on any
    failure — callers must treat the profile as unusable.
    """
    # NOTE on CDP session semantics (verified empirically): overrides and
    # new-document scripts live only while their debugger session is open —
    # closing the connection reverts everything. This function therefore
    # *validates* that the override set is accepted (fail-closed on rejected
    # methods) and proves DevTools is reachable; persistence across navigations
    # and tabs comes from the StealthDaemon's permanent browser session.
    spec = spec_from_configuration(configuration)
    if spec is None:
        return {"skipped": True}
    metadata = {
        "brands": [dict(b) for b in spec.brands],
        "fullVersion": spec.full_version,
        "platform": spec.hints_platform,
        "platformVersion": spec.hints_platform_version,
        "architecture": spec.architecture,
        "bitness": spec.bitness,
        "mobile": False,
        "model": "",
    }
    applied: dict[str, Any] = {}
    patched_tabs = 0
    for ws_url in discover_page_targets(Path(profile_path), timeout=timeout):
        connection = _CdpConnection(ws_url)
        try:
            _patch_session(connection, spec, metadata, session_id=None)
        finally:
            connection.close()
        patched_tabs += 1
    if patched_tabs == 0:  # unreachable: discovery raises on empty lists
        raise StealthError("No page targets to patch.")
    applied["userAgent"] = True
    if spec.timezone_id:
        applied["timezone"] = spec.timezone_id
    applied["rendererPatch"] = True
    applied["tabs"] = patched_tabs
    return applied


def _patch_session(
    connection: "_CdpConnection",
    spec: StealthSpec,
    metadata: dict[str, Any],
    session_id: str | None,
) -> None:
    """Apply the full override set to one CDP session (tab)."""
    connection.call(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": spec.user_agent,
            "acceptLanguage": spec.accept_language,
            "userAgentMetadata": metadata,
        },
        session_id=session_id,
    )
    if spec.timezone_id:
        connection.call(
            "Emulation.setTimezoneOverride",
            {"timezoneId": spec.timezone_id},
            session_id=session_id,
        )
    connection.call("Page.enable", {}, session_id=session_id)
    connection.call(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": _stealth_js(spec)},
        session_id=session_id,
    )


class StealthDaemon:
    """Persistent per-profile CDP session that patches every new tab.

    ``apply_stealth`` covers tabs open at launch; tabs opened later (Ctrl+T,
    links, popups) would otherwise leak the real fingerprint. The daemon holds
    a browser-level connection with ``Target.setAutoAttach`` and injects the
    same overrides into each new page session. One daemon per running profile;
    closed by ``ChromiumManager.stop`` (mirrors the proxy-shim registry).
    """

    def __init__(self, browser_ws_url: str, spec: StealthSpec) -> None:
        import threading

        self._browser_ws_url = browser_ws_url
        self._spec = spec
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"stealth-{id(self):x}", daemon=True
        )
        self._started = False
        self._closed = False
        # Observability: patched target ids and the last background failure.
        self.patched_targets: list[str] = []
        self.last_error: str | None = None
        self._attached: set[str] = set()
        self._last_sweep: float = 0.0
        import os as _os

        self._trace_path = _os.environ.get("ANTIDETECT_STEALTH_TRACE")

    def _trace(self, message: str) -> None:
        if not self._trace_path:
            return
        try:
            with open(self._trace_path, "a", encoding="utf-8") as handle:
                handle.write(f"{time.monotonic():.2f} {message}\n")
        except OSError:
            pass

    def start(self) -> "StealthDaemon":
        self._thread.start()
        self._started = True
        return self

    def close(self) -> None:
        self._stop_event.set()
        if self._started:
            self._thread.join(timeout=5.0)
            self._started = False
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def running(self) -> bool:
        return self._started and self._thread.is_alive()

    def _metadata(self) -> dict[str, Any]:
        return {
            "brands": [dict(b) for b in self._spec.brands],
            "fullVersion": self._spec.full_version,
            "platform": self._spec.hints_platform,
            "platformVersion": self._spec.hints_platform_version,
            "architecture": self._spec.architecture,
            "bitness": self._spec.bitness,
            "mobile": False,
            "model": "",
        }

    # Tabs with no user state: safe to reload so the just-registered scripts
    # apply to a fresh document immediately (otherwise they wait for the next
    # user navigation). Never reload anything else (form/video loss).
    _PRISTINE_URLS = frozenset({"about:blank", "chrome://newtab/", "chrome://new-tab-page/"})

    def _attach_and_patch(
        self,
        connection: "_CdpConnection",
        metadata: dict[str, Any],
        target_id: str,
        *,
        reload_if_pristine: bool = False,
        page_url: str = "",
    ) -> None:
        """Explicitly attach to one page target and patch its session."""
        try:
            attached = connection.call(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
        except StealthError:
            return  # tab already gone or owned elsewhere
        session_id = attached.get("sessionId")
        if not session_id:
            return
        self._trace(f"attach {target_id[:8]} session {(session_id or '')[:8]}")
        try:
            _patch_session(connection, self._spec, metadata, session_id=session_id)
        except StealthError as exc:
            self.last_error = f"attach {target_id}: {exc}"
            self._trace(f"attach {target_id[:8]} FAILED {exc}")
            return  # tab closed mid-patch; nothing more to do
        self._attached.add(target_id)
        self.patched_targets.append(target_id)
        self._trace(f"attach {target_id[:8]} OK")
        if reload_if_pristine and page_url in self._PRISTINE_URLS:
            try:
                connection.call("Page.reload", {}, session_id=session_id)
                self._trace(f"reload {target_id[:8]} (pristine)")
            except StealthError as exc:
                self._trace(f"reload {target_id[:8]} skipped: {exc}")

    def _run(self) -> None:
        try:
            self._serve()
        except Exception as exc:  # never die silently; record and park
            self.last_error = f"daemon fatal: {exc}"

    def _sweep(
        self, connection: "_CdpConnection", metadata: dict[str, Any]
    ) -> None:
        """Attach to every page target not yet patched (startup race net).

        Runs once at startup and then periodically: a tab created between the
        initial sweep and setAutoAttach (or missed by it) is picked up on the
        next pass, deterministically.
        """
        try:
            listed = connection.call("Target.getTargets", {})
        except StealthError as exc:
            self.last_error = f"sweep: {exc}"
            return
        for info in listed.get("targetInfos") or []:
            if not isinstance(info, dict):
                continue
            if info.get("type") != "page" or not info.get("targetId"):
                continue
            target_id = str(info["targetId"])
            if target_id in self._attached:
                self._trace(f"sweep skip known {target_id[:8]}")
                continue
            url = str(info.get("url") or "")
            self._trace(f"sweep new {target_id[:8]} url={url[:50]}")
            self._attach_and_patch(
                connection, metadata, target_id,
                reload_if_pristine=True, page_url=url,
            )

    def _wait_settled(
        self, connection: "_CdpConnection", timeout: float = 20.0
    ) -> None:
        """Wait until Chrome's startup target churn stops.

        Verified empirically: attaching during the first seconds (targets
        appearing/disappearing as profile init completes) yields a dead
        registration — no error, but scripts never execute. The page-target
        set is polled until it is identical on two consecutive passes; only
        then does the first sweep attach.
        """
        previous: list[str] | None = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return
            try:
                listed = connection.call("Target.getTargets", {})
            except StealthError:
                time.sleep(0.5)
                continue
            current = sorted(
                str(info["targetId"])
                for info in listed.get("targetInfos") or []
                if isinstance(info, dict) and info.get("type") == "page" and info.get("targetId")
            )
            if previous is not None and current == previous:
                self._trace(f"settled with {len(current)} page(s)")
                return
            previous = current
            time.sleep(1.0)
        self._trace("settle timeout; proceeding anyway")

    def _serve(self) -> None:
        try:
            connection = _CdpConnection(self._browser_ws_url, timeout=_CDP_TIMEOUT)
        except StealthError as exc:
            self.last_error = f"connect: {exc}"
            return
        metadata = self._metadata()
        # 1. Let startup churn finish; early attaches register dead sessions.
        self._wait_settled(connection)
        if self._stop_event.is_set():
            connection.close()
            return
        # 2. Explicit sweep: pages that already exist. Never rely on
        # auto-attach alone — empirically it can miss the initial tab.
        self._sweep(connection, metadata)
        self._last_sweep = time.monotonic()
        # 2. Auto-attach for tabs opened later (plus explicit targetCreated
        # handling below as a second net).
        try:
            connection.call(
                "Target.setAutoAttach",
                {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True},
            )
        except StealthError:
            connection.close()
            return
        try:
            while not self._stop_event.is_set():
                # Periodic re-sweep closes the startup race: a tab born between
                # the initial sweep and setAutoAttach is caught on the next pass.
                if time.monotonic() - self._last_sweep >= 2.0:
                    self._sweep(connection, metadata)
                    self._last_sweep = time.monotonic()
                    if self._stop_event.is_set():
                        return
                connection._ws.settimeout(1.0)
                try:
                    raw = connection._ws.recv()
                except Exception:
                    if self._stop_event.is_set():
                        return
                    continue  # timeout tick or transient read error: keep polling
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                method = message.get("method")
                params = message.get("params") or {}
                if method in ("Target.attachedToTarget", "Target.detachedFromTarget", "Target.targetCreated", "Target.targetDestroyed", "Target.targetInfoChanged"):
                    info = params.get("targetInfo") or {}
                    self._trace(
                        f"event {method} type={info.get('type')} url={str(info.get('url'))[:60]} "
                        f"tid={str(info.get('targetId') or params.get('targetId') or '')[:8]}"
                    )
                if method == "Target.attachedToTarget":
                    session_id = params.get("sessionId")
                    target_info = params.get("targetInfo") or {}
                    if not session_id or target_info.get("type") not in ("page",):
                        continue
                    try:
                        _patch_session(connection, self._spec, metadata, session_id=session_id)
                    except StealthError as exc:
                        self.last_error = f"event-patch: {exc}"
                        self._trace(
                            f"event-patch FAILED tid={str(target_info.get('targetId') or '')[:8]} {exc}"
                        )
                        continue  # tab already gone; sweep will retry (not marked)
                    if target_info.get("targetId"):
                        self._attached.add(str(target_info["targetId"]))
                elif method == "Target.targetCreated":
                    target_info = params.get("targetInfo") or {}
                    if target_info.get("type") == "page" and target_info.get("targetId"):
                        self._attach_and_patch(
                            connection, metadata, str(target_info["targetId"])
                        )
        finally:
            connection.close()


def start_daemon(
    profile_path: Path,
    configuration: BrowserConfiguration,
    timeout: float = _DISCOVERY_TIMEOUT,
) -> StealthDaemon | None:
    """Start the persistent tab-patcher; None for bare configurations."""
    spec = spec_from_configuration(configuration)
    if spec is None:
        return None
    endpoint = discover_browser_endpoint(Path(profile_path), timeout=timeout)
    return StealthDaemon(endpoint, spec).start()
