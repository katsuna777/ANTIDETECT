from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.domain.enums.profile_status import ProfileStatus
from app.domain.models.profile import Profile
from app.infrastructure.database.sequence_utils import reset_sequence

if TYPE_CHECKING:
    from app.infrastructure.database.connection import Database

_COLUMNS = (
    "id, name, profile_path, configuration_id, proxy_id, status, "
    "created_at, updated_at, last_started_at, last_stopped_at, pid"
)

_SQL_UPDATED = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


class _RowProfile:
    """Adapts a sqlite3.Row into a domain Profile."""

    def __init__(self, row) -> None:
        self._row = row

    def to_profile(self) -> Profile:
        row = self._row
        return Profile(
            id=row["id"],
            name=row["name"],
            profile_path=row["profile_path"],
            configuration_id=row["configuration_id"],
            proxy_id=row["proxy_id"],
            status=ProfileStatus.from_string(row["status"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            last_started_at=_parse_dt(row["last_started_at"]),
            last_stopped_at=_parse_dt(row["last_stopped_at"]),
            pid=row["pid"],
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _serialize_dt(value: datetime) -> str:
    """Store datetimes as UTC-naive ISO strings, matching SQLite's strftime."""
    dt = value
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="microseconds")


class SqliteProfileRepository:
    def __init__(self, db: "Database") -> None:
        self._db = db

    def create(
        self,
        name: str,
        profile_path: str,
        configuration_id: int,
        created_at: datetime,
        proxy_id: int | None = None,
    ) -> Profile:
        now = _serialize_dt(created_at)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO profiles (name, profile_path, configuration_id, proxy_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'STOPPED', ?, ?)
                """,
                (name, profile_path, configuration_id, proxy_id, now, now),
            )
            profile_id = int(cursor.lastrowid)
        created = self.get(profile_id)
        if created is None:
            raise RuntimeError("Failed to load freshly created profile.")
        return created

    def get(self, profile_id: int) -> Profile | None:
        row = self._db.execute(f"SELECT {_COLUMNS} FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        return _RowProfile(row).to_profile() if row else None

    def list(self) -> list[Profile]:
        rows = self._db.execute(f"SELECT {_COLUMNS} FROM profiles ORDER BY id").fetchall()
        return [_RowProfile(row).to_profile() for row in rows]

    def find_by_name(self, name: str) -> Profile | None:
        row = self._db.execute(
            f"SELECT {_COLUMNS} FROM profiles WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        return _RowProfile(row).to_profile() if row else None

    def update(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        profile_path: str | None = None,
        configuration_id: int | None = None,
        proxy_id: int | None = None,
    ) -> Profile | None:
        updates = []
        params: list = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if profile_path is not None:
            updates.append("profile_path = ?")
            params.append(profile_path)
        if configuration_id is not None:
            updates.append("configuration_id = ?")
            params.append(configuration_id)
        if proxy_id is not None:
            updates.append("proxy_id = ?")
            params.append(proxy_id)
        if not updates:
            return self.get(profile_id)
        updates.append(f"updated_at = {_SQL_UPDATED}")
        params.append(profile_id)
        with self._db.transaction() as conn:
            conn.execute(f"UPDATE profiles SET {', '.join(updates)} WHERE id = ?", params)
        return self.get(profile_id)

    def set_configuration(
        self, profile_id: int, configuration_id: int | None
    ) -> Profile | None:
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE profiles SET configuration_id = ?, updated_at = {_SQL_UPDATED} WHERE id = ?",
                (configuration_id, profile_id),
            )
        return self.get(profile_id)

    def set_proxy(self, profile_id: int, proxy_id: int | None) -> Profile | None:
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE profiles SET proxy_id = ?, updated_at = {_SQL_UPDATED} WHERE id = ?",
                (proxy_id, profile_id),
            )
        return self.get(profile_id)

    def update_runtime(
        self,
        profile_id: int,
        *,
        status: ProfileStatus,
        pid: int | None = None,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """
                UPDATE profiles
                SET status = ?, pid = ?, last_started_at = ?, last_stopped_at = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (
                    status.value,
                    pid,
                    _serialize_dt(started_at) if started_at else None,
                    _serialize_dt(stopped_at) if stopped_at else None,
                    profile_id,
                ),
            )

    def delete(self, profile_id: int) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            reset_sequence(conn, "profiles")
            return cursor.rowcount > 0