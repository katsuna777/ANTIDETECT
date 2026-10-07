from __future__ import annotations

from datetime import datetime
from typing import Optional

from antidetect.domain.enums.proxy_status import Anonymity, ProxyProtocol, ProxyStatus


class Proxy:
    """Immutable representation of a stored proxy endpoint."""

    __slots__ = (
        "id",
        "protocol",
        "host",
        "port",
        "username",
        "password",
        "country",
        "country_code",
        "source",
        "status",
        "consecutive_failures",
        "created_at",
        "updated_at",
        "last_checked_at",
    )

    def __init__(
        self,
        id: int,
        protocol: ProxyProtocol,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        country: Optional[str] = None,
        country_code: Optional[str] = None,
        source: Optional[str] = None,
        status: ProxyStatus = ProxyStatus.UNKNOWN,
        consecutive_failures: int = 0,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        last_checked_at: Optional[datetime] = None,
    ) -> None:
        self.id = id
        self.protocol = protocol
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.country = country
        self.country_code = country_code
        self.source = source
        self.status = status
        self.consecutive_failures = consecutive_failures
        self.created_at = created_at
        self.updated_at = updated_at
        self.last_checked_at = last_checked_at

    @property
    def host_port(self) -> str:
        return f"{self.host}:{self.port}"

    def dedupe_key(self) -> tuple[str, str, int]:
        return (self.protocol.value, self.host, self.port)

    def replace(self, **changes) -> "Proxy":
        values = {
            "id": self.id,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "country": self.country,
            "country_code": self.country_code,
            "source": self.source,
            "status": self.status,
            "consecutive_failures": self.consecutive_failures,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_checked_at": self.last_checked_at,
        }
        values.update(changes)
        return Proxy(**values)

    def __repr__(self) -> str:
        return (
            f"Proxy(id={self.id}, {self.protocol.value}://{self.host_port}, "
            f"status={self.status.value})"
        )


class ProxyWithCheck:
    """A proxy joined with its latest check result (read model for listings)."""

    __slots__ = (
        "proxy",
        "checked_at",
        "latency_ms",
        "external_ip",
        "country",
        "country_code",
        "anonymity",
        "check_error",
    )

    def __init__(
        self,
        proxy: Proxy,
        checked_at: Optional[datetime] = None,
        latency_ms: Optional[int] = None,
        external_ip: Optional[str] = None,
        country: Optional[str] = None,
        country_code: Optional[str] = None,
        anonymity: Optional[Anonymity] = None,
        check_error: Optional[str] = None,
    ) -> None:
        self.proxy = proxy
        self.checked_at = checked_at
        self.latency_ms = latency_ms
        self.external_ip = external_ip
        self.country = country
        self.country_code = country_code
        self.anonymity = anonymity
        self.check_error = check_error

    @property
    def id(self) -> int:
        return self.proxy.id

    def __repr__(self) -> str:
        return (
            f"ProxyWithCheck(id={self.proxy.id}, "
            f"status={self.proxy.status.value}, latency={self.latency_ms}ms)"
        )