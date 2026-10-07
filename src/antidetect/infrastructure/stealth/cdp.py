"""CDP target manager: applies the fingerprint to every tab, frame and worker.

How it stays race-free
----------------------
The browser is launched with ``--no-startup-window`` so nothing loads before we
are attached. We then ask for auto-attach with ``waitForDebuggerOnStart``: each
new target (tab, popup, out-of-process iframe, dedicated/shared/service worker)
is *paused before its first script runs*, patched, and only then resumed. The
same is requested recursively on every page/iframe session so that workers and
nested frames are caught too. Nothing the user opens — Ctrl+T, ``target=_blank``,
``window.open`` — can execute a script unpatched.

What is applied where
---------------------
* Natively through CDP (C++ level, no JS artifacts): user agent + full
  Client Hints, ``navigator.platform``, locale, timezone, hardware concurrency,
  screen size / DPR, geolocation.
* By the in-page payload (:mod:`.payload`): only what CDP cannot express
  (WebGL strings/limits, ``deviceMemory``, canvas/audio noise, worker scopes).

The daemon never enables the ``Runtime``/``Debugger`` domains, so the classic
"Runtime.enable" side channel stays silent.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from antidetect.domain.errors import StealthError
from antidetect.infrastructure.stealth.payload import build_payload
from antidetect.infrastructure.stealth.spec import StealthSpec

_DEVTOOLS_PORT_FILE = "DevToolsActivePort"
_SESSION_FILE = ".antidetect-session.json"
_DISCOVERY_TIMEOUT = 20.0
_DISCOVERY_POLL = 0.2
_CALL_TIMEOUT = 8.0
_INTERNAL_URL_PREFIXES = (
    "chrome://", "chrome-untrusted://", "chrome-extension://", "chrome-search://",
    "devtools://", "chrome-error://",
)
_RESTORE_SKIP = ("about:blank", "chrome://newtab/", "chrome://new-tab-page/", "")
_NEW_TAB_URL = "chrome://newtab/"
_MAX_RESTORED_TABS = 25
# Only these target kinds are paused and patched. Chrome 154 also exposes
# internal "browser_ui"/"other" targets (omnibox popup, prerender shells) that
# never answer runIfWaitingForDebugger — they must not be auto-attached at all.
_ATTACH_FILTER = [
    {"type": "page"},
    {"type": "iframe"},
    {"type": "worker"},
    {"type": "shared_worker"},
    {"type": "service_worker"},
    {"exclude": True},
]
_AUTO_ATTACH = {
    "autoAttach": True,
    "waitForDebuggerOnStart": True,
    "flatten": True,
    "filter": _ATTACH_FILTER,
}
_WORKER_TIMEOUT = 3.0


# --------------------------------------------------------------- discovery

def _read_devtools_port(profile_path: Path) -> int | None:
    try:
        text = (Path(profile_path) / _DEVTOOLS_PORT_FILE).read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return None
    first = (text.splitlines() or [""])[0].strip()
    return int(first) if first.isdigit() else None


def clear_stale_port_file(profile_path: Path) -> None:
    """Remove a leftover DevToolsActivePort so discovery never reads a dead port."""
    try:
        (Path(profile_path) / _DEVTOOLS_PORT_FILE).unlink()
    except OSError:
        pass


def read_devtools_endpoint(profile_path: Path) -> tuple[int, str] | None:
    """``(port, "/devtools/browser/<id>")`` of a running profile, from its DevToolsActivePort file.

    Chrome writes the port on line 1 and the browser-level WebSocket path on line 2. ``None``
    when the file is missing or unreadable (the profile is not running, or still starting).
    """
    try:
        lines = (Path(profile_path) / _DEVTOOLS_PORT_FILE).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return None
    if len(lines) < 2 or not lines[0].strip().isdigit() or not lines[1].strip().startswith("/devtools/"):
        return None
    return int(lines[0].strip()), lines[1].strip()


def cdp_call(ws_url: str, method: str, params: dict[str, Any] | None = None, *, timeout: float = _CALL_TIMEOUT) -> dict[str, Any]:
    """One browser-level CDP command over a short-lived connection (does not touch the stealth layer's session)."""
    conn = _CdpConnection(ws_url, timeout)
    try:
        return conn.call(method, params, timeout=timeout)
    finally:
        conn.close()


def discover_browser_endpoint(
    profile_path: Path, timeout: float = _DISCOVERY_TIMEOUT
) -> str:
    """Return the browser-level debugger WebSocket URL."""
    import urllib.request

    deadline = time.monotonic() + timeout
    last_error = "DevToolsActivePort did not appear"
    while time.monotonic() < deadline:
        port = _read_devtools_port(profile_path)
        if port is not None:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=2
                ) as response:
                    info = json.loads(response.read().decode("utf-8", errors="replace"))
                if isinstance(info, dict) and info.get("webSocketDebuggerUrl"):
                    return str(info["webSocketDebuggerUrl"])
                last_error = "no webSocketDebuggerUrl in /json/version"
            except Exception as exc:  # warm-up: port not listening yet
                last_error = str(exc)
        time.sleep(_DISCOVERY_POLL)
    raise StealthError(
        f"DevTools endpoint for {profile_path} unreachable within {timeout:g}s: {last_error}"
    )


