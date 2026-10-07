"""The profiles filter: status, system, proxy and tag, one card, applied as you click."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from antidetect.gui.components.basics import Button, label
from antidetect.gui.components.fields import Segmented
from antidetect.gui.components.flow import FlowLayout
from antidetect.gui.components.popover import Popover
from antidetect.gui.models.profiles import OS_NAMES
from antidetect.i18n import tr


@dataclass(frozen=True)
class FilterState:
    """What the popover lets you narrow the list by (the workspace and the search box live elsewhere)."""

    state: str | None = None                  # "running" | "stopped"
    platforms: frozenset = frozenset()
    proxy: str | None = None                  # "with" | "without"
    cookies: str | None = None                # "with" | "without"
    created: str | None = None                # "today" | "week" | "month"
    tag: str | None = None


class _Chips(QWidget):
    """Toggle chips; ``exclusive`` = at most one on (tags), otherwise any number (systems)."""

    changed = Signal()

    def __init__(self, options: list[tuple[str, str]], selected, *, exclusive: bool = False) -> None:
        super().__init__()
        row = FlowLayout(self, spacing=6)
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)
        self._exclusive = exclusive
        for key, text in options:
            button = QPushButton(text)
            button.setProperty("variant", "chip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setChecked(key in selected)
            button.clicked.connect(lambda _=False, k=key: self._clicked(k))
            self._group.addButton(button)
            self._buttons[key] = button
            row.addWidget(button)

    def _clicked(self, key: str) -> None:
        if self._exclusive and self._buttons[key].isChecked():
            for other, button in self._buttons.items():
                if other != key:
                    button.setChecked(False)
        self.changed.emit()

    def value(self) -> frozenset[str]:
        return frozenset(k for k, b in self._buttons.items() if b.isChecked())

    def clear(self) -> None:
        for button in self._buttons.values():
            button.setChecked(False)


class FilterPopover(Popover):
    """Emits ``changed(FilterState)`` after every click."""

    changed = Signal(object)

    def __init__(self, parent: QWidget | None, *, current: FilterState, tags: dict[str, int]) -> None:
        super().__init__(parent, width=360)
        self.body.setSpacing(12)

        self.body.addWidget(label(tr("filter.status"), "section"))
        self._state = Segmented([("all", tr("profiles.filter.all")), ("running", tr("profiles.filter.running")),
                                 ("stopped", tr("profiles.filter.stopped"))], current.state or "all")
        self.body.addWidget(self._state)

        self.body.addWidget(label(tr("filter.system"), "section"))
        self._platforms = _Chips([(key, name) for key, name in OS_NAMES.items()], set(current.platforms))
        self.body.addWidget(self._platforms)

        self.body.addWidget(label(tr("filter.proxy"), "section"))
        self._proxy = Segmented([("any", tr("filter.proxy.any")), ("with", tr("filter.proxy.with")),
                                 ("without", tr("filter.proxy.without"))], current.proxy or "any")
        self.body.addWidget(self._proxy)

        self.body.addWidget(label(tr("filter.cookies"), "section"))
        self._cookies = Segmented([("any", tr("filter.proxy.any")), ("with", tr("filter.cookies.with")),
                                   ("without", tr("filter.cookies.without"))], current.cookies or "any")
        self.body.addWidget(self._cookies)

        self.body.addWidget(label(tr("filter.created"), "section"))
        self._created = Segmented([("any", tr("filter.proxy.any")), ("today", tr("filter.created.today")),
                                   ("week", tr("filter.created.week")), ("month", tr("filter.created.month"))],
                                  current.created or "any")
        self.body.addWidget(self._created)

        self._tags: _Chips | None = None
        if tags:
            self.body.addWidget(label(tr("filter.tags"), "section"))
            ordered = sorted(tags, key=str.casefold)[:16]
            self._tags = _Chips([(t, f"{t} · {tags[t]}") for t in ordered],
                                {current.tag} if current.tag else set(), exclusive=True)
            self.body.addWidget(self._tags)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.addStretch(1)
        self._reset = Button(tr("filter.reset"), "link")
        self._reset.clicked.connect(self._on_reset)
        footer.addWidget(self._reset)
        self.body.addLayout(footer)

        for segmented in (self._state, self._proxy, self._cookies, self._created):
            segmented.changed.connect(lambda _k: self._emit())
        self._platforms.changed.connect(self._emit)
        if self._tags is not None:
            self._tags.changed.connect(self._emit)

    @staticmethod
    def _none_if(value: str | None, neutral: str) -> str | None:
        return None if value in (None, neutral) else value

    def _emit(self) -> None:
        tag = next(iter(self._tags.value()), None) if self._tags is not None else None
        self.changed.emit(FilterState(
            state=self._none_if(self._state.value(), "all"), platforms=self._platforms.value(),
            proxy=self._none_if(self._proxy.value(), "any"), cookies=self._none_if(self._cookies.value(), "any"),
            created=self._none_if(self._created.value(), "any"), tag=tag,
        ))

    def _on_reset(self) -> None:
        self._state.set_value("all")
        self._proxy.set_value("any")
        self._cookies.set_value("any")
        self._created.set_value("any")
        self._platforms.clear()
        if self._tags is not None:
            self._tags.clear()
        self._emit()
