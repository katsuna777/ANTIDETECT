"""What the API does, free of HTTP: one method per endpoint, plain dicts in and out.

Everything goes through the same services the GUI and the command line use, so a profile made
by a script is exactly a profile made by hand. Failures are raised as :class:`ApiError` with an
HTTP status and a stable machine-readable ``code``.
"""

from __future__ import annotations

import threading
from datetime import timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import quote

from antidetect import __version__
from antidetect.application.fingerprint import privacy
from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.errors import (
    AntiDetectError,
    BrowserConfigurationNotFoundError,
    ChromiumError,
    ChromiumNotFoundError,
    CookieError,
    CookieFileNotFoundError,
    ProfileAlreadyExistsError,
    ProfileAlreadyRunningError,
    ProfileConfigurationMissingError,
    ProfileNotFoundError,
    ProfileNotRunningError,
    ProxyNotFoundError,
    ProxyNotUsableError,
    StealthError,
)
from antidetect.infrastructure.stealth.cdp import cdp_call, read_devtools_endpoint

if TYPE_CHECKING:
    from antidetect.container import Container

MAX_NAME = 200
MAX_TAGS = 50
MAX_TAG = 50
MAX_COOKIES = 20000
DEFAULT_LIMIT = 500
MAX_LIMIT = 5000

#: First match wins, so a subclass has to come before its base.
_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (ProfileNotFoundError, 404, "profile_not_found"),
    (ProxyNotFoundError, 404, "proxy_not_found"),
    (BrowserConfigurationNotFoundError, 404, "configuration_not_found"),
    (ProfileAlreadyExistsError, 409, "profile_exists"),
    (ProfileAlreadyRunningError, 409, "already_running"),
    (ProfileNotRunningError, 409, "not_running"),
    (ProfileConfigurationMissingError, 409, "configuration_missing"),
    (ProxyNotUsableError, 422, "proxy_unusable"),
    (CookieFileNotFoundError, 404, "no_cookies"),
    (CookieError, 409, "cookie_error"),
    (ChromiumNotFoundError, 503, "browser_not_found"),
    (StealthError, 500, "stealth_failed"),
    (ChromiumError, 500, "browser_error"),
    (AntiDetectError, 400, "error"),
    (ValueError, 400, "bad_request"),
)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def translate(exc: Exception) -> ApiError | None:
    """The :class:`ApiError` a domain exception stands for (``None`` = unexpected, a bug)."""
    if isinstance(exc, ApiError):
        return exc
    for kind, status, code in _ERRORS:
        if isinstance(exc, kind):
            return ApiError(status, code, str(exc))
    return None


# --------------------------------------------------------------- body helpers


def _obj(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "The request body must be a JSON object.")
    return body


def _text(body: dict, key: str, *, required: bool = False, limit: int | None = None) -> str | None:
    if key not in body or body[key] is None:
        if required:
            raise ApiError(400, "bad_request", f"'{key}' is required.")
        return None
    value = body[key]
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", f"'{key}' must be a string.")
    value = value.strip() if key == "name" else value
    if required and not value.strip():
        raise ApiError(400, "bad_request", f"'{key}' must not be empty.")
    if limit is not None and len(value) > limit:
        raise ApiError(400, "bad_request", f"'{key}' is too long (at most {limit} characters).")
    return value


def _flag(body: dict, key: str, default: bool | None = None) -> bool | None:
    if key not in body:
        return default
    value = body[key]
    if isinstance(value, bool):
        return value
    raise ApiError(400, "bad_request", f"'{key}' must be true or false.")


def _privacy(body: dict) -> dict | None:
    """The protection switches present in a request body (``None`` when it has none)."""
    given: dict = {}
    if "webrtc" in body:
        value = body["webrtc"]
        if value not in privacy.WEBRTC_MODES:
            raise ApiError(400, "bad_request", f"'webrtc' must be one of: {', '.join(privacy.WEBRTC_MODES)}.")
        given["webrtc"] = value
    if "theme" in body:
        if body["theme"] not in privacy.THEMES:
            raise ApiError(400, "bad_request", f"'theme' must be one of: {', '.join(privacy.THEMES)}.")
        given["theme"] = body["theme"]
    for key in ("noise_canvas", "noise_audio"):
        if key in body:
            given[key] = _flag(body, key)
    return given or None


