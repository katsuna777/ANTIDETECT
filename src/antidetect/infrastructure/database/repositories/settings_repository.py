from __future__ import annotations

from typing import TYPE_CHECKING

from antidetect.domain.models.app_setting import AppSetting

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database


class SqliteSettingsRepository:
    def __init__(self, db: "Database") -> None:
        self._db = db

    def get(self, key: str) -> AppSetting | None:
        row = self._db.execute(
            "SELECT key, value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return AppSetting(key=row["key"], value=row["value"]) if row else None

    def set(self, key: str, value: str | None) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
