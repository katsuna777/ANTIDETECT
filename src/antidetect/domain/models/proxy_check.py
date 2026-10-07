from __future__ import annotations

from datetime import datetime
from typing import Optional

from antidetect.domain.enums.proxy_status import Anonymity, ProxyStatus


class ProxyCheck:
    """Immutable record of a single check run against one proxy."""

    __slots__ = (
        "id",
        "proxy_id",
        "checked_at",
        "status",
        "latency_ms",
        "external_ip",
        "country",
        "country_code",
        "anonymity",
        "error",
    )

    def __init__(
        self,
        id: int,
        proxy_id: int,
        checked_at: datetime,
        status: ProxyStatus,
        latency_ms: Optional[int] = None,
        external_ip: Optional[str] = None,
        country: Optional[str] = None,
        country_code: Optional[str] = None,
        anonymity: Optional[Anonymity] = None,
        error: Optional[str] = None,
    ) -> None:
        self.id = id
        self.proxy_id = proxy_id
        self.checked_at = checked_at
        self.status = status
        self.latency_ms = latency_ms
        self.external_ip = external_ip
        self.country = country
        self.country_code = country_code
        self.anonymity = anonymity
        self.error = error

    def __repr__(self) -> str:
        return f"ProxyCheck(id={self.id}, proxy_id={self.proxy_id}, status={self.status.value})"