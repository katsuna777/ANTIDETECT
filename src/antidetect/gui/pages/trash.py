"""Trash: the profiles that were deleted. They keep everything (cookies, fingerprint) until they are deleted for good."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QStackedWidget, QVBoxLayout, QWidget

from antidetect.gui import workers
from antidetect.gui.catalog import Catalog
from antidetect.gui.components import Button, EmptyState, SearchField, Select, StyledMenu, confirm, label
from antidetect.gui.components.bulk_bar import TrashBar
from antidetect.gui.errors import friendly_error_text
from antidetect.gui.metrics import COMPACT_HEIGHT, HEADER_HEIGHT, PAGE_MARGINS
from antidetect.gui.models import ProfileRow
from antidetect.gui.models.roles import ROW_ROLE
from antidetect.gui.models.trash import COL_ACTIONS, COL_COOKIES, COL_DELETED, COL_LEFT, COL_NAME, TrashModel
from antidetect.gui.preferences import Preferences
from antidetect.gui.views.delegates import PROFILE_ROW_HEIGHT, TrashDelegate
from antidetect.gui.views.table import DataTable
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost
    from antidetect.gui.workers import TaskRunner

_COLUMN_WIDTHS = ((COL_DELETED, 170), (COL_LEFT, 150), (COL_COOKIES, 112), (COL_ACTIONS, 100))
_NARROW = ((COL_COOKIES, 860), (COL_LEFT, 740))
_RETENTION = (7, 14, 30, 60, 90, 0)          # days; 0 = never delete by itself


class TrashPage(QWidget):
    changed = Signal()            # something came back or was deleted for good: the counters and lists must follow

    def __init__(self, container: "Container", runner: "TaskRunner", toasts: "ToastHost", catalog: Catalog,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._container = container
        self._runner = runner
        self._toasts = toasts
        self._catalog = catalog
        self._prefs = Preferences(container.settings)
        self._loading = False
        self._load_again = False
        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(14)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._title = label(tr("trash.title"), "page-title")
        self._count = QLabel("0")
        self._count.setProperty("role", "count")
        self._count.setFixedHeight(COMPACT_HEIGHT)
        bar.addWidget(self._title)
        bar.addSpacing(2)
        bar.addWidget(self._count, 0, Qt.AlignmentFlag.AlignVCenter)
        bar.addStretch(1)
        self._keep_caption = label(tr("trash.keep.caption"), "small")
        self._keep = Select()
        for days in _RETENTION:
            self._keep.addItem(tr("trash.keep.days", n=days) if days else tr("trash.keep.never"), days)
        self._keep.setMinimumWidth(130)
        self._search = SearchField(tr("profiles.search"))
        self._search.setMinimumWidth(180)
        self._search.setMaximumWidth(240)
        self._empty_button = Button(tr("trash.empty"), "danger", icon="trash")
        for widget in (self._keep_caption, self._keep, self._search, self._empty_button):
            bar.addWidget(widget)
        toolbar = QWidget()
        toolbar.setMinimumHeight(HEADER_HEIGHT)
        bar.setContentsMargins(0, 0, 0, 0)
        toolbar.setLayout(bar)
        root.addWidget(toolbar)

        self._model = TrashModel(self)
        self._view = DataTable(PROFILE_ROW_HEIGHT)
        self._view.select_by_checkbox = True
        self._view.setModel(self._model)
        self._delegate = TrashDelegate(self._view)
        self._delegate.catalog = catalog
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for column, width in _COLUMN_WIDTHS:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self._view.setColumnWidth(column, width)
        self._view.setItemDelegate(self._delegate)
        self._view.sortByColumn(COL_DELETED, Qt.SortOrder.DescendingOrder)
        self._view.hotspot = lambda index, pos: self._delegate.hotspot(index, pos, self._view)
        self._view.widthChanged.connect(self._fit_columns)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._context_menu)
        self._view.selectionModel().selectionChanged.connect(lambda *_: self._sync_bulk())
        self._delegate.restoreClicked.connect(lambda index: self.restore([index.data(ROW_ROLE)]))
        self._delegate.purgeClicked.connect(lambda index: self.purge([index.data(ROW_ROLE)]))
        self._empty = EmptyState("trash")
        self._empty.action.setVisible(False)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        self._bulk = TrashBar(self)
        self._bulk.restoreRequested.connect(lambda: self.restore(self._selected()))
        self._bulk.purgeRequested.connect(lambda: self.purge(self._selected()))
        self._bulk.clearRequested.connect(self._view.clearSelection)

        self._search.textChanged.connect(self._on_search)
        self._empty_button.clicked.connect(self.empty_trash)
        self._keep.currentIndexChanged.connect(self._retention_changed)
        self._empty_button.setEnabled(False)          # nothing to empty / search until the first list arrives
        self._search.setEnabled(False)
        self.reload()
        self._read_retention()
        self._show_state()

    # ------------------------------------------------------------------ view
    def _fit_columns(self, width: int) -> None:
        for column, below in _NARROW:
            self._view.setColumnHidden(column, width < below)

    def focus_primary(self) -> None:
        (self._view if self._stack.currentWidget() is self._view else self).setFocus(Qt.FocusReason.OtherFocusReason)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._bulk.place(self)

    # ------------------------------------------------------------------ data
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        if self._loading:
            self._load_again = True
            return
        self._loading = True
        self._runner.submit(
            workers.tasks.list_trash_rows(self._container),
            on_result=self._apply,
            on_error=lambda _exc: None,
            on_finished=self._finished,
        )

    def _finished(self) -> None:
        self._loading = False
        if self._load_again:
            self._load_again = False
            self.reload()

    def _apply(self, rows: list[ProfileRow]) -> None:
        self._model.set_rows(rows)
        self._catalog.set_trash(len(rows))
        self._count.setText(str(len(rows)))
        self._count.setVisible(bool(rows))
        self._empty_button.setEnabled(bool(rows))
        self._search.setEnabled(bool(rows))
        self._show_state()
        self._sync_bulk()

    def _show_state(self) -> None:
        if self._model.total() == 0:
            self._empty.set_content(tr("trash.empty.title"), tr("trash.empty.text", n=self._model.retention_days)
                                    if self._model.retention_days else tr("trash.empty.text.forever"))
            self._stack.setCurrentWidget(self._empty)
        elif self._model.rowCount() == 0:
            self._empty.set_content(tr("empty.filtered"))
            self._stack.setCurrentWidget(self._empty)
        else:
            self._stack.setCurrentWidget(self._view)

    def _on_search(self) -> None:
        self._model.set_text(self._search.text())
        self._show_state()

    # -------------------------------------------------------------- retention
    def _read_retention(self) -> None:
        self._runner.submit(workers.tasks.trash_retention(self._container), on_result=self._set_retention,
                            on_error=lambda _exc: None)

    def _set_retention(self, days: int) -> None:
        self._model.set_retention(days)
        self._keep.blockSignals(True)
        if not self._keep.select_data(days):
            self._keep.addItem(tr("trash.keep.days", n=days), days)
            self._keep.select_data(days)
        self._keep.blockSignals(False)
        self._show_state()

    def _retention_changed(self) -> None:
        days = self._keep.currentData()
        if days is None:
            return
        self._runner.submit(workers.tasks.trash_retention(self._container, days), on_result=self._set_retention,
                            on_error=self._fail)

    # --------------------------------------------------------------- selection
    def _selected(self) -> list[ProfileRow]:
        return [row for index in self._view.selectionModel().selectedRows()
                if (row := index.data(ROW_ROLE)) is not None]

    def _sync_bulk(self) -> None:
        count = len(self._view.selectionModel().selectedRows())
        self._bulk.set_count(count)
        self._bulk.setVisible(count > 1)
        if count > 1:
            self._bulk.place(self)
        self._view.viewport().update()

    def _context_menu(self, position) -> None:
        index = self._view.indexAt(position)
        if not index.isValid():
            return
        rows = self._selected() if self._view.selectionModel().isSelected(index) else [index.data(ROW_ROLE)]
        menu = StyledMenu(self)
        if len(rows) > 1:
            menu.caption(tr("menu.selected", n=len(rows)))
            menu.addSeparator()
        menu.item(tr("trash.restore"), lambda: self.restore(rows), icon="rotate-ccw")
        menu.addSeparator()
        menu.item(tr("trash.purge"), lambda: self.purge(rows), icon="trash", danger=True)
        menu.exec(self._view.viewport().mapToGlobal(position))

    # ----------------------------------------------------------------- actions
    def _fail(self, exc: object) -> None:
        self._toasts.show_message(friendly_error_text(exc), kind="error")

    def restore(self, rows: list[ProfileRow]) -> None:
        if not rows:
            return
        self._runner.submit(
            workers.tasks.restore_profiles(self._container, [r.id for r in rows]),
            on_result=lambda names: self._toasts.show_message(tr("toast.restored", name=", ".join(names[:2]))),
            on_error=self._fail,
            on_finished=self._after_change,
        )

    def purge(self, rows: list[ProfileRow]) -> None:
        """Delete for good: the folder with the profile's cookies and history goes too."""
        if not rows:
            return
        if self._prefs.get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, default=True):
            if len(rows) == 1:
                title, text = tr("confirm.purge.title", name=rows[0].name), tr("confirm.purge.text")
            else:
                title, text = tr("confirm.purge.many.title", n=len(rows)), tr("confirm.purge.text")
            if not confirm(self.window(), title, text, tr("trash.purge"), danger=True):
                return
        self._runner.submit(
            workers.tasks.purge_profiles(self._container, [r.id for r in rows]),
            on_result=lambda n: self._toasts.show_message(tr("toast.purged", n=n)),
            on_error=self._fail,
            on_finished=self._after_change,
        )

    def empty_trash(self) -> None:
        total = self._model.total()
        if not total:
            return
        if not confirm(self.window(), tr("confirm.empty.title"), tr("confirm.empty.text", n=total),
                       tr("trash.empty"), danger=True):
            return
        self._runner.submit(
            workers.tasks.empty_trash(self._container),
            on_result=lambda n: self._toasts.show_message(tr("toast.purged", n=n)),
            on_error=self._fail,
            on_finished=self._after_change,
        )

    def _after_change(self) -> None:
        self.reload()
        self.changed.emit()

    # -------------------------------------------------------------------- i18n
    def retranslate(self) -> None:
        self._title.setText(tr("trash.title"))
        self._keep_caption.setText(tr("trash.keep.caption"))
        for index in range(self._keep.count()):
            days = self._keep.itemData(index)
            self._keep.setItemText(index, tr("trash.keep.days", n=days) if days else tr("trash.keep.never"))
        self._search.setPlaceholderText(tr("profiles.search"))
        self._empty_button.setText(tr("trash.empty"))
        self._bulk.retranslate()
        self._model.retranslate()
        self._show_state()
