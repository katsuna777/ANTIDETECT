"""Check: open a profile on independent fingerprint checkers and see what websites see."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui import workers
from antidetect.gui.components import (
    Button,
    Callout,
    Card,
    EmptyState,
    FreeProxyNotice,
    IconLabel,
    PageHeader,
    Select,
    label,
)
from antidetect.gui.metrics import PAGE_MARGINS
from antidetect.gui.errors import friendly_error_text, show_error
from antidetect.gui.models import ProfileRow
from antidetect.gui.pages.profiles import CHECK_SITES
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost
    from antidetect.gui.workers import TaskRunner

_COLUMNS = 2


class _SiteCard(Card):
    def __init__(self, key: str, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, padding=20, spacing=4)
        self.key, self.url = key, url
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconLabel("shield-check", "accent", 20))
        self._name = label("", "h2")
        head.addWidget(self._name, 1)
        self.body.addLayout(head)
        self._desc = label("", "muted", wrap=True)
        self.body.addSpacing(4)
        self.body.addWidget(self._desc)
        self.body.addSpacing(14)
        self.button = Button("", None, icon="external")
        row = QHBoxLayout()
        row.addWidget(self.button)
        row.addStretch(1)
        self.body.addLayout(row)
        self.retranslate()

    def retranslate(self) -> None:
        self._name.setText(tr(f"check.site.{self.key}"))
        self._desc.setText(tr(f"check.desc.{self.key}"))
        self.button.setText(tr("check.open"))


class CheckPage(QWidget):
    profilesChanged = Signal()

    def __init__(self, container: "Container", runner: "TaskRunner", toasts: "ToastHost",
                 parent: QWidget | None = None, *, embedded: bool = False) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = runner
        self._toasts = toasts
        self._rows: list[ProfileRow] = []
        self._shown: list[tuple[str, int]] = []      # what the profile picker lists now

        root = QVBoxLayout(self)
        # inside Settings the page has no title of its own: the tabs above are its header
        root.setContentsMargins(PAGE_MARGINS[0], 0 if embedded else PAGE_MARGINS[1], PAGE_MARGINS[2], PAGE_MARGINS[3])
        root.setSpacing(16)
        self._header = PageHeader(tr("check.title"), tr("check.subtitle"))
        if embedded:
            self._header.top.setVisible(False)
        root.addWidget(self._header)

        self._content = QWidget()
        col = QVBoxLayout(self._content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)
        picker = QHBoxLayout()
        picker.setSpacing(12)
        self._profile_caption = label(tr("check.profile"), "field")
        self._profiles = Select()
        self._profiles.setMinimumWidth(280)
        self._profiles.fit_to_width(30)              # there can be thousands of profiles in the list
        picker.addWidget(self._profile_caption)
        picker.addWidget(self._profiles)
        picker.addStretch(1)
        col.addLayout(picker)
        self._free_notice = FreeProxyNotice()
        self._free_notice.setVisible(False)
        col.addWidget(self._free_notice)
        # The cards scroll when the window is short; the picker and the warning stay in view.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner_col = QVBoxLayout(inner)
        inner_col.setContentsMargins(0, 0, 0, 0)
        inner_col.setSpacing(16)
        scroll.setWidget(inner)
        col.addWidget(scroll, 1)
        self._hint = Callout("accent", "info")
        self._hint.set_content(tr("check.hint"))
        inner_col.addWidget(self._hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self._profiles.currentIndexChanged.connect(self._sync_free_notice)
        self._cards: list[_SiteCard] = []
        for position, (key, url) in enumerate(CHECK_SITES):
            card = _SiteCard(key, url)
            card.button.clicked.connect(lambda _=False, c=card: self._open(c.url))
            grid.addWidget(card, position // _COLUMNS, position % _COLUMNS)
            self._cards.append(card)
        for column in range(_COLUMNS):
            grid.setColumnStretch(column, 1)
        inner_col.addLayout(grid)
        inner_col.addStretch(1)

        self._empty = EmptyState("shield-check")
        self._empty.set_content(tr("check.none.title"), tr("check.none.text"))
        self._stack = QStackedWidget()
        self._stack.addWidget(self._content)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)
        self.reload()

    # ------------------------------------------------------------------ data
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        self._runner.submit(
            workers.tasks.list_profile_rows(self._container),
            on_result=self._apply_rows,
            on_error=lambda _exc: None,
        )

    def _apply_rows(self, rows: list[ProfileRow]) -> None:
        self._rows = list(rows)
        ordered = sorted(rows, key=lambda r: r.name.casefold())
        shown = [(row.name, row.id) for row in ordered]
        if shown != self._shown:                     # every visit asks again; refilling a long list is not free
            self._shown = shown
            current = self._profiles.currentData()
            self._profiles.blockSignals(True)
            self._profiles.clear()
            for name, profile_id in shown:
                self._profiles.addItem(name, profile_id)
            if not self._profiles.select_data(current):
                self._profiles.setCurrentIndex(0)
            self._profiles.blockSignals(False)
        self._stack.setCurrentWidget(self._content if rows else self._empty)
        self._sync_free_notice()

    def _sync_free_notice(self) -> None:
        """Checks run through the profile's proxy: say so when that is a free one."""
        row = self.selected_row()
        self._free_notice.setVisible(row is not None and row.proxy_free)

    def selected_row(self) -> ProfileRow | None:
        profile_id = self._profiles.currentData()
        return next((r for r in self._rows if r.id == profile_id), None)

    # --------------------------------------------------------------- actions
    def _open(self, url: str) -> None:
        row = self.selected_row()
        if row is None:
            return
        self._runner.submit(
            workers.tasks.open_url(self._container, row.id, url),
            on_error=self._fail,
            on_finished=self.profilesChanged.emit,
        )

    def _fail(self, exc: object) -> None:
        self._toasts.show_message(
            friendly_error_text(exc), kind="error",
            action=(tr("common.details"), lambda e=exc: show_error(self.window(), e)),
        )

    # ------------------------------------------------------------------ i18n
    def retranslate(self) -> None:
        self._header.set_texts(tr("check.title"), tr("check.subtitle"))
        self._profile_caption.setText(tr("check.profile"))
        self._hint.set_content(tr("check.hint"))
        self._free_notice.retranslate()
        self._empty.set_content(tr("check.none.title"), tr("check.none.text"))
        for card in self._cards:
            card.retranslate()
