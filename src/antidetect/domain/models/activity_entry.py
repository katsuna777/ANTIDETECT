from __future__ import annotations

from datetime import datetime


class ActivityEntry:
    """One line of the Activity feed: *what* happened (``kind``), to *which* thing (``subject``) and the details.

    The text is not stored: the GUI turns ``kind`` + ``subject`` + ``data`` into a sentence in the
    language the user has chosen at the time the feed is shown.
    """

    __slots__ = ("id", "ts", "kind", "level", "subject", "data")

    def __init__(self, id: int, ts: datetime, kind: str, subject: str = "", data: dict | None = None,
                 level: str = "INFO") -> None:
        self.id = id
        self.ts = ts
        self.kind = kind
        self.subject = subject
        self.data = data or {}
        self.level = level

    def __repr__(self) -> str:
        return f"ActivityEntry(id={self.id}, kind={self.kind!r}, subject={self.subject!r})"
