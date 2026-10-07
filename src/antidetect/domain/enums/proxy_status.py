from __future__ import annotations

from enum import Enum


class ProxyProtocol(str, Enum):
    """Transport protocol supported by Chromium and the proxy subsystem."""

    HTTP = "HTTP"
    HTTPS = "HTTPS"
    SOCKS5 = "SOCKS5"

    @classmethod
    def from_string(cls, value: str) -> "ProxyProtocol":
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"Unknown proxy protocol: {value!r}") from exc


class ProxyStatus(str, Enum):
    """Lifecycle status of a stored proxy as persisted in the database."""

    UNKNOWN = "UNKNOWN"
    CHECKING = "CHECKING"
    WORKING = "WORKING"
    DEAD = "DEAD"
    ERROR = "ERROR"

    @classmethod
    def from_string(cls, value: str) -> "ProxyStatus":
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"Unknown proxy status: {value!r}") from exc


class Anonymity(str, Enum):
    """Anonymity level of a working proxy, best-effort and conservative."""

    UNKNOWN = "unknown"
    TRANSPARENT = "transparent"
    ANONYMOUS = "anonymous"
    ELITE = "elite"

    @classmethod
    def from_string(cls, value: str | None) -> "Anonymity":
        if not value:
            return cls.UNKNOWN
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN