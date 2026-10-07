from __future__ import annotations

from typing import TYPE_CHECKING

from antidetect.domain.models.tag import Tag
from antidetect.infrastructure.database.datetime_utils import SQL_NOW, parse_dt

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database


def key_of(name: str) -> str:
    """The form names are compared in: SQLite's NOCASE only folds ASCII, Python's casefold folds Cyrillic too."""
    return (name or "").strip().casefold()


class SqliteTagRepository:
    """The tag registry: a name and a colour slot. Which profile carries a tag lives in ``profiles.tags``."""

    def __init__(self, db: "Database") -> None:
        self._db = db

    @staticmethod
    def _tag(row) -> Tag:
        return Tag(id=row["id"], name=row["name"], color=row["color"], created_at=parse_dt(row["created_at"]))

    def list(self) -> list[Tag]:
        rows = self._db.execute("SELECT id, name, color, created_at FROM tags ORDER BY id").fetchall()
        return [self._tag(row) for row in rows]

    def get(self, tag_id: int) -> Tag | None:
        row = self._db.execute("SELECT id, name, color, created_at FROM tags WHERE id = ?", (tag_id,)).fetchone()
        return self._tag(row) if row else None

    def find(self, name: str) -> Tag | None:
        row = self._db.execute(
            "SELECT id, name, color, created_at FROM tags WHERE key = ?", (key_of(name),)
        ).fetchone()
        return self._tag(row) if row else None

    def create(self, name: str, color: int) -> Tag:
        name = name.strip()
        with self._db.transaction() as conn:
            cursor = conn.execute(
                f"INSERT INTO tags (name, key, color, created_at) VALUES (?, ?, ?, {SQL_NOW})",
                (name, key_of(name), color),
            )
            tag_id = int(cursor.lastrowid)
        created = self.get(tag_id)
        if created is None:
            raise RuntimeError("Failed to load the tag that was just created.")
        return created

    def rename(self, tag_id: int, name: str) -> Tag | None:
        name = name.strip()
        with self._db.transaction() as conn:
            conn.execute("UPDATE tags SET name = ?, key = ? WHERE id = ?", (name, key_of(name), tag_id))
        return self.get(tag_id)

    def set_color(self, tag_id: int, color: int) -> Tag | None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE tags SET color = ? WHERE id = ?", (color, tag_id))
        return self.get(tag_id)

    def delete(self, tag_id: int) -> bool:
        with self._db.transaction() as conn:
            return conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,)).rowcount > 0
