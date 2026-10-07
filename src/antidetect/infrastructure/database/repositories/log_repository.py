from __future__ import annotations

import json
from typing import TYPE_CHECKING

from antidetect.domain.models.log_entry import LogEntry
from antidetect.infrastructure.database.datetime_utils import parse_dt, serialize_dt

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database


class SqliteLogRepository:
    """SQLite-backed store for the application's human-readable log stream.

    Entries are inserted in real time from worker/GUI threads (the shared
    ``Database`` connection is reentrant-locked) and read incrementally by the
    live Log page via ``list_after``, so each poll only fetches new rows.
    """

    def __init__(self, db: "Database") -> None:
        self._db = db

    def insert(self, entry: LogEntry) -> int:
        cur = self._db.execute(
            """
            INSERT INTO app_logs (ts, level, source, message, extra)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                serialize_dt(entry.ts),
                entry.level,
                entry.source,
                entry.message,
                _serialize_extra(entry.extra),
            ),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def insert_many(self, entries: list[LogEntry]) -> int:
        if not entries:
            return 0
        rows = [
            (
                serialize_dt(entry.ts),
                entry.level,
                entry.source,
                entry.message,
                _serialize_extra(entry.extra),
            )
            for entry in entries
        ]
        self._db.executemany(
            """
            INSERT INTO app_logs (ts, level, source, message, extra)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._db.commit()
        return len(rows)

    def list_after(self, after_id: int = 0, limit: int = 5000) -> list[LogEntry]:
        rows = self._db.execute(
            """
            SELECT id, ts, level, source, message, extra
            FROM app_logs
            WHERE id > ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (after_id, limit),
        ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def all(self, limit: int = 100_000) -> list[LogEntry]:
        rows = self._db.execute(
            """
            SELECT id, ts, level, source, message, extra
            FROM app_logs
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_entry(row) for row in rows]

    def latest_id(self) -> int:
        row = self._db.execute("SELECT MAX(id) AS last_id FROM app_logs").fetchone()
        return int(row["last_id"]) if row is not None and row["last_id"] is not None else 0

    def count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) AS n FROM app_logs").fetchone()
        return int(row["n"]) if row is not None else 0

    def clear(self) -> int:
        cur = self._db.execute("DELETE FROM app_logs")
        self._db.commit()
        return int(cur.rowcount or 0)


def _row_to_entry(row) -> LogEntry:
    return LogEntry(
        id=int(row["id"]),
        ts=_coerce_dt(row["ts"]),
        level=str(row["level"]),
        source=str(row["source"]),
        message=str(row["message"]),
        extra=_deserialize_extra(row["extra"]),
    )


def _coerce_dt(value: str):
    parsed = parse_dt(value)
    if parsed is not None:
        return parsed
    import datetime

    return datetime.datetime.now()

def _serialize_extra(extra: dict | None) -> str | None:
    if not extra:
        return None
    try:
        return json.dumps(extra, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps({str(k): str(v) for k, v in extra.items()}, ensure_ascii=False)


def _deserialize_extra(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        data = json.loads(value)
    except ValueError:
        return {"raw": value}
    return data if isinstance(data, dict) else {"raw": value}