"""What the window knows about tags, workspaces, the trash and the feed — kept in one place.

The sidebar, the table, the pickers and the dialogs all read from here (never from the database
while painting). ``refresh()`` reloads it on a worker thread; every change made through this object
refreshes it by itself and says ``profilesAffected`` when the table has to be read again too (a tag
rename rewrites the profiles that carry it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, Signal

from antidetect.gui import workers
from antidetect.gui.theme import tags as tag_colors

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.workers import TaskRunner


@dataclass(frozen=True)
class TagItem:
    id: int
    name: str
    color: int
    count: int


@dataclass(frozen=True)
class WorkspaceItem:
    id: int
    name: str
    color: int
    count: int


class Catalog(QObject):
    changed = Signal()               # tags / workspaces / counters changed: repaint whoever shows them
    profilesAffected = Signal()      # profile rows changed too (tag rename, workspace delete...): reload the table

    def __init__(self, container: "Container", runner: "TaskRunner", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = runner
        self.tags: list[TagItem] = []
        self.workspaces: list[WorkspaceItem] = []
        self.unassigned = 0
        self.trash = 0
        self.unseen = 0
        self.unseen_errors = 0
        self.loaded = False              # True once the first answer has arrived
        self._loading = False
        self._again = False

    # ----------------------------------------------------------------- reads
    def tag(self, name: str) -> TagItem | None:
        key = (name or "").strip().casefold()
        return next((t for t in self.tags if t.name.casefold() == key), None)

    def workspace(self, workspace_id: int | None) -> WorkspaceItem | None:
        return next((w for w in self.workspaces if w.id == workspace_id), None) if workspace_id is not None else None

    def workspace_named(self, name: str) -> WorkspaceItem | None:
        key = (name or "").strip().casefold()
        return next((w for w in self.workspaces if w.name.casefold() == key), None)

    def tag_names(self) -> list[str]:
        return [t.name for t in self.tags]

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Reload on a worker; a request made while one runs is served right after it."""
        if self._loading:
            self._again = True
            return
        self._loading = True
        self._runner.submit(
            workers.tasks.load_catalog(self._container),
            on_result=self._apply,
            on_error=lambda _exc: None,
            on_finished=self._finished,
        )

    def _finished(self) -> None:
        self._loading = False
        if self._again:
            self._again = False
            self.refresh()

    def _apply(self, snapshot) -> None:
        tags = [TagItem(*row) for row in snapshot.tags]
        workspaces = [WorkspaceItem(*row) for row in snapshot.workspaces]
        first = not self.loaded
        self.loaded = True
        same = (tags == self.tags and workspaces == self.workspaces and snapshot.unassigned == self.unassigned
                and snapshot.trash == self.trash and snapshot.unseen == self.unseen
                and snapshot.unseen_errors == self.unseen_errors)
        self.tags, self.workspaces = tags, workspaces
        self.unassigned, self.trash, self.unseen = snapshot.unassigned, snapshot.trash, snapshot.unseen
        self.unseen_errors = snapshot.unseen_errors
        tag_colors.register((t.name, t.color) for t in tags)
        if not same or first:
            self.changed.emit()

    def set_trash(self, count: int) -> None:
        if count != self.trash:
            self.trash = count
            self.changed.emit()

    def set_unseen(self, count: int) -> None:
        if count != self.unseen or (count == 0 and self.unseen_errors):
            self.unseen = count
            if count == 0:
                self.unseen_errors = 0
            self.changed.emit()

    # ------------------------------------------------------------- mutations
    def _run(self, task, *, on_result: Callable | None = None, on_error: Callable | None = None,
             rows: bool = False) -> None:
        def done(result) -> None:
            self.refresh()
            if rows:
                self.profilesAffected.emit()
            if on_result is not None:
                on_result(result)

        def failed(exc) -> None:
            self.refresh()
            if on_error is not None:
                on_error(exc)

        self._runner.submit(task, on_result=done, on_error=failed)

    def create_tag(self, name: str, color: int | None = None, *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.create_tag(self._container, name, color), on_result=on_result, on_error=on_error)

    def rename_tag(self, tag_id: int, name: str, *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.rename_tag(self._container, tag_id, name), on_result=on_result, on_error=on_error,
                  rows=True)

    def recolor_tag(self, tag_id: int, color: int, *, on_error=None) -> None:
        # the table paints from the registry: show the new colour before the worker has answered
        tag = next((t for t in self.tags if t.id == tag_id), None)
        if tag is not None:
            self.tags = [TagItem(t.id, t.name, color, t.count) if t.id == tag_id else t for t in self.tags]
            tag_colors.register((t.name, t.color) for t in self.tags)
            self.changed.emit()
        self._run(workers.tasks.recolor_tag(self._container, tag_id, color), on_error=on_error)

    def delete_tag(self, tag_id: int, *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.delete_tag(self._container, tag_id), on_result=on_result, on_error=on_error, rows=True)

    def assign_tags(self, ids: list[int], add: list[str], remove: list[str], *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.assign_tags(self._container, ids, add, remove), on_result=on_result,
                  on_error=on_error, rows=True)

    def create_workspace(self, name: str, color: int | None = None, *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.create_workspace(self._container, name, color), on_result=on_result,
                  on_error=on_error)

    def rename_workspace(self, workspace_id: int, name: str, *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.rename_workspace(self._container, workspace_id, name), on_result=on_result,
                  on_error=on_error)

    def recolor_workspace(self, workspace_id: int, color: int, *, on_error=None) -> None:
        self.workspaces = [WorkspaceItem(w.id, w.name, color, w.count) if w.id == workspace_id else w
                           for w in self.workspaces]
        self.changed.emit()
        self._run(workers.tasks.recolor_workspace(self._container, workspace_id, color), on_error=on_error)

    def delete_workspace(self, workspace_id: int, *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.delete_workspace(self._container, workspace_id), on_result=on_result,
                  on_error=on_error, rows=True)

    def move_profiles(self, ids: list[int], workspace_id: int | None, *, on_result=None, on_error=None) -> None:
        self._run(workers.tasks.move_profiles(self._container, ids, workspace_id), on_result=on_result,
                  on_error=on_error, rows=True)
