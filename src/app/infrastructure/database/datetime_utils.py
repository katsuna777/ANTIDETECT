from __future__ import annotations

from datetime import datetime, timezone

SQL_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def serialize_dt(value: datetime) -> str:
    """Store datetimes as UTC-naive ISO strings, matching SQLite's strftime."""
    dt = value
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="microseconds")