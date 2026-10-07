"""Deterministic coloured avatars for profiles (initial on a tinted rounded square)."""

from __future__ import annotations

import zlib

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

# (light background, light text, dark background, dark text)
_TINTS = (
    ("#E6EDFF", "#2B4FD8", "#161B2E", "#8EA8FF"),
    ("#E4F5EC", "#1B7F4B", "#0F2218", "#58D69A"),
    ("#FDEFD9", "#A25A0A", "#271E0E", "#EDB45E"),
    ("#F6E7FA", "#9333B0", "#25172B", "#D58BEB"),
    ("#E3F4F7", "#13768A", "#0C2226", "#5CCBE0"),
    ("#FCE8EA", "#C0273A", "#2B1618", "#F28A97"),
    ("#EEF0F3", "#4B5566", "#1F1F1F", "#A8A8A8"),
)


def tint_for(name: str, dark: bool) -> tuple[QColor, QColor]:
    index = zlib.crc32((name or "?").casefold().encode("utf-8")) % len(_TINTS)
    bg_l, fg_l, bg_d, fg_d = _TINTS[index]
    return (QColor(bg_d), QColor(fg_d)) if dark else (QColor(bg_l), QColor(fg_l))


def initial(name: str) -> str:
    for ch in name.strip():
        if ch.isalnum():
            return ch.upper()
    return "?"


#: Corner radius of a tile as a fraction of its side: the same shape the key tiles on the API page have.
TILE_RADIUS = 0.3


def paint_avatar(painter: QPainter, rect: QRectF, name: str, dark: bool, *, radius: float | None = None,
                 font_px: int = 15) -> None:
    """The profile's initial on a tinted rounded square."""
    bg, fg = tint_for(name, dark)
    radius = rect.height() * TILE_RADIUS if radius is None else radius
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(rect, radius, radius)
    font = QFont(painter.font())
    font.setPixelSize(font_px)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(fg)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initial(name))
    painter.restore()


class AvatarBadge(QWidget):
    """The tile of a profile as a widget (dialog headers); follows the name while it is being typed."""

    def __init__(self, name: str = "", size: int = 44, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._size = size
        self.setFixedSize(QSize(size, size))

    def set_name(self, name: str) -> None:
        if name != self._name:
            self._name = name
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        from antidetect.gui.theme import current_palette

        painter = QPainter(self)
        paint_avatar(painter, QRectF(self.rect()), self._name, current_palette().is_dark,
                     font_px=round(self._size * 0.4))
