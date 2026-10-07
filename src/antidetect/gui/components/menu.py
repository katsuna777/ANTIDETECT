"""A context menu with rounded corners, icons, a danger item and chevrons drawn like the rest of the app's icons."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

from antidetect.gui.theme import current_palette
from antidetect.gui.theme import icons as ic

ICON_PX = 16
CHEVRON_PX = 14


class StyledMenu(QMenu):
    def __init__(self, parent: QWidget | None = None, title: str = "") -> None:
        super().__init__(title, parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def item(self, text: str, callback: Callable[[], object] | None = None, *, icon: str | None = None,
             danger: bool = False, accent: bool = False, enabled: bool = True, qicon: QIcon | None = None) -> QAction:
        """``danger``: red (the style sheet colours the menu's *default* action, so there is at most one);
        ``accent``: the icon in the accent colour (the main action of the menu)."""
        action = self.addAction(text)
        if callback is not None:
            action.triggered.connect(lambda _checked=False, cb=callback: cb())
        pal = current_palette()
        if qicon is not None:
            action.setIcon(qicon)
        elif icon == "blank":      # keeps the labels of a menu with ticks in one column
            blank = QPixmap(ICON_PX, ICON_PX)
            blank.fill(Qt.GlobalColor.transparent)
            action.setIcon(QIcon(blank))
        elif icon:
            color = pal.danger if danger else pal.accent if accent else pal.muted
            action.setIcon(ic.icon(icon, color, size=ICON_PX, disabled=pal.faint))
        action.setEnabled(enabled)
        if danger:
            self.setDefaultAction(action)
        return action

    def submenu(self, text: str, icon: str | None = None) -> "StyledMenu":
        sub = StyledMenu(self, text)
        action = self.addMenu(sub)
        if icon:
            action.setIcon(ic.icon(icon, current_palette().muted, size=ICON_PX))
        return sub

    def caption(self, text: str) -> QAction:
        action = self.addAction(text)
        action.setEnabled(False)
        return action

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        # The style's own submenu arrow is a different shape from every other chevron in the app (the style
        # sheet turns it off): draw ours, brighter on the row under the pointer.
        pal = current_palette()
        painter = None
        for action in self.actions():
            if action.menu() is None or action.isSeparator():
                continue
            rect = self.actionGeometry(action)
            if painter is None:
                painter = QPainter(self)
            hot = action is self.activeAction()
            color = pal.text if hot else pal.faint
            pixmap = ic.pixmap("chevron-right", color, CHEVRON_PX, 2.0, painter.device().devicePixelRatioF())
            painter.drawPixmap(rect.right() - CHEVRON_PX - 10, rect.center().y() - CHEVRON_PX // 2 + 1, pixmap)