# -------------------------------------------------------------- connection

class _CdpConnection:
    """Blocking CDP client with a response table and an event queue.

    ``call`` waits for its own reply while queueing any events that arrive, so
    event handlers can issue calls without recursing into each other.
    """

    def __init__(self, ws_url: str, timeout: float = _CALL_TIMEOUT) -> None:
        try:
            import websocket  # type: ignore[import-not-found]
        except ImportError as exc:
            raise StealthError(
                "websocket-client is required for stealth injection; "
                "install it with: pip install 'websocket-client>=1.8'"
            ) from exc
        self._websocket = websocket
        try:
            # Chrome 111+ rejects handshakes carrying a foreign Origin header.
            self._ws = websocket.create_connection(
                ws_url, timeout=timeout, suppress_origin=True
            )
        except Exception as exc:
            raise StealthError(f"Could not connect to {ws_url}: {exc}") from exc
        self._next_id = 0
        self._fired: set[int] = set()          # ids whose reply nobody waits for
        self._responses: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.closed = False

    def _read(self, timeout: float) -> bool:
        """Read one frame into the response table / event queue."""
        self._ws.settimeout(max(0.01, timeout))
        try:
            raw = self._ws.recv()
        except self._websocket.WebSocketTimeoutException:
            return False
        except Exception as exc:
            self.closed = True
            raise StealthError(f"CDP connection lost: {exc}") from exc
        try:
            message = json.loads(raw)
        except ValueError:
            return True
        if not isinstance(message, dict):
            return True
        if "id" in message:
            if int(message["id"]) in self._fired:
                self._fired.discard(int(message["id"]))
            else:
                self._responses[int(message["id"])] = message
        elif "method" in message:
            self.events.append(message)
        return True

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        *,
        timeout: float = _CALL_TIMEOUT,
        tolerate: bool = False,
    ) -> dict[str, Any]:
        self._next_id += 1
        call_id = self._next_id
        envelope: dict[str, Any] = {"id": call_id, "method": method, "params": params or {}}
        if session_id is not None:
            envelope["sessionId"] = session_id
        try:
            self._ws.send(json.dumps(envelope))
        except Exception as exc:
            self.closed = True
            raise StealthError(f"CDP {method} send failed: {exc}") from exc
        deadline = time.monotonic() + timeout
        while True:
            reply = self._responses.pop(call_id, None)
            if reply is not None:
                if "error" in reply:
                    if tolerate:
                        return {}
                    raise StealthError(f"CDP {method} rejected: {reply['error']}")
                result = reply.get("result")
                return result if isinstance(result, dict) else {}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if tolerate:
                    return {}
                raise StealthError(f"CDP {method} timed out waiting for a reply.")
            self._read(remaining)

    def fire(self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None) -> None:
        """Send a command and do not wait for (or keep) its reply."""
        self._next_id += 1
        envelope: dict[str, Any] = {"id": self._next_id, "method": method, "params": params or {}}
        if session_id is not None:
            envelope["sessionId"] = session_id
        self._fired.add(self._next_id)
        try:
            self._ws.send(json.dumps(envelope))
        except Exception as exc:
            self.closed = True
            raise StealthError(f"CDP {method} send failed: {exc}") from exc

    def next_event(self, timeout: float) -> dict[str, Any] | None:
        if self.events:
            return self.events.pop(0)
        self._read(timeout)
        return self.events.pop(0) if self.events else None

    def close(self) -> None:
        self.closed = True
        try:
            self._ws.close()
        except Exception:
            pass


