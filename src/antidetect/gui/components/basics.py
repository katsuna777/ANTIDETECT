"""Small building blocks: labels, buttons, cards, dividers, page header."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui.metrics import HEADER_HEIGHT
from antidetect.gui.theme import bus, current_palette
from antidetect.gui.theme import icons as ic

_ICON_PX = 16
_ICON_GAP = 6      # extra room after the glyph when the button also has text (Qt leaves ~2 px)


def label(text: str = "", role: str | None = None, *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def flash(button: QPushButton, text: str, restore: Callable[[], str], ms: int = 1600) -> None:
    """Show ``text`` on a button for a moment ("Copied"), then put ``restore()`` back.

    The timer belongs to the button, so it can never fire into a widget that is already gone.
    """
    button.setText(text)
    timer = QTimer(button)
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (button.setText(restore()), timer.deleteLater()))
    timer.start(ms)


def repolish(widget: QWidget) -> None:
    """Re-evaluate the style sheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_role(widget: QWidget, role: str) -> None:
    if widget.property("role") != role:
        widget.setProperty("role", role)
        repolish(widget)


class Button(QPushButton):
    """A push button whose optional icon follows the theme and the variant."""

    def __init__(self, text: str = "", variant: str | None = None, icon: str | None = None,
                 size: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        if variant:
            self.setProperty("variant", variant)
        if size == "sm":
            self.setProperty("compact", True)  # not "size": that is a built-in QWidget property
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._icon_name = icon
        self._fit_icon()
        self._refresh_icon()
        bus.changed.connect(self._refresh_icon)

    def setText(self, text: str) -> None:  # noqa: N802 - the icon slot depends on whether there is text
        super().setText(text)
        self._fit_icon()

    def _fit_icon(self) -> None:
        # The icon engine draws the glyph at the left of its slot, so a wider slot is a gap after it.
        has_icon, has_text = bool(getattr(self, "_icon_name", None)), bool(self.text())
        self.setIconSize(QSize(_ICON_PX + (_ICON_GAP if has_icon and has_text else 0), _ICON_PX))
        icon_only = has_icon and not has_text           # a square button (the style sheet sizes it)
        if bool(self.property("iconOnly")) != icon_only:
            self.setProperty("iconOnly", icon_only)
            repolish(self)

    def set_icon_name(self, name: str | None) -> None:
        self._icon_name = name
        self._fit_icon()
        self._refresh_icon()

    def set_active(self, active: bool) -> None:
        """Mark a toolbar button as 'something is switched on behind this' (a filter, a sort)."""
        if bool(self.property("active")) != active:
            self.setProperty("active", active)
            repolish(self)

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            self.setIcon(QIcon())
            return
        pal = current_palette()
        variant = self.property("variant")
        color = {
            "primary": pal.accent_text, "danger": pal.danger, "danger-solid": pal.danger_text,
            "link": pal.accent,
        }.get(variant, pal.text)
        self.setIcon(ic.icon(self._icon_name, color, size=_ICON_PX, disabled=pal.faint))


def button(text: str = "", variant: str | None = None, *, icon: str | None = None,
           size: str | None = None) -> Button:
    return Button(text, variant, icon, size)


class IconButton(QToolButton):
    """A square, borderless icon button (toolbar / row actions)."""

    def __init__(self, icon_name: str, tooltip: str = "", parent: QWidget | None = None, size: int = 18) -> None:
        super().__init__(parent)
        self.setProperty("role", "icon")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(tooltip)
        self.setIconSize(QSize(size, size))
        self._icon_name = icon_name
        self._size = size
        self._refresh_icon()
        bus.changed.connect(self._refresh_icon)

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        pal = current_palette()
        self.setIcon(ic.icon(self._icon_name, pal.muted, size=self._size, hover=pal.text, disabled=pal.faint))


class Card(QFrame):
    """A bordered surface. Add content to ``card.body`` (a zero-margin QVBoxLayout)."""

    def __init__(self, parent: QWidget | None = None, *, padding: int = 0, spacing: int = 0) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)


def divider() -> QFrame:
    line = QFrame()
    line.setProperty("role", "divider")
    line.setFixedHeight(1)
    return line


class PageHeader(QWidget):
    """The title row (``HEADER_HEIGHT`` tall, so every page's title sits at the same height) and,
    below it, an optional subtitle."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        top = self.top = QWidget()
        top.setMinimumHeight(HEADER_HEIGHT)
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.title = label(title, "title")
        row.addWidget(self.title)
        row.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions)
        col.addWidget(top)
        self.subtitle = label(subtitle, "subtitle")
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)

    def set_texts(self, title: str, subtitle: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))


class IconLabel(QLabel):
    """A QLabel that shows a themed icon (tint chosen from a palette attribute)."""

    def __init__(self, icon_name: str, tint: str = "muted", size: int = 18, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name, self._tint, self._size = icon_name, tint, size
        self.setFixedSize(size, size)
        self._refresh()
        bus.changed.connect(self._refresh)

    def set_icon(self, name: str, tint: str | None = None) -> None:
        self._name = name
        if tint:
            self._tint = tint
        self._refresh()

    def _refresh(self) -> None:
        color = getattr(current_palette(), self._tint, self._tint)
        self.setPixmap(ic.pixmap(self._name, color, self._size))