def _tags(body: dict) -> list[str] | None:
    if "tags" not in body or body["tags"] is None:
        return None
    raw = body["tags"]
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raise ApiError(400, "bad_request", "'tags' must be a list of strings.")
    tags = list(dict.fromkeys(t.strip() for t in raw if t.strip()))
    if len(tags) > MAX_TAGS or any(len(t) > MAX_TAG for t in tags):
        raise ApiError(400, "bad_request", f"At most {MAX_TAGS} tags of {MAX_TAG} characters each.")
    return tags


def _workspace(body: dict) -> tuple[bool, str | None]:
    """(given, name): ``null`` or ``""`` means "no workspace"; a name that does not exist yet is created."""
    if "workspace" not in body:
        return False, None
    value = body["workspace"]
    if value is None:
        return True, None
    if not isinstance(value, str):
        raise ApiError(400, "bad_request", "'workspace' must be a name or null.")
    value = " ".join(value.split())
    if len(value) > MAX_TAG:
        raise ApiError(400, "bad_request", f"'workspace' is too long (at most {MAX_TAG} characters).")
    return True, value or None


def _http_url(value: Any) -> str:
    if not isinstance(value, str) or not value.lower().startswith(("http://", "https://")):
        raise ApiError(400, "bad_request", "'url' must start with http:// or https://.")
    return value.strip()


def _iso(moment) -> str | None:
    """ISO 8601 in UTC with a trailing Z (the database keeps UTC without a zone)."""
    if moment is None:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.isoformat(timespec="seconds") + "Z"


# ------------------------------------------------------------------- cookies

_COOKIE_KEYS = (
    "name", "value", "url", "domain", "path", "secure", "httpOnly", "sameSite",
    "expires", "priority", "sameParty", "sourceScheme", "sourcePort", "partitionKey",
)
_SAME_SITE = {"strict": "Strict", "lax": "Lax", "none": "None", "no_restriction": "None"}


def clean_cookies(raw: Any) -> list[dict]:
    """Cookies as Chrome wants them. Also reads the exports of common cookie-editor extensions."""
    if isinstance(raw, dict):
        raw = raw.get("cookies")
    if not isinstance(raw, list):
        raise ApiError(400, "bad_request", "Send a list of cookies, or {\"cookies\": [...]}.")
    if len(raw) > MAX_COOKIES:
        raise ApiError(400, "bad_request", f"At most {MAX_COOKIES} cookies at a time.")
    cookies: list[dict] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ApiError(400, "bad_request", f"Cookie #{index} is not an object.")
        cookie = {key: item[key] for key in _COOKIE_KEYS if key in item and item[key] is not None}
        if "expires" not in cookie and isinstance(item.get("expirationDate"), (int, float)):
            cookie["expires"] = item["expirationDate"]          # Cookie-Editor / EditThisCookie
        if not isinstance(cookie.get("expires"), (int, float)) or cookie["expires"] <= 0:
            cookie.pop("expires", None)                          # a session cookie
        if "sameSite" in cookie:
            mapped = _SAME_SITE.get(str(cookie["sameSite"]).lower())
            if mapped is None:
                cookie.pop("sameSite")                           # "unspecified"
            else:
                cookie["sameSite"] = mapped
        if not isinstance(cookie.get("name"), str) or not isinstance(cookie.get("value"), str):
            raise ApiError(400, "bad_request", f"Cookie #{index} needs a string 'name' and 'value'.")
        if not cookie.get("domain") and not cookie.get("url"):
            raise ApiError(400, "bad_request", f"Cookie #{index} ('{cookie['name']}') needs a 'domain' or a 'url'.")
        cookies.append(cookie)
    return cookies