# ------------------------------------------------------------------ daemon

class StealthDaemon:
    """One per running profile: patches every target and manages the session."""

    def __init__(
        self,
        browser_ws_url: str | None,
        spec: StealthSpec,
        *,
        profile_path: Path | None = None,
        start_urls: list[str] | None = None,
        restore_session: bool = True,
        quit_when_last_tab_closes: bool = True,
        connect_timeout: float = _DISCOVERY_TIMEOUT,
    ) -> None:
        self._ws_url = browser_ws_url
        self._spec = spec
        self._profile_path = Path(profile_path) if profile_path else None
        self._start_urls = list(start_urls or [])
        self._restore = restore_session
        self._quit_on_last = quit_when_last_tab_closes
        self._connect_timeout = connect_timeout
        self._stop = threading.Event()
        self._close_browser = threading.Event()
        self._open_requests: list[str] = []
        self._open_lock = threading.Lock()
        self.ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"stealth-{id(self):x}", daemon=True
        )
        self._started = False
        self._closed = False
        self._conn: _CdpConnection | None = None
        # Observability (also used by tests).
        self.patched_targets: list[str] = []
        self.patched_workers: list[str] = []
        self.last_error: str | None = None
        self._pages: dict[str, str] = {}          # top-level page targetId -> url
        self._deferred: dict[str, str] = {}       # targetId of a blank tab -> url to load once it is patched
        self._seen_page = False
        self._empty_since: float | None = None
        self._fitted_windows: set[int] = set()
        self._session_dirty = False
        self._session_frozen = False
        self._last_session_write = 0.0
        self._payload = build_payload(spec)
        self._trace_path = os.environ.get("ANTIDETECT_STEALTH_TRACE")

    # ------------------------------------------------------------- lifecycle

    def start(self) -> "StealthDaemon":
        self._thread.start()
        self._started = True
        return self

    def wait_ready(self, timeout: float = 25.0) -> None:
        """Block until the first tab is open and patched; raise on failure."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ready.wait(0.1):
                return
            if self.last_error and not self._thread.is_alive():
                break
        raise StealthError(self.last_error or "Stealth layer did not become ready in time.")

    def request_open(self, url: str) -> None:
        """Open ``url`` in a new (patched) tab of this browser; safe from any thread."""
        with self._open_lock:
            self._open_requests.append(str(url))

    def request_close(self) -> None:
        """Ask the browser to quit gracefully (Browser.close: ~0.1s vs SIGTERM ~5s)."""
        self.freeze()
        self._close_browser.set()

    def freeze(self) -> None:
        """Snapshot the open tabs and stop tracking (shutdown is about to start)."""
        self._write_session()
        self._session_frozen = True

    def close(self) -> None:
        self._stop.set()
        if self._started:
            self._thread.join(timeout=5.0)
            self._started = False
        if self._conn is not None:
            self._conn.close()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def running(self) -> bool:
        return self._started and self._thread.is_alive()

    def _trace(self, message: str) -> None:
        if not self._trace_path:
            return
        try:
            with open(self._trace_path, "a", encoding="utf-8") as handle:
                handle.write(f"{time.monotonic():.2f} {message}\n")
        except OSError:
            pass

    # ----------------------------------------------------------------- loop

    def _run(self) -> None:
        try:
            self._serve()
        except Exception as exc:  # never die silently; record and park
            self.last_error = f"daemon: {exc}"
            self._trace(f"fatal {exc}")
        finally:
            if self._conn is not None:
                self._conn.close()

    def _serve(self) -> None:
        ws_url = self._ws_url
        if ws_url is None and self._profile_path is not None:
            ws_url = discover_browser_endpoint(self._profile_path, self._connect_timeout)
        if ws_url is None:
            raise StealthError("No DevTools endpoint to attach to.")
        self._conn = conn = _CdpConnection(ws_url)
        conn.call("Target.setDiscoverTargets", {"discover": True})
        conn.call("Target.setAutoAttach", dict(_AUTO_ATTACH))
        self._open_initial_tabs(conn)
        while not self._stop.is_set():
            if self._close_browser.is_set():
                try:
                    conn.call("Browser.close", {}, timeout=3.0, tolerate=True)
                except StealthError:
                    pass
                return
            self._drain_open_requests(conn)
            event = conn.next_event(0.2)
            if event is not None:
                try:
                    self._handle(conn, event)
                except StealthError as exc:
                    self.last_error = str(exc)
                    self._trace(f"event error {exc}")
            self._tick(conn)
            if conn.closed:
                return

    def _drain_open_requests(self, conn: _CdpConnection) -> None:
        with self._open_lock:
            pending, self._open_requests = self._open_requests, []
        for url in pending:
            reply = self._create_tab(conn, url, new_window=False, tolerate=True)
            if reply.get("targetId"):
                conn.call("Target.activateTarget", {"targetId": reply["targetId"]}, tolerate=True)

    def _create_tab(self, conn: _CdpConnection, url: str, *, new_window: bool, tolerate: bool) -> dict[str, Any]:
        """Create a tab. A website is loaded *after* the tab is patched, never with it.

        A tab created with a URL starts its first request immediately — before DevTools
        can attach — so that request would carry the real machine in Sec-CH-UA-Platform
        (and friends) and the site would see e.g. macOS for a Windows profile. The tab is
        therefore created blank; ``_on_attached`` navigates it once the overrides are set.
        """
        params: dict[str, Any] = {"url": url, "newWindow": new_window}
        deferred = url.lower().startswith(("http://", "https://"))
        if deferred:
            params["url"] = "about:blank"
        reply = conn.call("Target.createTarget", params, tolerate=tolerate)
        target_id = reply.get("targetId")
        if deferred and target_id:
            # The attach event is queued behind this reply, so the entry is always in place first.
            self._deferred[str(target_id)] = url
        return reply

    def _tick(self, conn: _CdpConnection) -> None:
        now = time.monotonic()
        if self._session_dirty and now - self._last_session_write > 1.0:
            self._write_session()
        if self._quit_on_last and self._seen_page and not self._pages:
            if self._empty_since is None:
                self._empty_since = now
            elif now - self._empty_since > 2.0:
                self._trace("last tab closed -> Browser.close")
                self._write_session()
                try:
                    conn.call("Browser.close", {}, timeout=3.0, tolerate=True)
                except StealthError:
                    pass
                self._stop.set()
        else:
            self._empty_since = None

    # --------------------------------------------------------------- events

    def _handle(self, conn: _CdpConnection, event: dict[str, Any]) -> None:
        method = event.get("method")
        params = event.get("params") or {}
        if method == "Target.attachedToTarget":
            self._on_attached(conn, params)
        elif method in ("Target.targetCreated", "Target.targetInfoChanged"):
            self._track(params.get("targetInfo") or {})
        elif method == "Target.targetDestroyed":
            target_id = str(params.get("targetId") or "")
            if self._pages.pop(target_id, None) is not None:
                self._session_dirty = True

    def _track(self, info: dict[str, Any]) -> None:
        if info.get("type") != "page" or not info.get("targetId"):
            return
        url = str(info.get("url") or "")
        if url.startswith("devtools://"):
            return
        target_id = str(info["targetId"])
        if self._pages.get(target_id) != url:
            self._pages[target_id] = url
            self._seen_page = True
            self._empty_since = None
            self._session_dirty = True

    def _on_attached(self, conn: _CdpConnection, params: dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        info = params.get("targetInfo") or {}
        if not session_id:
            return
        target_type = info.get("type")
        target_id = str(info.get("targetId") or "")
        url = str(info.get("url") or "")
        waiting = bool(params.get("waitingForDebugger"))
        self._trace(f"attached {target_type} {target_id[:8]} waiting={waiting} url={url[:60]}")
        try:
            if target_type in ("page", "iframe"):
                # A *tab* is patched even while it shows an internal page (NTP,
                # settings): typing an address into it navigates the same target in
                # place, and an unpatched target would show the real machine.
                # The payload skips privileged documents itself. Only nested
                # internal iframes (chrome-untrusted:// inside the NTP) are left alone.
                if target_type == "page" or not url.startswith(_INTERNAL_URL_PREFIXES):
                    self._patch_page(conn, session_id, info)
                if target_type == "page":
                    self._track(info)
                    self._fit_window(conn, target_id)
            elif target_type in ("worker", "shared_worker"):
                if not url.startswith(_INTERNAL_URL_PREFIXES):
                    self._patch_worker(conn, session_id, target_id)
            elif target_type == "service_worker":
                # A paused service worker never answers Runtime.evaluate, so it
                # is resumed first and patched immediately after: its top-level
                # script only registers listeners, which run later.
                if waiting:
                    conn.call(
                        "Runtime.runIfWaitingForDebugger", {}, session_id,
                        timeout=_WORKER_TIMEOUT, tolerate=True,
                    )
                    waiting = False
                if not url.startswith(_INTERNAL_URL_PREFIXES):
                    self._patch_worker(conn, session_id, target_id)
        except StealthError as exc:
            self.last_error = f"patch {target_type} {target_id[:8]}: {exc}"
            self._trace(self.last_error)
        finally:
            if waiting:
                try:
                    conn.call(
                        "Runtime.runIfWaitingForDebugger", {}, session_id,
                        timeout=_WORKER_TIMEOUT, tolerate=True,
                    )
                except StealthError:
                    pass
            if target_type == "page":
                self.ready.set()
        wanted = self._deferred.pop(target_id, None)
        if wanted is not None and target_type == "page":
            # Patched and resumed: now (and only now) the site may be asked for anything.
            # Fire-and-forget: a slow server must not stall the patching of other tabs.
            conn.fire("Page.navigate", {"url": wanted}, session_id)
            self._trace(f"navigate {target_id[:8]} -> {wanted[:60]}")

    # -------------------------------------------------------------- patching

    def _patch_page(self, conn: _CdpConnection, sid: str, info: dict[str, Any]) -> None:
        spec = self._spec
        if spec.user_agent:
            params: dict[str, Any] = {"userAgent": spec.user_agent}
            if spec.accept_language:
                params["acceptLanguage"] = spec.accept_language
            if spec.nav_platform:
                params["platform"] = spec.nav_platform
            if spec.ua_metadata:
                params["userAgentMetadata"] = spec.ua_metadata
            conn.call("Emulation.setUserAgentOverride", params, sid)
        if spec.locale:
            # "Another locale override is already in effect": the override is
            # shared by the renderer process, so a repeat is a harmless no-op.
            conn.call("Emulation.setLocaleOverride", {"locale": spec.locale}, sid, tolerate=True)
        if spec.timezone_id:
            conn.call("Emulation.setTimezoneOverride", {"timezoneId": spec.timezone_id}, sid, tolerate=True)
        if spec.cores:
            conn.call(
                "Emulation.setHardwareConcurrencyOverride",
                {"hardwareConcurrency": int(spec.cores)},
                sid,
                tolerate=True,
            )
        is_page = info.get("type") == "page"
        if spec.screen is not None and is_page:
            # Page level only: child frames inherit the widget's screen info.
            conn.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 0,
                    "height": 0,
                    "deviceScaleFactor": float(spec.screen.dpr),
                    "mobile": False,
                    "screenWidth": int(spec.screen.width),
                    "screenHeight": int(spec.screen.height),
                    "positionX": 0,
                    "positionY": 0,
                    "dontSetVisibleSize": True,
                },
                sid,
                tolerate=True,
            )
        if spec.geolocation is not None and is_page:
            conn.call(
                "Emulation.setGeolocationOverride",
                {"latitude": spec.geolocation[0], "longitude": spec.geolocation[1], "accuracy": 35.0},
                sid,
                tolerate=True,
            )
        if spec.color_scheme and is_page:
            # prefers-color-scheme without a JS trace: the page (and its frames) simply answer it.
            conn.call(
                "Emulation.setEmulatedMedia",
                {"features": [{"name": "prefers-color-scheme", "value": spec.color_scheme}]},
                sid,
                tolerate=True,
            )
        # The Page domain must be enabled or the new-document scripts are not
        # evaluated in dynamically created child frames.
        conn.call("Page.enable", {}, sid, tolerate=True)
        conn.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": self._payload, "runImmediately": True},
            sid,
        )
        # Catch this page's iframes and dedicated workers (paused at start too).
        conn.call("Target.setAutoAttach", dict(_AUTO_ATTACH), sid, tolerate=True)
        self.patched_targets.append(str(info.get("targetId") or sid))
        self._trace(f"patched {info.get('type')} {str(info.get('targetId') or '')[:8]}")

    def _patch_worker(self, conn: _CdpConnection, sid: str, target_id: str) -> None:
        conn.call(
            "Runtime.evaluate",
            {"expression": self._payload, "silent": True, "returnByValue": True},
            sid,
            timeout=_WORKER_TIMEOUT,
        )
        self.patched_workers.append(target_id)
        self._trace(f"patched worker {target_id[:8]}")

    # -------------------------------------------------------------- windows

    def _fit_window(self, conn: _CdpConnection, target_id: str) -> None:
        """Keep the real window inside the claimed screen (outer <= screen)."""
        screen = self._spec.screen
        if screen is None or not target_id:
            return
        reply = conn.call("Browser.getWindowForTarget", {"targetId": target_id}, tolerate=True)
        window_id = reply.get("windowId")
        bounds = reply.get("bounds") or {}
        if window_id is None or window_id in self._fitted_windows:
            return
        self._fitted_windows.add(window_id)
        width, height = bounds.get("width"), bounds.get("height")
        if not width or not height:
            return
        new_w = min(int(width), int(screen.avail_width))
        new_h = min(int(height), int(screen.avail_height))
        if (new_w, new_h) != (int(width), int(height)):
            conn.call(
                "Browser.setWindowBounds",
                {
                    "windowId": window_id,
                    "bounds": {
                        "windowState": "normal",
                        "left": int(bounds.get("left") or 0),
                        "top": max(int(bounds.get("top") or 0), int(screen.avail_top)),
                        "width": new_w,
                        "height": new_h,
                    },
                },
                tolerate=True,
            )

    # -------------------------------------------------------- session & tabs

    def _open_initial_tabs(self, conn: _CdpConnection) -> None:
        urls = list(self._start_urls)
        if self._restore:
            urls += [url for url in self._read_session() if url not in urls]
        if not urls:
            urls = [_NEW_TAB_URL]
        first = True
        for url in urls[:_MAX_RESTORED_TABS]:
            reply = self._create_tab(conn, url, new_window=first, tolerate=not first)
            if first and reply.get("targetId"):
                conn.call("Target.activateTarget", {"targetId": reply["targetId"]}, tolerate=True)
            first = False

    def _session_path(self) -> Path | None:
        return self._profile_path / _SESSION_FILE if self._profile_path else None

    def _read_session(self) -> list[str]:
        path = self._session_path()
        if path is None:
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        urls = data.get("urls") if isinstance(data, dict) else None
        if not isinstance(urls, list):
            return []
        return [
            str(url)
            for url in urls
            if isinstance(url, str)
            and url not in _RESTORE_SKIP
            and not url.startswith(("devtools://", "chrome-extension://", "chrome-error://"))
        ]

    def _write_session(self) -> None:
        if self._session_frozen:
            return
        self._session_dirty = False
        self._last_session_write = time.monotonic()
        path = self._session_path()
        if path is None or not self._pages:
            return  # keep the last non-empty session when everything closes
        urls = [u for u in self._pages.values() if u not in _RESTORE_SKIP]
        try:
            path.write_text(json.dumps({"urls": urls}), encoding="utf-8")
        except OSError:
            pass


# --------------------------------------------------------------- entry point

def start_daemon(
    profile_path: Path,
    spec: StealthSpec,
    *,
    start_urls: list[str] | None = None,
    restore_session: bool = True,
    quit_when_last_tab_closes: bool = True,
    connect_timeout: float = _DISCOVERY_TIMEOUT,
) -> StealthDaemon:
    """Attach to a freshly launched browser and open its first (patched) tab."""
    endpoint = discover_browser_endpoint(Path(profile_path), timeout=connect_timeout)
    return StealthDaemon(
        endpoint,
        spec,
        profile_path=Path(profile_path),
        start_urls=start_urls,
        restore_session=restore_session,
        quit_when_last_tab_closes=quit_when_last_tab_closes,
    ).start()
