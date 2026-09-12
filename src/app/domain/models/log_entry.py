from __future__ import annotations

from datetime import datetime
from typing import Optional


class LogEntry:
    """Immutable representation of a single persisted log record."""

    __slots__ = ("id", "ts", "level", "source", "message", "extra")

    def __init__(
        self,
        id: int,
        ts: datetime,
        level: str,
        source: str,
        message: str,
        extra: Optional[dict] = None,
    ) -> None:
        self.id = id
        self.ts = ts
        self.level = level
        self.source = source
        self.message = message
        self.extra = extra

    def __repr__(self) -> str:
        return (
            f"LogEntry(id={self.id}, ts={self.ts.isoformat()}, "
            f"level={self.level}, source={self.source}, message={self.message!r})"
        )