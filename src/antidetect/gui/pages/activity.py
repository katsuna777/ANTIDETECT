"""Activity: what happened in the app (profiles started, tags changed, proxies checked...), newest first."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QListView,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui import workers
from antidetect.gui.catalog import Catalog
from antidetect.gui.components import Button, EmptyState, PageHeader, SearchField, Segmented, confirm
from antidetect.gui.errors import friendly_error_text
from antidetect.gui.metrics import PAGE_MARGINS
from antidetect.gui.models.activity import ActivityModel
from antidetect.gui.preferences import Preferences
from antidetect.gui.views.activity_delegate import ActivityDelegate
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost
    from antidetect.gui.workers import TaskRunner

PAGE = 200
_POLL_MS = 3000
_FILTERS = (("all", "act.filter.all"), ("profiles", "act.filter.profiles"), ("proxies", "act.filter.proxies"),
            ("organize", "act.filter.organize"), ("errors", "act.filter.errors"))


class ActivityPage(QWidget):
    def __init__(self, container: "Container", runner: "TaskRunner", toasts: "ToastHost", catalog: Catalog,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = runner
        self._toasts = toasts
        self._catalog = catalog
        self._prefs = Preferences(container.settings)
        self._loading = False
        self._polling = False
        self._more = False                       # older entries exist than the ones loaded
        self._filter = "all"
        self._generation = 0                     # answers for an older filter are dropped

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(14)
        self._header = PageHeader(tr("activity.title"))
        root.addWidget(self._header)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self._segmented = Segmented([(key, tr(text)) for key, text in _FILTERS], "all")
        self._search = SearchField(tr("activity.search"))
        self._search.setMinimumWidth(160)
        self._search.setMaximumWidth(280)
        self._clear = Button("", "soft", icon="trash")
        self._clear.setToolTip(tr("activity.clear"))
        bar.addWidget(self._segmented)
        bar.addWidget(self._search)
        bar.addStretch(1)
        bar.addWidget(self._clear)
        root.addLayout(bar)

        self._model = ActivityModel(self)
        self._list = QListView()
        self._list.setModel(self._model)
        self._list.setItemDelegate(ActivityDelegate(self._list))
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setMouseTracking(True)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.verticalScrollBar().setSingleStep(24)
        self._list.verticalScrollBar().valueChanged.connect(self._maybe_load_older)
        self._empty = EmptyState("activity")
        self._empty.action.setVisible(False)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._list)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        self._segmented.changed.connect(self._on_filter)
        self._search.textChanged.connect(self._on_search)
        self._clear.clicked.connect(self._clear_all)
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state)
        self._load()
        self._sync_state()

    # -------------------------------------------------------------------- data
    def _query(self) -> dict:
        return {"group": None if self._filter in ("all", "errors") else self._filter,
                "errors_only": self._filter == "errors"}

    def _load(self) -> None:
        """Read the newest entries for the current filter."""
        self._generation += 1
        generation = self._generation
        self._runner.submit(
            workers.tasks.list_activity(self._container, limit=PAGE, **self._query()),
            on_result=lambda entries, g=generation: self._loaded(entries, g),
            on_error=lambda _exc: None,
        )

    def _loaded(self, entries, generation: int) -> None:
        if generation != self._generation:
            return
        self._model.set_entries(entries)
        self._more = len(entries) >= PAGE
        self._sync_state()

    def _poll(self) -> None:
        if self._polling or not self.window().isActiveWindow():
            return
        self._polling = True
        generation = self._generation
        self._runner.submit(
            workers.tasks.list_activity(self._container, after_id=self._model.newest_id(), limit=PAGE, **self._query()),
            on_result=lambda entries, g=generation: self._fresh(entries, g),
            on_error=lambda _exc: None,
            on_finished=lambda: setattr(self, "_polling", False),
        )

    def _fresh(self, entries, generation: int) -> None:
        if generation == self._generation and entries:
            self._model.prepend(entries)
            self._sync_state()
            self._mark_seen()

    def _maybe_load_older(self, value: int) -> None:
        bar = self._list.verticalScrollBar()
        if self._more and not self._loading and value >= bar.maximum() - 200:
            oldest = self._model.oldest_id()
            if oldest is None:
                return
            self._loading = True
            generation = self._generation
            self._runner.submit(
                workers.tasks.list_activity(self._container, before_id=oldest, limit=PAGE, **self._query()),
                on_result=lambda entries, g=generation: self._older(entries, g),
                on_error=lambda _exc: None,
                on_finished=lambda: setattr(self, "_loading", False),
            )

    def _older(self, entries, generation: int) -> None:
        if generation != self._generation:
            return
        self._more = len(entries) >= PAGE
        self._model.append(entries)

    def _on_filter(self, key: str) -> None:
        self._filter = key
        self._load()

    def _on_search(self, text: str) -> None:
        self._model.set_text(text)
        self._sync_state()

    def _sync_state(self) -> None:
        shown = self._model.rowCount()
        has_any = bool(self._model.entries())
        if shown:
            self._stack.setCurrentWidget(self._list)
        else:
            if has_any:                                   # entries exist, the search hides them all
                self._empty.set_content(tr("empty.filtered"))
            else:
                self._empty.set_content(tr("activity.empty.title"), tr("activity.empty.text"))
            self._stack.setCurrentWidget(self._empty)
        self._clear.setEnabled(has_any)

    def _clear_all(self) -> None:
        if not confirm(self.window(), tr("activity.clear.title"), tr("activity.clear.text"), tr("activity.clear"),
                       danger=True):
            return
        self._runner.submit(
            workers.tasks.clear_activity(self._container),
            on_result=lambda _n: self._load(),
            on_error=lambda exc: self._toasts.show_message(friendly_error_text(exc), kind="error"),
        )

    # ------------------------------------------------------------------ lifecycle
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()
        self._mark_seen()
        self._poll()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _on_app_state(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self.isVisible():
            self._poll()
            self._mark_seen()

    def _mark_seen(self) -> None:
        """Everything on screen counts as read: the badge in the sidebar goes."""
        self._runner.submit(workers.tasks.mark_activity_seen(self._container), on_error=lambda _exc: None)
        self._catalog.set_unseen(0)

    def shutdown(self) -> None:
        self._timer.stop()

    # -------------------------------------------------------------------- i18n
    def retranslate(self) -> None:
        self._header.title.setText(tr("activity.title"))
        for key, text in _FILTERS:
            self._segmented.set_text(key, tr(text))
        self._search.setPlaceholderText(tr("activity.search"))
        self._clear.setToolTip(tr("activity.clear"))
        self._model.retranslate()
        self._sync_state()
