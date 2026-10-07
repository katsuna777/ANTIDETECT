from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from antidetect.domain.enums.proxy_status import ProxyProtocol


@dataclass(frozen=True)
class ProxyEntry:
    """A parsed, normalized proxy candidate that has not been persisted yet.

    Produced by the parser/collector pipeline and consumed by the repository
    during ``upsert``. Whether a username/password pair is present or not is
    kept as-is from the source line.
    """

    protocol: ProxyProtocol
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    source: Optional[str] = None

    def dedupe_key(self) -> tuple[str, str, int]:
        return (self.protocol.value, self.host, self.port)


@dataclass(frozen=True)
class ProxyBatch:
    """Result of a collection run across all configured sources."""

    entries: list[ProxyEntry] = field(default_factory=list)
    source_stats: list["SourceStatistics"] = field(default_factory=list)

    @property
    def new_entries(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class SourceStatistics:
    name: str
    fetched: bool
    lines: int = 0
    found: int = 0
    error: Optional[str] = None