from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from antidetect.domain.models.activity_entry import ActivityEntry
from antidetect.infrastructure.database.datetime_utils import parse_dt, serialize_dt

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database


class SqliteActivityRepository:
    """The Activity feed: append-only, newest read first, trimmed to a few thousand rows."""

    KEEP = 3000
    _TRIM_EVERY = 100

    def __init__(self, db: "Database") -> None:
        self._db = db
        self._since_trim = 0

    def insert(self, entry: ActivityEntry) -> int:
        cursor = self._db.execute(
            "INSERT INTO activity (ts, kind, level, subject, data) VALUES (?, ?, ?, ?, ?)",
            (
                serialize_dt(entry.ts), entry.kind, entry.level, entry.subject,
                json.dumps(entry.data, ensure_ascii=False, default=str) if entry.data else None,
            ),
        )
        self._db.commit()
        self._since_trim += 1
        if self._since_trim >= self._TRIM_EVERY:
            self._since_trim = 0
            self.trim(self.KEEP)
        return int(cursor.lastrowid)

    def list(self, *, before_id: int | None = None, after_id: int | None = None, limit: int = 200,
             prefixes: tuple[str, ...] = (), level: str | None = None) -> list[ActivityEntry]:
        """Newest first. ``prefixes`` keep the kinds that start with one of them (``("profile.",)``)."""
        where, params = ["1 = 1"], []
        if before_id is not None:
            where.append("id < ?")
            params.append(before_id)
        if after_id is not None:
            where.append("id > ?")
            params.append(after_id)
        if prefixes:
            where.append("(" + " OR ".join("kind LIKE ?" for _ in prefixes) + ")")
            params += [f"{prefix}%" for prefix in prefixes]
        if level:
            where.append("level = ?")
            params.append(level)
        rows = self._db.execute(
            f"SELECT id, ts, kind, level, subject, data FROM activity WHERE {' AND '.join(where)} "
            "ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_entry(row) for row in rows]

    def latest_id(self) -> int:
        row = self._db.execute("SELECT MAX(id) AS last_id FROM activity").fetchone()
        return int(row["last_id"]) if row is not None and row["last_id"] is not None else 0

    def count_after(self, after_id: int, level: str | None = None) -> int:
        if level:
            return int(self._db.execute("SELECT COUNT(*) FROM activity WHERE id > ? AND level = ?",
                                        (after_id, level)).fetchone()[0])
        return int(self._db.execute("SELECT COUNT(*) FROM activity WHERE id > ?", (after_id,)).fetchone()[0])

    def trim(self, keep: int) -> int:
        cursor = self._db.execute(
            "DELETE FROM activity WHERE id <= (SELECT MAX(id) FROM activity) - ?", (keep,)
        )
        self._db.commit()
        return int(cursor.rowcount or 0)

    def clear(self) -> int:
        cursor = self._db.execute("DELETE FROM activity")
        self._db.commit()
        return int(cursor.rowcount or 0)


def _entry(row) -> ActivityEntry:
    data: dict = {}
    if row["data"]:
        try:
            loaded = json.loads(row["data"])
            data = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            data = {}
    return ActivityEntry(
        id=int(row["id"]), ts=parse_dt(row["ts"]) or datetime.now(), kind=str(row["kind"]),
        subject=str(row["subject"] or ""), data=data, level=str(row["level"]),
    )

