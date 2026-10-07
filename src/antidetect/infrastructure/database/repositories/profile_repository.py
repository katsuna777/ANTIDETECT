from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from antidetect.domain.enums.profile_status import ProfileStatus
from antidetect.domain.models.profile import Profile
from antidetect.infrastructure.database.sequence_utils import reset_sequence

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database

_COLUMNS = (
    "id, name, profile_path, configuration_id, proxy_id, status, "
    "created_at, updated_at, last_started_at, last_stopped_at, pid, "
    "notes, tags, geo_auto, start_url, workspace_id, deleted_at"
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
            notes=row["notes"] or "",
            tags=split_tags(row["tags"]),
            geo_auto=bool(row["geo_auto"]),
            start_url=row["start_url"],
            workspace_id=row["workspace_id"],
            deleted_at=_parse_dt(row["deleted_at"]),
        )


def split_tags(raw: str | None) -> list[str]:
    """Stored ``a, b, c`` -> ``["a", "b", "c"]`` (trimmed, no empties)."""
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def join_tags(tags: list[str] | None) -> str:
    """Normalize tags: trimmed, no commas inside, unique case-insensitively."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags or []:
        clean = str(tag).replace(",", " ").strip()
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            out.append(clean)
    return ", ".join(out)


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
        *,
        notes: str = "",
        tags: list[str] | None = None,
        geo_auto: bool = True,
        start_url: str | None = None,
        workspace_id: int | None = None,
    ) -> Profile:
        now = _serialize_dt(created_at)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO profiles (name, profile_path, configuration_id, proxy_id, status,
                                      created_at, updated_at, notes, tags, geo_auto, start_url,
                                      workspace_id)
                VALUES (?, ?, ?, ?, 'STOPPED', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, profile_path, configuration_id, proxy_id, now, now,
                    notes or "", join_tags(tags), 1 if geo_auto else 0, start_url or None,
                    workspace_id,
                ),
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
        """The profiles that are not in the trash."""
        rows = self._db.execute(
            f"SELECT {_COLUMNS} FROM profiles WHERE deleted_at IS NULL ORDER BY id"
        ).fetchall()
        return [_RowProfile(row).to_profile() for row in rows]

    def list_all(self) -> list[Profile]:
        """Every profile, the trash included (a tag rename has to reach those as well)."""
        rows = self._db.execute(f"SELECT {_COLUMNS} FROM profiles ORDER BY id").fetchall()
        return [_RowProfile(row).to_profile() for row in rows]

    def list_trashed(self) -> list[Profile]:
        """Profiles in the trash, the most recently deleted first."""
        rows = self._db.execute(
            f"SELECT {_COLUMNS} FROM profiles WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC, id DESC"
        ).fetchall()
        return [_RowProfile(row).to_profile() for row in rows]

    def count_trashed(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM profiles WHERE deleted_at IS NOT NULL").fetchone()[0])

    def find_by_name(self, name: str) -> Profile | None:
        """The live profile with exactly this name (a name in the trash does not count)."""
        row = self._db.execute(
            f"SELECT {_COLUMNS} FROM profiles WHERE name = ? AND deleted_at IS NULL LIMIT 1", (name,)
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
        notes: str | None = None,
        tags: list[str] | None = None,
        geo_auto: bool | None = None,
        start_url: str | None = None,
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
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        if tags is not None:
            updates.append("tags = ?")
            params.append(join_tags(tags))
        if geo_auto is not None:
            updates.append("geo_auto = ?")
            params.append(1 if geo_auto else 0)
        if start_url is not None:
            updates.append("start_url = ?")
            params.append(start_url or None)
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
                SET status = ?, pid = ?,
                    last_started_at = COALESCE(?, last_started_at),
                    last_stopped_at = COALESCE(?, last_stopped_at),
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

    def trash(self, profile_ids: list[int], moment: datetime) -> int:
        """Move profiles to the trash (nothing on disk is touched)."""
        return self._mark(profile_ids, f"deleted_at = ?, status = 'STOPPED', pid = NULL", _serialize_dt(moment))

    def restore(self, profile_id: int, name: str | None = None) -> Profile | None:
        """Bring a profile back from the trash (under ``name`` when its old name is taken)."""
        with self._db.transaction() as conn:
            if name is not None:
                conn.execute("UPDATE profiles SET name = ? WHERE id = ?", (name, profile_id))
            conn.execute(
                f"UPDATE profiles SET deleted_at = NULL, updated_at = {_SQL_UPDATED} WHERE id = ?", (profile_id,)
            )
        return self.get(profile_id)

    def set_workspace(self, profile_ids: list[int], workspace_id: int | None) -> int:
        """Put profiles into a workspace (``None`` = into no workspace)."""
        return self._mark(profile_ids, "workspace_id = ?", workspace_id)

    def _mark(self, profile_ids: list[int], assignment: str, value) -> int:
        ids = [int(i) for i in profile_ids]
        if not ids:
            return 0
        changed = 0
        with self._db.transaction() as conn:
            for start in range(0, len(ids), 500):       # SQLite caps the number of bound variables
                chunk = ids[start:start + 500]
                marks = ",".join("?" * len(chunk))
                cursor = conn.execute(
                    f"UPDATE profiles SET {assignment}, updated_at = {_SQL_UPDATED} WHERE id IN ({marks})",
                    (value, *chunk),
                )
                changed += cursor.rowcount
        return changed

    def delete(self, profile_id: int) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            reset_sequence(conn, "profiles")
            return cursor.rowcount > 0