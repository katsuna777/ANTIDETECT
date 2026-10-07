from __future__ import annotations

from typing import TYPE_CHECKING

from antidetect.domain.models.tag import Workspace
from antidetect.infrastructure.database.datetime_utils import SQL_NOW, parse_dt
from antidetect.infrastructure.database.repositories.tag_repository import key_of

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database


class SqliteWorkspaceRepository:
    def __init__(self, db: "Database") -> None:
        self._db = db

    @staticmethod
    def _workspace(row) -> Workspace:
        return Workspace(id=row["id"], name=row["name"], color=row["color"], created_at=parse_dt(row["created_at"]))

    def list(self) -> list[Workspace]:
        rows = self._db.execute("SELECT id, name, color, created_at FROM workspaces ORDER BY id").fetchall()
        return [self._workspace(row) for row in rows]

    def get(self, workspace_id: int) -> Workspace | None:
        row = self._db.execute(
            "SELECT id, name, color, created_at FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone()
        return self._workspace(row) if row else None

    def find(self, name: str) -> Workspace | None:
        row = self._db.execute(
            "SELECT id, name, color, created_at FROM workspaces WHERE key = ?", (key_of(name),)
        ).fetchone()
        return self._workspace(row) if row else None

    def counts(self) -> dict[int | None, int]:
        """Live (not trashed) profiles per workspace; ``None`` = in no workspace."""
        rows = self._db.execute(
            "SELECT workspace_id, COUNT(*) AS n FROM profiles WHERE deleted_at IS NULL GROUP BY workspace_id"
        ).fetchall()
        return {row["workspace_id"]: int(row["n"]) for row in rows}

    def create(self, name: str, color: int) -> Workspace:
        name = name.strip()
        with self._db.transaction() as conn:
            cursor = conn.execute(
                f"INSERT INTO workspaces (name, key, color, created_at) VALUES (?, ?, ?, {SQL_NOW})",
                (name, key_of(name), color),
            )
            workspace_id = int(cursor.lastrowid)
        created = self.get(workspace_id)
        if created is None:
            raise RuntimeError("Failed to load the workspace that was just created.")
        return created

    def rename(self, workspace_id: int, name: str) -> Workspace | None:
        name = name.strip()
        with self._db.transaction() as conn:
            conn.execute("UPDATE workspaces SET name = ?, key = ? WHERE id = ?", (name, key_of(name), workspace_id))
        return self.get(workspace_id)

    def set_color(self, workspace_id: int, color: int) -> Workspace | None:
        with self._db.transaction() as conn:
            conn.execute("UPDATE workspaces SET color = ? WHERE id = ?", (color, workspace_id))
        return self.get(workspace_id)

    def delete(self, workspace_id: int) -> bool:
        """Remove the workspace; its profiles stay, in no workspace (the foreign key sets them free)."""
        with self._db.transaction() as conn:
            return conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,)).rowcount > 0
