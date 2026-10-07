"""Workspaces: named groups of profiles (a client, a project, a team). A profile is in at most one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from antidetect.application import palette
from antidetect.domain.errors import WorkspaceAlreadyExistsError, WorkspaceNotFoundError
from antidetect.domain.models.tag import Workspace

if TYPE_CHECKING:
    from antidetect.application.ports import ActivitySink, LogSink, ProfileRepository, WorkspaceRepository

MAX_NAME = 40


def clean_name(name: str) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


@dataclass(frozen=True)
class WorkspaceInfo:
    workspace: Workspace
    count: int


class WorkspaceService:
    def __init__(self, workspaces: "WorkspaceRepository", profiles: "ProfileRepository",
                 activity: "ActivitySink | None" = None, log_sink: "LogSink | None" = None) -> None:
        self._workspaces = workspaces
        self._profiles = profiles
        self._activity = activity
        self._log = log_sink

    def list_workspaces(self) -> list[WorkspaceInfo]:
        counts = self._workspaces.counts()
        return [WorkspaceInfo(w, counts.get(w.id, 0)) for w in self._workspaces.list()]

    def unassigned_count(self) -> int:
        return self._workspaces.counts().get(None, 0)

    def get_workspace(self, workspace_id: int) -> Workspace:
        workspace = self._workspaces.get(workspace_id)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        return workspace

    def find(self, name: str) -> Workspace | None:
        return self._workspaces.find(clean_name(name))

    def create_workspace(self, name: str, color: int | None = None) -> Workspace:
        name = clean_name(name)
        if not name:
            raise ValueError("Workspace name must not be empty.")
        if self._workspaces.find(name) is not None:
            raise WorkspaceAlreadyExistsError(name)
        if color is None:
            color = palette.least_used([w.color for w in self._workspaces.list()],
                                       start=sum(map(ord, name.casefold())) % palette.SLOTS)
        workspace = self._workspaces.create(name, int(color) % palette.SLOTS)
        self._report("act.workspace.created", workspace.name)
        return workspace

    def rename_workspace(self, workspace_id: int, name: str) -> Workspace:
        current = self.get_workspace(workspace_id)
        name = clean_name(name)
        if not name:
            raise ValueError("Workspace name must not be empty.")
        clash = self._workspaces.find(name)
        if clash is not None and clash.id != workspace_id:
            raise WorkspaceAlreadyExistsError(name)
        if name == current.name:
            return current
        renamed = self._workspaces.rename(workspace_id, name)
        self._report("act.workspace.renamed", name, old=current.name)
        return renamed  # type: ignore[return-value]

    def set_color(self, workspace_id: int, color: int) -> Workspace:
        self.get_workspace(workspace_id)
        return self._workspaces.set_color(workspace_id, color % palette.SLOTS)  # type: ignore[return-value]

    def delete_workspace(self, workspace_id: int) -> int:
        """Delete the workspace (its profiles are kept, in no workspace); returns how many were in it."""
        workspace = self.get_workspace(workspace_id)
        count = self._workspaces.counts().get(workspace_id, 0)
        self._workspaces.delete(workspace_id)
        self._report("act.workspace.deleted", workspace.name, profiles=count)
        return count

    def move_profiles(self, profile_ids: list[int], workspace_id: int | None) -> int:
        """Put profiles into a workspace (``None`` = take them out of any)."""
        target = self.get_workspace(workspace_id) if workspace_id is not None else None
        moved = self._profiles.set_workspace(list(profile_ids), workspace_id)
        if moved:
            self._report("act.profile.moved", target.name if target else "", count=moved,
                         names=[p.name for p in (self._profiles.get(i) for i in profile_ids[:3]) if p])
        return moved

    def _report(self, kind: str, subject: str, **data) -> None:
        if self._activity is not None:
            self._activity.record(kind, subject, **data)
        if self._log is not None:
            self._log.info("workspaces", f"{kind} {subject}".strip())
