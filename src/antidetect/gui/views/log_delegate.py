"""Paints one log line: time, level badge, source and message."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from antidetect.gui.models.logs import LINE_ROLE, LogLine
from antidetect.gui.theme import current_palette

LOG_ROW_HEIGHT = 26
_NAMES = ("DEBUG", "INFO", "WARN", "ERROR")


class LogDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._mono.setPixelSize(12)
        self._badge = QFont(self._mono)
        self._badge.setPixelSize(10)
        self._badge.setWeight(QFont.Weight.Bold)
        self._source_width = QFontMetrics(self._mono).horizontalAdvance("0" * 13)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), LOG_ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        line: LogLine | None = index.data(LINE_ROLE)
        if line is None:
            return
        pal = current_palette()
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor(pal.accent_soft))
        elif line.level == 3:
            painter.fillRect(rect, QColor(pal.danger_soft))
        painter.setFont(self._mono)
        fm = QFontMetrics(self._mono)
        x = rect.left() + 14
        painter.setPen(QColor(pal.faint))
        painter.drawText(QRect(x, rect.top(), 70, rect.height()), Qt.AlignmentFlag.AlignVCenter, line.clock)
        x += 74
        fg, bg = {
            3: (pal.danger, pal.danger_soft), 2: (pal.warning, pal.warning_soft),
            1: (pal.muted, pal.subtle), 0: (pal.faint, pal.subtle),
        }[line.level]
        chip = QRectF(x, rect.center().y() - 8, 46, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg if line.level != 3 else pal.surface))
        painter.drawRoundedRect(chip, 4, 4)
        painter.setFont(self._badge)
        painter.setPen(QColor(fg))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, _NAMES[line.level])
        x += 54
        painter.setFont(self._mono)
        painter.setPen(QColor(pal.muted))
        painter.drawText(QRect(x, rect.top(), self._source_width, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(line.source, Qt.TextElideMode.ElideRight, self._source_width))
        x += self._source_width + 10
        painter.setPen(QColor(pal.danger if line.level == 3 else pal.text))
        width = rect.right() - x - 12
        painter.drawText(QRect(x, rect.top(), width, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(line.message, Qt.TextElideMode.ElideRight, width))
        painter.restore()
