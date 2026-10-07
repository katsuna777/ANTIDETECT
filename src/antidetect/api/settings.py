"""API settings: switch, port and access keys, kept in the same settings table as every preference."""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

#: The API listens on the loopback interface only. There is deliberately no option to change
#: it: reachable from the network, anyone could start your profiles.
HOST = "127.0.0.1"
DEFAULT_PORT = 47831
MIN_PORT = 1024
MAX_PORT = 65535
MAX_KEY_NAME = 60
DEFAULT_KEY_NAME = "Main"

KEY_ENABLED = "api.enabled"
KEY_PORT = "api.port"
KEY_KEYS = "api.keys"
KEY_LEGACY_TOKEN = "api.token"          # the single token of the first version; becomes the key "Main"


class ApiKeyError(ValueError):
    """A key operation that cannot be done; ``reason`` lets the GUI say it in the user's language."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason        # "empty" | "long" | "duplicate" | "last"


class _Store(Protocol):
    def get(self, key: str): ...   # pragma: no cover

    def set(self, key: str, value: str | None) -> None: ...   # pragma: no cover


@dataclass(frozen=True)
class ApiKey:
    """One access key. Each script, machine or teammate can have its own and lose it on its own."""

    id: str
    name: str
    token: str
    created_at: str          # ISO 8601, UTC

    def masked(self) -> str:
        """``ad_Xk3…f9Q``: enough to tell keys apart, nothing a shoulder-surfer can use."""
        return f"{self.token[:6]}…{self.token[-3:]}"


def parse_port(value) -> int:
    """A usable port number, or ``ValueError`` (ports below 1024 need admin rights)."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"Port must be a number between {MIN_PORT} and {MAX_PORT}.") from None
    if not MIN_PORT <= port <= MAX_PORT:
        raise ValueError(f"Port must be between {MIN_PORT} and {MAX_PORT}.")
    return port


def new_token() -> str:
    return "ad_" + secrets.token_urlsafe(32)


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ApiKeyError("empty", "The key needs a name.")
    if len(name) > MAX_KEY_NAME:
        raise ApiKeyError("long", f"The name is too long (at most {MAX_KEY_NAME} characters).")
    return name


class ApiSettings:
    def __init__(self, store: _Store) -> None:
        self._store = store

    def _get(self, key: str) -> str:
        setting = self._store.get(key)
        return (setting.value or "").strip() if setting is not None and setting.value is not None else ""

    # ------------------------------------------------------------------ switch, port
    @property
    def enabled(self) -> bool:
        return self._get(KEY_ENABLED).lower() in ("1", "true", "yes", "on")

    def set_enabled(self, enabled: bool) -> None:
        self._store.set(KEY_ENABLED, "1" if enabled else "0")

    @property
    def port(self) -> int:
        try:
            return parse_port(self._get(KEY_PORT) or DEFAULT_PORT)
        except ValueError:
            return DEFAULT_PORT

    def set_port(self, port) -> int:
        value = parse_port(port)
        self._store.set(KEY_PORT, str(value))
        return value

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    # ------------------------------------------------------------------ keys
    def keys(self) -> list[ApiKey]:
        """Every key, oldest first. There is always at least one: the first call creates "Main"."""
        found = self._read()
        if found is None:
            legacy = self._get(KEY_LEGACY_TOKEN)
            found = [self._make(DEFAULT_KEY_NAME, legacy or new_token())]
            self._write(found)
        return found

    def key_count(self) -> int:
        """How many keys there are, without creating the first one (for a counter shown at start-up)."""
        found = self._read()
        return len(found) if found is not None else 1

    def _read(self) -> list[ApiKey] | None:
        raw = self._get(KEY_KEYS)
        if not raw:
            return None
        try:
            items = json.loads(raw)
            keys = [ApiKey(str(i["id"]), str(i["name"]), str(i["token"]), str(i.get("created_at", ""))) for i in items]
        except (ValueError, TypeError, KeyError):
            return None
        return keys or None

    def _write(self, keys: list[ApiKey]) -> None:
        self._store.set(KEY_KEYS, json.dumps([k.__dict__ for k in keys], ensure_ascii=False))

    @staticmethod
    def _make(name: str, token: str | None = None) -> ApiKey:
        return ApiKey(
            id=secrets.token_hex(4),
            name=name,
            token=token or new_token(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def get_key(self, key_id: str) -> ApiKey:
        for key in self.keys():
            if key.id == key_id:
                return key
        raise KeyError(key_id)

    def find(self, token: str) -> ApiKey | None:
        """The key a token belongs to (compared in constant time), or ``None``."""
        match = None
        for key in self.keys():
            if hmac.compare_digest(token.encode(), key.token.encode()):
                match = key
        return match

    def add_key(self, name: str) -> ApiKey:
        name = _clean_name(name)
        keys = self.keys()
        if any(k.name.casefold() == name.casefold() for k in keys):
            raise ApiKeyError("duplicate", f"There is already a key named “{name}”.")
        key = self._make(name)
        self._write(keys + [key])
        return key

    def rename_key(self, key_id: str, name: str) -> ApiKey:
        name = _clean_name(name)
        keys = self.keys()
        if any(k.id != key_id and k.name.casefold() == name.casefold() for k in keys):
            raise ApiKeyError("duplicate", f"There is already a key named “{name}”.")
        old = self.get_key(key_id)
        renamed = ApiKey(old.id, name, old.token, old.created_at)
        self._write([renamed if k.id == key_id else k for k in keys])
        return renamed

    def regenerate_key(self, key_id: str) -> ApiKey:
        """A new secret for the same key; the old one stops working at once."""
        old = self.get_key(key_id)
        fresh = ApiKey(old.id, old.name, new_token(), old.created_at)
        self._write([fresh if k.id == key_id else k for k in self.keys()])
        return fresh

    def delete_key(self, key_id: str) -> None:
        keys = self.keys()
        if len(keys) <= 1:
            raise ApiKeyError("last", "The last key cannot be deleted: make a new one first, or switch the API off.")
        if not any(k.id == key_id for k in keys):
            raise KeyError(key_id)
        self._write([k for k in keys if k.id != key_id])

    # ------------------------------------------------------------------ the first key
    @property
    def token(self) -> str:
        """The token of the first key: what the command line and the examples use."""
        return self.keys()[0].token

    def regenerate_token(self) -> str:
        return self.regenerate_key(self.keys()[0].id).token
