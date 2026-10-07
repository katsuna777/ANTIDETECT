"""Proxies: the user's own proxy list — add, check, delete — plus a free list."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLabel, QProgressBar, QStackedWidget, QVBoxLayout, QWidget

from antidetect.gui import workers
from antidetect.gui.components import (
    Button,
    EmptyState,
    FreeProxyNotice,
    SearchField,
    StyledMenu,
    label,
)
from antidetect.gui.metrics import COMPACT_HEIGHT, HEADER_HEIGHT, PAGE_MARGINS
from antidetect.gui.dialogs.proxy_import import ProxyImportDialog
from antidetect.gui.errors import friendly_error_text, show_error
from antidetect.gui.models import ProxyRow
from antidetect.gui.models.proxies import (
    COL_ADDRESS,
    COL_ANON,
    COL_COUNTRY,
    COL_PING,
    COL_SOURCE,
    COL_STATUS,
    COL_USED,
    ProxiesModel,
)
from antidetect.gui.models.roles import ROW_ROLE
from antidetect.gui.workers.tasks import ProxyListing
from antidetect.gui.views.delegates import PROXY_ROW_HEIGHT, ProxyDelegate
from antidetect.gui.views.table import DataTable
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost
    from antidetect.gui.workers import TaskRunner

_COLUMN_WIDTHS = ((COL_COUNTRY, 160), (COL_PING, 90), (COL_STATUS, 150), (COL_ANON, 120), (COL_SOURCE, 120), (COL_USED, 170))
_LIVE_RELOAD_S = 4.0   # while free proxies are being verified, show the ones that passed this often


class ProxiesPage(QWidget):
    countChanged = Signal(int)    # how many proxies are stored (sidebar counter)

    def __init__(self, container: "Container", runner: "TaskRunner", toasts: "ToastHost",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = runner
        self._toasts = toasts
        self._busy = False
        self._live = False            # a free-list run is going: refresh the table as proxies pass
        self._reloading = False
        self._reload_again = False
        self._last_reload = 0.0
        self._stop_event: threading.Event | None = None
        self._stopping = False        # Stop was pressed: the run is winding down
        self._listing = ProxyListing([], 0, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(14)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.setContentsMargins(0, 0, 0, 0)
        self._title = label(tr("proxies.title"), "page-title")
        self._count = QLabel("0")
        self._count.setProperty("role", "count")
        self._count.setFixedHeight(COMPACT_HEIGHT)
        self._working = QLabel("")
        self._working.setProperty("role", "count")
        self._working.setProperty("tone", "success")
        self._working.setFixedHeight(COMPACT_HEIGHT)
        bar.addWidget(self._title)
        bar.addSpacing(2)
        bar.addWidget(self._count, 0, Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self._working, 0, Qt.AlignmentFlag.AlignVCenter)
        bar.addStretch(1)
        self._search = SearchField(tr("proxies.search"))
        self._search.setMinimumWidth(190)
        self._search.setMaximumWidth(260)
        bar.addWidget(self._search)
        self._delete = Button(tr("bulk.delete"), "danger", icon="trash")
        self._delete.setVisible(False)
        self._delete.clicked.connect(lambda: self.delete_rows(self._selected()))
        bar.addWidget(self._delete)
        self._check_all = Button(tr("proxies.check"), "soft", icon="refresh")
        self._check_all.clicked.connect(self.check_all)
        bar.addWidget(self._check_all)
        self._free = Button(tr("proxies.free"), "soft", icon="download")
        self._free.setToolTip(tr("proxies.free.tip"))
        self._free.clicked.connect(self.collect_free)
        bar.addWidget(self._free)
        self._add = Button(tr("proxies.add"), "primary", icon="plus")
        self._add.clicked.connect(self.add_proxies)
        bar.addWidget(self._add)
        self._toolbar = QWidget()
        self._toolbar.setMinimumHeight(HEADER_HEIGHT)
        self._toolbar.setLayout(bar)
        root.addWidget(self._toolbar)

        self._free_notice = FreeProxyNotice()
        self._free_notice.setVisible(False)
        root.addWidget(self._free_notice)

        self._status_bar = QWidget()
        self._status_bar.setVisible(False)
        status = QHBoxLayout(self._status_bar)
        status.setContentsMargins(2, 0, 2, 0)
        status.setSpacing(12)
        self._status = label("", "small")
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._stop = Button(tr("action.stop"), "link")
        self._stop.setVisible(False)
        self._stop.clicked.connect(self._request_stop)
        status.addWidget(self._status)
        status.addWidget(self._progress, 1)
        status.addWidget(self._stop)
        root.addWidget(self._status_bar)

        self._model = ProxiesModel(self)
        self._filter = self._model     # the model filters and sorts itself
        self._view = DataTable(PROXY_ROW_HEIGHT)
        self._view.setModel(self._model)
        self._view.setItemDelegate(ProxyDelegate(self._view))
        self._configure_view()
        self._empty = EmptyState("globe")
        self._empty.action.clicked.connect(self.add_proxies)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        self._search.textChanged.connect(self._on_search)
        QShortcut(QKeySequence("Delete"), self._view, activated=lambda: self.delete_rows(self._selected()))
        self.reload()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_compact()

    def _apply_compact(self) -> None:
        """Narrow windows keep the check / free-list buttons as bare icons."""
        compact = self.width() < 1120
        for button, key in ((self._check_all, "proxies.check"), (self._free, "proxies.free")):
            button.setText("" if compact else tr(key))
            button.setToolTip(tr(key) if compact else (tr("proxies.free.tip") if button is self._free else ""))

    def _configure_view(self) -> None:
        view = self._view
        header = view.horizontalHeader()
        header.setSectionResizeMode(COL_ADDRESS, QHeaderView.ResizeMode.Stretch)
        for column, width in _COLUMN_WIDTHS:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            view.setColumnWidth(column, width)
        view.widthChanged.connect(self._fit_columns)
        view.sortByColumn(COL_ADDRESS, Qt.SortOrder.AscendingOrder)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._context_menu)
        view.selectionModel().selectionChanged.connect(lambda *_: self._delete.setVisible(bool(self._selected())))

    def _fit_columns(self, width: int) -> None:
        # The address is what matters: give up the side columns before squeezing it.
        self._view.setColumnHidden(COL_USED, width < 1100)
        self._view.setColumnHidden(COL_SOURCE, width < 960)
        self._view.setColumnHidden(COL_ANON, width < 820)

    # ------------------------------------------------------------------ data
    def reload(self) -> None:
        """Re-read the table. A request made while one is in flight runs right after it."""
        if self._reloading:
            self._reload_again = True
            return
        self._reloading = True
        self._last_reload = time.monotonic()
        self._runner.submit(
            workers.tasks.list_proxy_rows(self._container),
            on_result=self._apply_rows,
            on_error=self._fail,
            on_finished=self._reload_finished,
        )

    def _reload_finished(self) -> None:
        self._reloading = False
        if self._reload_again:
            self._reload_again = False
            self.reload()

    def _apply_rows(self, listing: ProxyListing) -> None:
        self._listing = listing
        self._model.set_rows(listing.rows)
        self._count.setText(str(listing.total))
        self._count.setVisible(listing.total > 0)
        self._working.setText(tr("proxies.working", n=listing.working))
        self._working.setVisible(listing.working > 0)
        self._search.setEnabled(listing.total > 0)
        self._check_all.setEnabled(listing.total > 0 and not self._busy)
        self._sync_free_notice()
        self._show_state()
        self.countChanged.emit(listing.total)

    def _sync_free_notice(self) -> None:
        """Warn while free proxies are being collected and as long as any are in the table."""
        self._free_notice.setVisible(self._live or any(not row.is_manual for row in self._listing.rows))

    def _show_state(self) -> None:
        if self._listing.total == 0:
            self._empty.set_content(tr("proxies.empty.title"), tr("proxies.empty.text"), tr("proxies.add"))
            self._stack.setCurrentWidget(self._empty)
        elif self._model.rowCount() == 0:
            self._empty.set_content(tr("empty.filtered"))
            self._stack.setCurrentWidget(self._empty)
        else:
            self._stack.setCurrentWidget(self._view)

    def _on_search(self, text: str) -> None:
        self._model.set_text(text)
        if self._model.total():
            self._show_state()

    def _selected(self) -> list[ProxyRow]:
        rows = []
        for index in self._view.selectionModel().selectedRows():
            row = index.data(ROW_ROLE)
            if row is not None:
                rows.append(row)
        return rows

    def _fail(self, exc: object) -> None:
        self._toasts.show_message(
            friendly_error_text(exc), kind="error",
            action=(tr("common.details"), lambda e=exc: show_error(self.window(), e)),
        )

    # ------------------------------------------------------------------ progress
    def _begin(self, text: str, can_stop: bool = False) -> None:
        self._busy = True
        for widget in (self._add, self._check_all, self._free):
            widget.setEnabled(False)
        self._progress.setRange(0, 0)
        self._status_bar.setVisible(True)
        self._status.setText(text)
        self._stop.setEnabled(True)
        self._stop.setVisible(can_stop)

    def _progress_update(self, done: int, total: int) -> None:
        if total > 0 and not self._stopping:
            self._progress.setRange(0, total)
            self._progress.setValue(done)
            self._status.setText(tr("proxies.checking", done=done, total=total))
            if self._live and time.monotonic() - self._last_reload >= _LIVE_RELOAD_S:
                self.reload()

    def _end(self, message: str = "") -> None:
        self._busy = False
        self._live = False
        self._stopping = False
        for widget in (self._add, self._check_all, self._free):
            widget.setEnabled(True)
        self._stop.setVisible(False)
        self._status_bar.setVisible(False)
        self._model.set_busy(set())
        self._stop_event = None
        self.reload()

    def _request_stop(self) -> None:
        if self._stop_event is None or self._stop_event.is_set():
            return
        self._stop_event.set()
        # The button answers at once; the run itself winds down in well under a second.
        self._stopping = True
        self._stop.setEnabled(False)
        self._progress.setRange(0, 0)
        self._status.setText(tr("proxies.stopping"))

    # ------------------------------------------------------------------ actions
    def add_proxies(self) -> None:
        dialog = ProxyImportDialog(self.window())
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._begin("")
        self._runner.submit(
            workers.tasks.import_proxies(self._container, dialog.text(), dialog.protocol(), dialog.check_after()),
            on_result=lambda s: self._toasts.show_message(tr("toast.proxies.added", added=s.added, existing=s.existing)),
            on_progress=self._progress_update,
            on_error=self._fail,
            on_finished=self._end,
        )

    def check_all(self) -> None:
        self.check_rows(self._model.rows())

    def check_rows(self, rows: list[ProxyRow]) -> None:
        if not rows or self._busy:
            return
        self._stop_event = threading.Event()
        self._begin(tr("proxies.checking", done=0, total=len(rows)), can_stop=True)
        self._model.set_busy({r.id for r in rows})
        self._runner.submit(
            workers.tasks.check_proxies(self._container, [r.id for r in rows], stop_event=self._stop_event),
            on_progress=self._progress_update,
            on_error=self._fail,
            on_finished=self._end,
        )

    def collect_free(self) -> None:
        self._stop_event = threading.Event()
        self._begin(tr("proxies.collecting"), can_stop=True)
        self._live = True
        self._sync_free_notice()
        self._runner.submit(
            workers.tasks.refresh_free_proxies(self._container, stop_event=self._stop_event),
            on_result=lambda s: self._toasts.show_message(tr("proxies.done", working=s.working, checked=s.checked)),
            on_progress=self._progress_update,
            on_error=self._fail,
            on_finished=self._end,
        )

    def delete_rows(self, rows: list[ProxyRow]) -> None:
        if not rows:
            return
        self._runner.submit(
            workers.tasks.delete_proxies(self._container, [r.id for r in rows]),
            on_error=self._fail,
            on_finished=self.reload,
        )

    def copy_address(self, row: ProxyRow) -> None:
        QGuiApplication.clipboard().setText(row.address)
        self._toasts.show_message(tr("toast.copied"), timeout_ms=1500)

    def _context_menu(self, position) -> None:
        index = self._view.indexAt(position)
        if index.isValid() and not self._view.selectionModel().isSelected(index):
            self._view.selectRow(index.row())
        rows = self._selected()
        if not rows:
            return
        menu = StyledMenu(self)
        menu.item(tr("proxy.menu.check"), lambda: self.check_rows(rows), icon="refresh")
        if len(rows) == 1:
            menu.item(tr("proxy.menu.copy"), lambda: self.copy_address(rows[0]), icon="copy")
        menu.addSeparator()
        menu.item(tr("proxy.menu.delete"), lambda: self.delete_rows(rows), icon="trash", danger=True)
        menu.exec(self._view.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------ i18n
    def retranslate(self) -> None:
        self._title.setText(tr("proxies.title"))
        self._free_notice.retranslate()
        self._add.setText(tr("proxies.add"))
        self._apply_compact()
        self._search.setPlaceholderText(tr("proxies.search"))
        self._delete.setText(tr("bulk.delete"))
        self._stop.setText(tr("action.stop"))
        self._model.retranslate()
        self._apply_rows(self._listing)

    def shutdown(self) -> None:
        self._request_stop()
