"""Paints the Activity list: a muted day header, then one row per event with a tinted icon tile."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from antidetect.gui.models.activity import ITEM_ROLE, day_label
from antidetect.gui.theme import current_palette
from antidetect.gui.views.paint import draw_icon, draw_text, text_width

HEADER_H = 40
ROW_H = 56
TILE = 34


def _tone_colors(pal, tone: str) -> tuple[str, str]:
    """(icon colour, tile fill)."""
    return {
        "success": (pal.success, pal.success_soft),
        "danger": (pal.danger, pal.danger_soft),
        "warning": (pal.warning, pal.warning_soft),
        "accent": (pal.text, pal.subtle),
    }.get(tone, (pal.muted, pal.subtle))


class ActivityDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fonts: dict[tuple, QFont] = {}

    def _font(self, base: QFont, px: int, weight=QFont.Weight.Normal) -> QFont:
        key = (px, int(weight))
        font = self._fonts.get(key)
        if font is None:
            font = self._fonts[key] = QFont(base)
            font.setPixelSize(px)
            font.setWeight(weight)
        return font

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        item = index.data(ITEM_ROLE)
        return QSize(option.rect.width(), HEADER_H if item is not None and item.entry is None else ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            return
        pal = current_palette()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = option.rect
        base = option.font
        if item.entry is None:
            font = self._font(base, 11, QFont.Weight.DemiBold)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
            painter.setFont(font)
            painter.setPen(QColor(pal.muted))
            painter.drawText(QRect(rect.left() + 14, rect.top() + 12, rect.width() - 28, rect.height() - 12),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             day_label(item.day).upper())
            painter.restore()
            return
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.hover))
            painter.drawRoundedRect(QRectF(rect).adjusted(2, 2, -2, -2), 12, 12)
        icon_color, fill = _tone_colors(pal, item.tone)
        tile = QRectF(rect.left() + 14, rect.center().y() - TILE / 2 + 0.5, TILE, TILE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(tile, TILE * 0.3, TILE * 0.3)
        draw_icon(painter, item.icon, icon_color, tile.center().x() - 8, tile.center().y() - 8, 16, 1.9)
        time_font = self._font(base, 12)
        time_w = text_width(item.time, time_font) + 6
        right = rect.right() - 16
        draw_text(painter, QRect(right - time_w, rect.top(), time_w, rect.height()), item.time, time_font, pal.faint,
                  Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        left = int(tile.right()) + 14
        width = right - time_w - 14 - left
        title_font, detail_font = self._font(base, 13, QFont.Weight.Medium), self._font(base, 12)
        if item.detail:
            top = rect.center().y() - 17
            draw_text(painter, QRect(left, top, width, 17), item.title, title_font, pal.text)
            draw_text(painter, QRect(left, top + 18, width, 16), item.detail, detail_font,
                      pal.danger if item.tone == "danger" else pal.muted)
        else:
            draw_text(painter, QRect(left, rect.top(), width, rect.height()), item.title, title_font, pal.text)
        painter.restore()
