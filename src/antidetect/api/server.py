"""The local HTTP server: JSON over loopback, one thread per request, standard library only.

Three things keep it from being a way into your machine for a web page you happen to have open:

* it listens on ``127.0.0.1`` and nowhere else;
* every request needs the token (``Authorization: Bearer <token>``). A page in your browser can
  neither read it nor send that header, because no CORS headers are ever answered;
* a request that carries an ``Origin`` header (what browsers add to cross-site calls) or a
  ``Host`` that is not loopback (DNS rebinding) is refused outright.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from antidetect.api.service import ApiError, ApiService, translate
from antidetect.api.settings import HOST, ApiKey

MAX_BODY = 8 * 1024 * 1024
_LOOPBACK = ("127.0.0.1", "localhost", "[::1]")
_MUTATING = ("POST", "PATCH", "PUT", "DELETE")

_Handler = Callable[[ApiService, "re.Match[str]", dict, Any], Any]


@dataclass(frozen=True)
class _Route:
    method: str
    pattern: "re.Pattern[str]"
    handler: _Handler
    public: bool = False          # answered without a token (only the liveness probe)
    status: int = 200


def _route(method: str, pattern: str, handler: _Handler, *, public: bool = False, status: int = 200) -> _Route:
    return _Route(method, re.compile(pattern + r"/?$"), handler, public, status)


_ROUTES = [
    _route("GET", r"/v1/health", lambda s, m, q, b: s.health(), public=True),
    _route("GET", r"/v1/status", lambda s, m, q, b: s.status()),
    _route("GET", r"/v1/profiles", lambda s, m, q, b: s.list_profiles(q)),
    _route("POST", r"/v1/profiles", lambda s, m, q, b: s.create_profile(b), status=201),
    _route("GET", r"/v1/profiles/(\d+)", lambda s, m, q, b: s.get_profile(int(m[1]))),
    _route("PATCH", r"/v1/profiles/(\d+)", lambda s, m, q, b: s.update_profile(int(m[1]), b)),
    _route("DELETE", r"/v1/profiles/(\d+)", lambda s, m, q, b: s.delete_profile(int(m[1]), q)),
    _route("POST", r"/v1/profiles/(\d+)/start", lambda s, m, q, b: s.start_profile(int(m[1]))),
    _route("POST", r"/v1/profiles/(\d+)/stop", lambda s, m, q, b: s.stop_profile(int(m[1]))),
    _route("GET", r"/v1/profiles/(\d+)/connection", lambda s, m, q, b: s.get_connection(int(m[1]))),
    _route("POST", r"/v1/profiles/(\d+)/open", lambda s, m, q, b: s.open_url(int(m[1]), b)),
    _route("GET", r"/v1/profiles/(\d+)/cookies", lambda s, m, q, b: s.get_cookies(int(m[1]))),
    _route("POST", r"/v1/profiles/(\d+)/cookies", lambda s, m, q, b: s.set_cookies(int(m[1]), b)),
    _route("DELETE", r"/v1/profiles/(\d+)/cookies", lambda s, m, q, b: s.clear_cookies(int(m[1]))),
    _route("GET", r"/v1/proxies", lambda s, m, q, b: s.list_proxies(q)),
    _route("POST", r"/v1/proxies", lambda s, m, q, b: s.add_proxies(b)),
    _route("POST", r"/v1/proxies/(\d+)/check", lambda s, m, q, b: s.check_proxy(int(m[1]))),
    _route("DELETE", r"/v1/proxies/(\d+)", lambda s, m, q, b: s.delete_proxy(int(m[1]))),
]


class _Server(ThreadingHTTPServer):
    daemon_threads = True                 # a hung client must never keep the app from quitting
    # On Windows SO_REUSEADDR lets a second program bind a port that is already taken.
    allow_reuse_address = sys.platform != "win32"
    request_queue_size = 64


class ApiServer:
    """Starts and stops the listener; binding errors (``OSError``) surface from :meth:`start`."""

    def __init__(
        self,
        service: ApiService,
        authenticate: Callable[[str], ApiKey | None],
        port: int,
        *,
        log: Any = None,
        on_use: Callable[[ApiKey], None] | None = None,
    ) -> None:
        self._service = service
        self._authenticate = authenticate        # token -> the key it belongs to, or None
        self._on_use = on_use                    # told about every authenticated request
        self._wanted_port = port
        self._log = log
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd is not None else self._wanted_port

    def start(self) -> None:
        if self._httpd is not None:
            return
        httpd = _Server((HOST, self._wanted_port), self._handler_class())
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="antidetect-api", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        httpd, thread = self._httpd, self._thread
        self._httpd = self._thread = None
        if httpd is None:
            return
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=3.0)

    # ---------------------------------------------------------------- handler
    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 60                                  # an idle keep-alive connection is dropped

            def version_string(self) -> str:
                return "Antidetect"

            def log_message(self, *args) -> None:        # the app log below says what matters
                pass

            def do_GET(self) -> None: server._handle(self, "GET")                   # noqa: E704
            def do_POST(self) -> None: server._handle(self, "POST")                 # noqa: E704
            def do_PATCH(self) -> None: server._handle(self, "PATCH")               # noqa: E704
            def do_PUT(self) -> None: server._handle(self, "PUT")                   # noqa: E704
            def do_DELETE(self) -> None: server._handle(self, "DELETE")             # noqa: E704
            def do_OPTIONS(self) -> None: server._handle(self, "OPTIONS")           # noqa: E704
            def do_HEAD(self) -> None: server._handle(self, "HEAD")                 # noqa: E704

        return Handler

    def _handle(self, request: BaseHTTPRequestHandler, method: str) -> None:
        started = time.monotonic()
        parts = urlsplit(request.path)
        status, payload, headers = 500, {}, {}
        try:
            try:
                self._guard(request)
                status, payload = self._dispatch(request, method, parts)
            except ApiError as exc:
                status, payload, headers = exc.status, {"error": {"code": exc.code, "message": exc.message}}, exc.headers
            except Exception as exc:                      # a domain error, or a bug
                known = translate(exc)
                if known is None:
                    self._write_log("error", f"{method} {parts.path} crashed: {type(exc).__name__}: {exc}")
                    status, payload = 500, {"error": {"code": "internal_error", "message": "Internal error; see the Log page."}}
                else:
                    status, payload = known.status, {"error": {"code": known.code, "message": known.message}}
            self._send(request, method, status, payload, headers)
        except (BrokenPipeError, ConnectionError, TimeoutError):
            return
        if method in _MUTATING and not parts.path.endswith("/health"):
            elapsed = time.monotonic() - started
            level = "info" if status < 400 else "warn"
            detail = f" — {payload['error']['code']}" if status >= 400 and isinstance(payload, dict) and "error" in payload else ""
            key = getattr(request, "api_key", None)
            who = f" [{key.name}]" if key is not None else ""
            self._write_log(level, f"API{who} {method} {parts.path} → {status} ({elapsed:.1f}s){detail}")

    def _write_log(self, level: str, message: str) -> None:
        sink = getattr(self._log, level, None)
        if sink is not None:
            try:
                sink("api", message)
            except Exception:
                pass

    def _guard(self, request: BaseHTTPRequestHandler) -> None:
        """Refuse what cannot be a script on this machine: foreign hosts and browser cross-site calls."""
        host = (request.headers.get("Host") or "").strip().lower()
        if host not in {f"{name}:{self.port}" for name in _LOOPBACK}:
            raise ApiError(403, "forbidden_host", "Requests must go to 127.0.0.1.")
        if request.headers.get("Origin") is not None:
            raise ApiError(403, "forbidden_origin", "Browser cross-site requests are not accepted.")

    def _authorized(self, request: BaseHTTPRequestHandler) -> bool:
        header = request.headers.get("Authorization") or ""
        given = header[7:].strip() if header[:7].lower() == "bearer " else (request.headers.get("X-API-Key") or "").strip()
        key = self._authenticate(given) if given else None
        if key is None:
            return False
        request.api_key = key
        if self._on_use is not None:
            try:
                self._on_use(key)
            except Exception:
                pass
        return True

    def _dispatch(self, request: BaseHTTPRequestHandler, method: str, parts) -> tuple[int, Any]:
        found = [(route, route.pattern.match(parts.path)) for route in _ROUTES]
        found = [(route, match) for route, match in found if match is not None]
        if not (found and all(route.public for route, _ in found)) and not self._authorized(request):
            raise ApiError(401, "unauthorized", "Send the API token as 'Authorization: Bearer <token>'.")
        if not found:
            raise ApiError(404, "not_found", f"No such endpoint: {parts.path}")
        chosen = next(((route, match) for route, match in found if route.method == method), None)
        if chosen is None:
            allowed = ", ".join(sorted({route.method for route, _ in found}))
            raise ApiError(405, "method_not_allowed", f"Method {method} is not allowed here. Allowed: {allowed}.",
                           headers={"Allow": allowed})
        route, match = chosen
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        body = self._read_body(request) if method in ("POST", "PATCH", "PUT") else None
        return route.status, route.handler(self._service, match, query, body)

    @staticmethod
    def _read_body(request: BaseHTTPRequestHandler) -> Any:
        try:
            length = int(request.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad_request", "Bad Content-Length.") from None
        if length > MAX_BODY:
            raise ApiError(413, "too_large", f"The request body is limited to {MAX_BODY // (1024 * 1024)} MB.")
        raw = request.rfile.read(length) if length > 0 else b""
        request.body_consumed = True
        if not raw.strip():
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "bad_json", "The request body is not valid JSON.") from None

    @staticmethod
    def _send(request: BaseHTTPRequestHandler, method: str, status: int, payload: Any, headers: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(headers)
        declared = (request.headers.get("Content-Length") or "").strip()
        if declared.isdigit() and int(declared) > 0 and not getattr(request, "body_consumed", False):
            # Refused before the body was read: the bytes still on the wire would corrupt the next request.
            headers["Connection"] = "close"
            request.close_connection = True
        request.send_response(status)
        request.send_header("Content-Type", "application/json; charset=utf-8")
        request.send_header("Content-Length", str(len(data)))
        request.send_header("Cache-Control", "no-store")
        request.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers.items():
            request.send_header(key, value)
        request.end_headers()
        if method != "HEAD":
            request.wfile.write(data)
