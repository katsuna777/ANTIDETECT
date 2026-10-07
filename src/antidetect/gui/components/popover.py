"""Popovers: small floating cards anchored to a button (filter, proxy details, command palette)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from antidetect.gui.theme import current_palette

SHADOW = 18          # transparent margin around the card that the shadow is painted into
RADIUS = 14


def paint_floating_card(painter: QPainter, rect: QRectF, radius: float = RADIUS) -> None:
    """A raised card with a diffuse shadow (a stack of translucent rounded rectangles)."""
    pal = current_palette()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    base = 34 if not pal.is_dark else 120
    for step in range(8, 0, -1):
        grow = step * 1.5
        painter.setBrush(QColor(0, 0, 0, max(1, int(base * (9 - step) / 70))))
        painter.drawRoundedRect(rect.adjusted(-grow, -grow + 6, grow, grow + 6), radius + grow, radius + grow)
    painter.setPen(QPen(QColor(pal.border_strong if pal.is_dark else pal.border), 1))
    painter.setBrush(QColor(pal.raised))
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class Popover(QFrame):
    """A frameless popup that closes on an outside click or Escape. Fill ``self.body``."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None, *, padding: int = 14, width: int = 320) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setObjectName("Popover")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW + padding, SHADOW + padding, SHADOW + padding, SHADOW + padding)
        outer.setSpacing(0)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        outer.addLayout(self.body)
        self.setFixedWidth(width + 2 * SHADOW + 2 * padding)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_floating_card(painter, QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW))

    def card_rect(self) -> QRect:
        return self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)

    def popup_at(self, anchor: QRect, *, align: str = "left", gap: int = 6) -> None:
        """Show under ``anchor`` (global coordinates), card edge flush with its left or right edge."""
        self.adjustSize()
        card_w = self.width() - 2 * SHADOW
        x = anchor.left() if align == "left" else anchor.right() + 1 - card_w
        y = anchor.bottom() + 1 + gap
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 8, min(x, area.right() - card_w - 8))
            if y + self.height() - SHADOW > area.bottom() - 8:      # no room below: open upwards
                y = anchor.top() - gap - (self.height() - SHADOW)
        self.move(QPoint(x - SHADOW, y - SHADOW))
        self.show()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self.closed.emit()