# --------------------------------------------------------------------- service


class ApiService:
    def __init__(self, container: "Container", on_change: Callable[[], None] | None = None) -> None:
        self._c = container
        self._on_change = on_change
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ plumbing
    def _changed(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass

    def _lock(self, profile_id: int) -> threading.Lock:
        """One at a time per profile: two scripts starting the same profile cannot launch it twice."""
        with self._guard:
            return self._locks.setdefault(profile_id, threading.Lock())

    # ------------------------------------------------------------------- views
    @staticmethod
    def connection_of(profile) -> dict | None:
        if profile.status.value != "RUNNING":
            return None
        found = read_devtools_endpoint(Path(profile.profile_path))
        if found is None:
            return None
        port, path = found
        return {
            "ws": f"ws://127.0.0.1:{port}{path}",
            "http": f"http://127.0.0.1:{port}",
            "port": port,
            "debugger_address": f"127.0.0.1:{port}",
            "pid": profile.pid,
        }

    @staticmethod
    def proxy_view(row) -> dict:
        proxy = row.proxy
        return {
            "id": proxy.id,
            "type": proxy.protocol.value.lower(),
            "host": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "has_password": bool(proxy.password),
            "country": row.country or proxy.country,
            "country_code": row.country_code or proxy.country_code,
            "status": proxy.status.value.lower(),
            "latency_ms": row.latency_ms,
            "ip": row.external_ip,
            "source": proxy.source,
            "checked_at": _iso(row.checked_at or proxy.last_checked_at),
        }

    def _workspace_names(self) -> dict[int, str]:
        return {info.workspace.id: info.workspace.name for info in self._c.workspaces.list_workspaces()}

    def _workspace_id(self, name: str | None) -> int | None:
        """The id of the workspace called ``name``, which is created when it does not exist yet."""
        if not name:
            return None
        workspace = self._c.workspaces.find(name) or self._c.workspaces.create_workspace(name)
        return workspace.id

    def _profile_view(self, profile, configuration, proxy_row, workspaces: dict[int, str] | None = None) -> dict:
        hardware = (configuration.hardware_settings or {}) if configuration is not None else {}
        screen = (
            f"{configuration.screen_width}x{configuration.screen_height}"
            if configuration is not None and configuration.screen_width and configuration.screen_height
            else None
        )
        switches = privacy.resolve(configuration.privacy_settings if configuration is not None else None)
        return {
            "id": profile.id,
            "name": profile.name,
            "status": "running" if profile.status.value == "RUNNING" else "stopped",
            "tags": list(profile.tags),
            "workspace": (workspaces if workspaces is not None else self._workspace_names()).get(profile.workspace_id),
            "notes": profile.notes,
            "start_url": profile.start_url,
            "geo_auto": profile.geo_auto,
            "webrtc": switches["webrtc"],
            "noise_canvas": switches["noise_canvas"],
            "noise_audio": switches["noise_audio"],
            "theme": switches["theme"],
            "platform": configuration.platform if configuration is not None else None,
            "user_agent": configuration.user_agent if configuration is not None else None,
            "language": configuration.language if configuration is not None else None,
            "locale": configuration.locale if configuration is not None else None,
            "timezone": configuration.timezone if configuration is not None else None,
            "screen": screen,
            "cores": hardware.get("cores"),
            "memory_gb": hardware.get("memory_gb"),
            "proxy": self.proxy_view(proxy_row) if proxy_row is not None else None,
            "connection": self.connection_of(profile),
            "created_at": _iso(profile.created_at),
            "last_started_at": _iso(profile.last_started_at),
            "last_stopped_at": _iso(profile.last_stopped_at),
        }

    def _view(self, profile_id: int) -> dict:
        details = self._c.profiles.get_profile_details(profile_id)
        return self._profile_view(details.profile, details.configuration, details.proxy_check)

    # ------------------------------------------------------------------ status
    def health(self) -> dict:
        return {"ok": True, "app": "antidetect"}

    def status(self) -> dict:
        profiles = self._c.profiles.list_profiles()
        path, version = self._c.browser_info()
        return {
            "ok": True,
            "version": __version__,
            "profiles": len(profiles),
            "running": sum(1 for p in profiles if p.status.value == "RUNNING"),
            "browser": {"path": str(path) if path is not None else None, "version": version},
        }

    # ---------------------------------------------------------------- profiles
    def list_profiles(self, query: dict) -> dict:
        profiles = self._c.profiles.list_profiles()
        tag = (query.get("tag") or "").strip().casefold()
        status = (query.get("status") or "").strip().lower()
        text = (query.get("q") or "").strip().casefold()
        workspace = " ".join((query.get("workspace") or "").split())
        if status and status not in ("running", "stopped"):
            raise ApiError(400, "bad_request", "'status' must be 'running' or 'stopped'.")
        if tag:
            profiles = [p for p in profiles if any(t.casefold() == tag for t in p.tags)]
        if status:
            profiles = [p for p in profiles if (p.status.value == "RUNNING") == (status == "running")]
        if text:
            profiles = [p for p in profiles if text in p.name.casefold()]
        if workspace:
            found = self._c.workspaces.find(workspace)
            profiles = [p for p in profiles if found is not None and p.workspace_id == found.id]
        total = len(profiles)
        try:
            limit = min(int(query.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
            offset = max(int(query.get("offset", 0)), 0)
        except ValueError:
            raise ApiError(400, "bad_request", "'limit' and 'offset' must be numbers.") from None
        page = profiles[offset:offset + max(limit, 0)]
        configs = {c.id: c for c in self._c.configurations.list_configurations()}
        workspaces = self._workspace_names()
        used = sorted({p.proxy_id for p in page if p.proxy_id is not None})
        proxies = {row.proxy.id: row for row in self._c.proxies.list_proxies(ids=used)}
        return {
            "total": total,
            "items": [
                self._profile_view(p, configs.get(p.configuration_id), proxies.get(p.proxy_id), workspaces)
                for p in page
            ],
        }

    def get_profile(self, profile_id: int) -> dict:
        return self._view(profile_id)

    def get_connection(self, profile_id: int) -> dict:
        profile = self._c.profiles.get_profile(profile_id)
        if profile.status.value != "RUNNING":
            raise ApiError(409, "not_running", f"Profile {profile_id} is not running; start it first.")
        connection = self.connection_of(profile)
        if connection is None:
            raise ApiError(503, "connection_unavailable", "The browser has not published its debugging address yet; retry in a moment.")
        return connection

    def create_profile(self, body: Any) -> dict:
        body = _obj(body)
        name = _text(body, "name", required=True, limit=MAX_NAME)
        geo_auto = _flag(body, "geo_auto", True)
        start = _flag(body, "start", False)
        given, proxy_id = self._resolve_proxy(body)
        has_workspace, workspace = _workspace(body)
        profile = self._c.profiles.create_profile(
            name,
            proxy_id=proxy_id if given else None,
            auto_config=bool(geo_auto),
            platform=_text(body, "platform"),
            notes=_text(body, "notes") or "",
            tags=_tags(body),
            geo_auto=bool(geo_auto),
            start_url=_text(body, "start_url"),
            workspace_id=self._workspace_id(workspace) if has_workspace else None,
            privacy_settings=privacy.minimal(_privacy(body)) or None,
        )
        self._changed()
        if start:
            return self.start_profile(profile.id)
        return self._view(profile.id)

    def update_profile(self, profile_id: int, body: Any) -> dict:
        body = _obj(body)
        with self._lock(profile_id):
            service = self._c.profiles
            current = service.get_profile(profile_id)
            name = _text(body, "name", limit=MAX_NAME)
            if name is not None and not name.strip():
                raise ApiError(400, "bad_request", "'name' must not be empty.")
            geo_auto = _flag(body, "geo_auto")
            given, proxy_id = self._resolve_proxy(body)
            has_workspace, workspace = _workspace(body)
            service.update_profile(
                profile_id,
                name=name,
                notes=_text(body, "notes"),
                tags=_tags(body),
                geo_auto=geo_auto,
                start_url=_text(body, "start_url"),
                auto_config=False,
            )
            if has_workspace:
                self._c.workspaces.move_profiles([profile_id], self._workspace_id(workspace))
            if given and proxy_id != current.proxy_id:
                service.assign_proxy(
                    profile_id, proxy_id,
                    auto_config=current.geo_auto if geo_auto is None else geo_auto,
                )
            if body.get("regenerate_fingerprint") is True or _text(body, "platform"):
                service.regenerate_configuration(profile_id, _text(body, "platform"))
            wanted = _privacy(body)
            if wanted is not None:
                service.set_privacy(profile_id, wanted)
            if given or geo_auto:
                service.sync_geo(profile_id)
        self._changed()
        return self._view(profile_id)

    def delete_profile(self, profile_id: int, query: dict | None = None) -> dict:
        """Move the profile to the trash; ``?permanent=true`` deletes it (and its folder) for good."""
        raw = ((query or {}).get("permanent") or "").strip().lower()
        if raw not in ("", "0", "1", "true", "false", "yes", "no"):
            raise ApiError(400, "bad_request", "'permanent' must be true or false.")
        permanent = raw in ("1", "true", "yes")
        with self._lock(profile_id):
            if permanent:
                self._c.profiles.delete_profile(profile_id)
            else:
                self._c.profiles.trash_profile(profile_id)
        with self._guard:
            self._locks.pop(profile_id, None)
        self._changed()
        return {"id": profile_id, "deleted": True, "trashed": not permanent}

    def start_profile(self, profile_id: int) -> dict:
        """Start (or find already running) and answer with the address automation connects to."""
        with self._lock(profile_id):
            before = self._c.profiles.get_profile(profile_id)
            already = before.status.value == "RUNNING"
            if not already:
                self._c.profiles.start_profile(profile_id)
                self._changed()
            view = self._view(profile_id)
        view["already_running"] = already
        return view

    def stop_profile(self, profile_id: int) -> dict:
        with self._lock(profile_id):
            self._c.profiles.stop_profile(profile_id)
        self._changed()
        return self._view(profile_id)

    def open_url(self, profile_id: int, body: Any) -> dict:
        url = _http_url(_obj(body).get("url"))
        self._c.profiles.open_url(profile_id, url)
        return {"id": profile_id, "opened": url}

    # ----------------------------------------------------------------- cookies
    def _browser_ws(self, profile_id: int) -> str:
        connection = self.get_connection(profile_id)
        return connection["ws"]

    def get_cookies(self, profile_id: int) -> dict:
        reply = cdp_call(self._browser_ws(profile_id), "Storage.getCookies")
        cookies = reply.get("cookies") or []
        return {"count": len(cookies), "cookies": cookies}

    def set_cookies(self, profile_id: int, body: Any) -> dict:
        cookies = clean_cookies(body)
        ws = self._browser_ws(profile_id)
        if cookies:
            cdp_call(ws, "Storage.setCookies", {"cookies": cookies})
        self._c.logs.info("api", f"Profile #{profile_id:03d}: {len(cookies)} cookies imported", {"profile_id": profile_id})
        return {"imported": len(cookies)}

    def clear_cookies(self, profile_id: int) -> dict:
        cdp_call(self._browser_ws(profile_id), "Storage.clearCookies")
        self._c.logs.info("api", f"Profile #{profile_id:03d}: cookies cleared", {"profile_id": profile_id})
        return {"cleared": True}

    # ----------------------------------------------------------------- proxies
    @staticmethod
    def _proxy_line(item: Any, default_type: str | None) -> str:
        """One proxy as a line the parser reads: a string as sent, or an object with parts."""
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            host, port = item.get("host"), item.get("port")
            if not isinstance(host, str) or not host.strip() or not str(port or "").strip().isdigit():
                raise ApiError(400, "bad_request", "A proxy object needs 'host' and a numeric 'port'.")
            kind = str(item.get("type") or default_type or "http").lower()
            user, password = item.get("username"), item.get("password")
            credentials = f"{quote(str(user), safe='')}:{quote(str(password or ''), safe='')}@" if user else ""
            return f"{kind}://{credentials}{host.strip()}:{int(str(port).strip())}"
        raise ApiError(400, "bad_request", "A proxy is a string like 'user:pass@host:port' or an object.")

    def _import_proxies(self, items: list, default_type: str | None):
        if default_type is not None and default_type.upper() not in ProxyProtocol.__members__:
            raise ApiError(400, "bad_request", "'type' must be http, https or socks5.")
        protocol = ProxyProtocol[default_type.upper()] if default_type else None
        text = "\n".join(self._proxy_line(item, default_type) for item in items)
        return self._c.proxies.import_text(text, protocol)

    def _resolve_proxy(self, body: dict) -> tuple[bool, int | None]:
        """``(given, proxy_id)``: whether the body says anything about the proxy, and which one."""
        if "proxy" in body and "proxy_id" in body:
            raise ApiError(400, "bad_request", "Send either 'proxy' or 'proxy_id', not both.")
        if "proxy_id" in body:
            value = body["proxy_id"]
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise ApiError(400, "bad_request", "'proxy_id' must be a number or null.")
            return True, value
        if "proxy" not in body:
            return False, None
        value = body["proxy"]
        if value is None or value == "":
            return True, None
        summary = self._import_proxies([value], _text(body, "proxy_type"))
        if not summary.ids:
            raise ApiError(422, "proxy_unreadable", "Couldn't read this proxy. Use user:pass@host:port or socks5://host:port.")
        proxy_id = summary.ids[0]
        if _flag(body, "check_proxy", True):
            rows = self._c.proxies.list_proxies(ids=[proxy_id])
            if rows and rows[0].checked_at is None:       # the exit country decides time zone and language
                try:
                    self._c.proxies.check_proxy(proxy_id)
                except Exception:
                    pass
        return True, proxy_id

    def list_proxies(self, query: dict) -> dict:
        status = (query.get("status") or "").strip() or None
        try:
            rows = self._c.proxies.list_proxies(status=status, sort="id")
        except ValueError:
            raise ApiError(400, "bad_request", "'status' must be one of: unknown, working, dead, error.") from None
        total = len(rows)
        try:
            limit = min(int(query.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
            offset = max(int(query.get("offset", 0)), 0)
        except ValueError:
            raise ApiError(400, "bad_request", "'limit' and 'offset' must be numbers.") from None
        return {"total": total, "items": [self.proxy_view(r) for r in rows[offset:offset + max(limit, 0)]]}

    def add_proxies(self, body: Any) -> dict:
        body = _obj(body)
        raw = body.get("proxies")
        if isinstance(raw, str):
            raw = [line for line in raw.splitlines() if line.strip()]
        if not isinstance(raw, list) or not raw:
            raise ApiError(400, "bad_request", "'proxies' must be a non-empty list (or text, one proxy per line).")
        summary = self._import_proxies(raw, _text(body, "type"))
        if _flag(body, "check", False) and summary.ids:
            self._c.proxies.check_all(ids=summary.ids, purge_failed=False)
        rows = self._c.proxies.list_proxies(ids=summary.ids)
        return {
            "added": summary.added,
            "existing": summary.existing,
            "invalid": summary.invalid,
            "items": [self.proxy_view(r) for r in rows],
        }

    def check_proxy(self, proxy_id: int) -> dict:
        self._c.proxies.check_proxy(proxy_id)
        rows = self._c.proxies.list_proxies(ids=[proxy_id])
        return self.proxy_view(rows[0])

    def delete_proxy(self, proxy_id: int) -> dict:
        self._c.proxies.get_proxy(proxy_id)
        self._c.proxies.delete_proxies([proxy_id])
        self._changed()
        return {"id": proxy_id, "deleted": True}
