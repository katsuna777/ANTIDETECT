"""Logs: a calm, filterable, virtualised view of what the app and the browsers reported."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListView,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui import workers
from antidetect.gui.components import Button, Card, EmptyState, PageHeader, SearchField, Segmented, Switch, label
from antidetect.gui.metrics import PAGE_MARGINS
from antidetect.gui.errors import friendly_error_text
from antidetect.gui.models.logs import LINE_ROLE, LogFilter, LogModel, format_line
from antidetect.gui.views.log_delegate import LogDelegate
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost
    from antidetect.gui.workers import TaskRunner

_POLL_MS = 1000


class LogsPage(QWidget):
    def __init__(self, container: "Container", runner: "TaskRunner", toasts: "ToastHost",
                 parent: QWidget | None = None, *, embedded: bool = False) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = runner
        self._toasts = toasts
        self._polling = False

        root = QVBoxLayout(self)
        root.setContentsMargins(PAGE_MARGINS[0], 0 if embedded else PAGE_MARGINS[1], PAGE_MARGINS[2], PAGE_MARGINS[3])
        root.setSpacing(16)
        self._header = PageHeader(tr("logs.title"))
        if embedded:
            self._header.top.setVisible(False)
        root.addWidget(self._header)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self._level = Segmented(self._level_options(), "0")
        bar.addWidget(self._level)
        self._search = SearchField(tr("logs.search"))
        self._search.setMinimumWidth(160)
        self._search.setMaximumWidth(320)
        bar.addWidget(self._search)
        bar.addStretch(1)
        self._follow_label = label(tr("logs.follow"), "muted")
        self._follow = Switch(True)
        bar.addWidget(self._follow_label)
        bar.addWidget(self._follow)
        bar.addSpacing(8)
        self._export = Button("", "soft", icon="upload")          # icon-only buttons are squares of the same size as the rest
        self._export.setToolTip(tr("logs.export"))
        self._clear = Button("", "soft", icon="trash")
        self._clear.setToolTip(tr("logs.clear"))
        bar.addWidget(self._export)
        bar.addWidget(self._clear)
        root.addLayout(bar)

        self._model = LogModel(self)
        self._filter = LogFilter(self)
        self._filter.setSourceModel(self._model)
        self._view = QListView()
        self._view.setModel(self._filter)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setUniformItemSizes(True)
        self._view.setItemDelegate(LogDelegate(self._view))
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._view.setSpacing(0)
        self._view.setStyleSheet("QListView { background: transparent; }")
        self._card = Card(padding=6)
        self._card.body.addWidget(self._view)
        self._empty = EmptyState("file-text")
        self._empty.action.setVisible(False)
        self._empty.set_content(tr("logs.empty"))
        self._stack = QStackedWidget()
        self._stack.addWidget(self._card)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        self._level.changed.connect(lambda key: self._on_filter(level=int(key)))
        self._search.textChanged.connect(lambda text: self._on_filter(text=text))
        self._export.clicked.connect(self._do_export)
        self._clear.clicked.connect(self._do_clear)
        QShortcut(QKeySequence.StandardKey.Copy, self._view, activated=self._copy_selection)
        self._model.rowsInserted.connect(self._after_insert)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state)
        self.poll()

    def _level_options(self) -> list[tuple[str, str]]:
        return [("0", tr("logs.filter.all")), ("1", tr("logs.filter.info")),
                ("2", tr("logs.filter.warn")), ("3", tr("logs.filter.error"))]

    # ------------------------------------------------------------------ data
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()
        self.poll()  # catch up on everything logged while the page was hidden

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        if self.window().isActiveWindow():  # nobody is reading while the app is in the background
            self.poll()

    def _on_app_state(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self.isVisible():
            self.poll()

    def poll(self) -> None:
        if self._polling:
            return
        self._polling = True
        self._runner.submit(
            workers.tasks.list_logs(self._container, self._model.last_id),
            on_result=self._append,
            on_error=lambda _e: None,
            on_finished=lambda: setattr(self, "_polling", False),
        )

    def _append(self, entries) -> None:
        if entries:
            self._model.append(entries)
            self._header.set_subtitle(tr("logs.subtitle", n=self._model.rowCount()))
            self._sync_state()

    def _after_insert(self, *_args) -> None:
        if self._follow.isChecked():
            self._view.scrollToBottom()

    def _on_filter(self, *, level: int | None = None, text: str | None = None) -> None:
        if level is not None:
            self._filter.set_level(level)
        if text is not None:
            self._filter.set_text(text)
        self._sync_state()
        if self._follow.isChecked():
            self._view.scrollToBottom()

    def _sync_state(self) -> None:
        self._stack.setCurrentWidget(self._card if self._filter.rowCount() else self._empty)

    def _copy_selection(self) -> None:
        rows = sorted(index.row() for index in self._view.selectionModel().selectedRows())
        lines = [format_line(self._filter.index(r, 0).data(LINE_ROLE)) for r in rows]
        if lines:
            QGuiApplication.clipboard().setText("\n".join(lines))

    def _do_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("logs.export"), "antidetect.log")
        if path:
            self._runner.submit(
                workers.tasks.export_logs(self._container, Path(path)),
                on_result=lambda p: self._toasts.show_message(tr("logs.exported", path=str(p))),
                on_error=lambda exc: self._toasts.show_message(friendly_error_text(exc), kind="error"),
            )

    def _do_clear(self) -> None:
        self._runner.submit(workers.tasks.clear_logs(self._container), on_finished=self._cleared)

    def _cleared(self) -> None:
        self._model.clear()
        self._header.set_subtitle("")
        self._sync_state()
        # Leave one row behind so the audit trail shows that (and when) it was cleared.
        self._container.logs.info("gui", "Log cleared")

    # ------------------------------------------------------------------ i18n
    def retranslate(self) -> None:
        self._header.title.setText(tr("logs.title"))
        for key, text in self._level_options():
            self._level.set_text(key, text)
        self._search.setPlaceholderText(tr("logs.search"))
        self._follow_label.setText(tr("logs.follow"))
        self._export.setToolTip(tr("logs.export"))
        self._clear.setToolTip(tr("logs.clear"))
        self._empty.set_content(tr("logs.empty"))
        if self._model.rowCount():
            self._header.set_subtitle(tr("logs.subtitle", n=self._model.rowCount()))

    def shutdown(self) -> None:
        self._timer.stop()

