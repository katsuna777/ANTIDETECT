"""Hand-painting helpers shared by the table delegates and the popovers.

Shadows are never ``QGraphicsDropShadowEffect`` (it renders every widget through an offscreen
buffer on each repaint): a soft shadow here is three stacked translucent rounded rectangles.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap

from antidetect.gui.theme import flags
from antidetect.gui.theme import icons as ic
from antidetect.gui.theme.palette import Palette

_ELIDE_CACHE: dict[tuple, str] = {}


def ratio(painter: QPainter) -> float:
    return painter.device().devicePixelRatioF() or 1.0


def elide(text: str, font: QFont, width: int) -> str:
    """``text`` cut with an ellipsis to ``width`` px; remembered, since a table repaints constantly."""
    if width <= 0:
        return ""
    key = (text, font.pixelSize(), int(font.weight()), width)
    cached = _ELIDE_CACHE.get(key)
    if cached is None:
        if len(_ELIDE_CACHE) > 4000:
            _ELIDE_CACHE.clear()
        cached = _ELIDE_CACHE[key] = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, width)
    return cached


def text_width(text: str, font: QFont) -> int:
    return QFontMetrics(font).horizontalAdvance(text)


def soft_shadow(painter: QPainter, rect: QRectF, radius: float, pal: Palette, strength: float = 1.0) -> None:
    """A faint, tight drop shadow under a card (light theme only: on black it would be invisible)."""
    if not pal.shadow:
        return
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for grow, drop, weight in ((3.0, 2.5, 0.22), (1.8, 1.6, 0.34), (0.8, 0.8, 0.5)):
        painter.setBrush(QColor(20, 20, 40, int(pal.shadow * weight * strength)))
        painter.drawRoundedRect(rect.adjusted(-grow, -grow + drop, grow, grow + drop), radius + grow, radius + grow)
    painter.restore()


_CARD_CACHE: dict[tuple, QPixmap] = {}
_MARGIN = 5      # room around a card for its shadow


def draw_card(painter: QPainter, rect: QRectF, pal: Palette, *, radius: float | None = None,
              fill: str | QColor | None = None, border: str | QColor | None = None, shadow: bool = True) -> None:
    """A little white card with a hairline and a soft shadow (the cells of the profiles table).

    A card is the same few shapes over and over (every "Stopped" pill is alike), so it is rendered
    once per size and colour and blitted afterwards: a table repaint then costs one drawPixmap per card.
    """
    r = min(10.0, rect.height() * 0.36) if radius is None else radius
    dpr = ratio(painter)
    fill_name = QColor(fill or pal.pill).name(QColor.NameFormat.HexArgb)
    border_name = QColor(border or pal.pill_border).name(QColor.NameFormat.HexArgb)
    use_shadow = bool(shadow and pal.shadow)
    key = (round(rect.width(), 1), round(rect.height(), 1), round(r, 1), fill_name, border_name, use_shadow, dpr)
    pixmap = _CARD_CACHE.get(key)
    if pixmap is None:
        if len(_CARD_CACHE) > 600:
            _CARD_CACHE.clear()
        w, h = rect.width(), rect.height()
        image = QImage(max(1, round((w + 2 * _MARGIN) * dpr)), max(1, round((h + 2 * _MARGIN) * dpr)),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        buffer = QPainter(image)
        buffer.setRenderHint(QPainter.RenderHint.Antialiasing)
        inner = QRectF(_MARGIN, _MARGIN, w, h)
        if use_shadow:
            soft_shadow(buffer, inner, r, pal)
        buffer.setPen(QPen(QColor(border_name), 1))
        buffer.setBrush(QColor(fill_name))
        buffer.drawRoundedRect(inner.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        buffer.end()
        pixmap = _CARD_CACHE[key] = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(dpr)
    painter.drawPixmap(QPointF(rect.x() - _MARGIN, rect.y() - _MARGIN), pixmap)


def draw_flag(painter: QPainter, center_x: float, center_y: float, code: str | None, pal: Palette,
              diameter: int = 24) -> bool:
    """The flag of ``code`` (a rounded square) centred on a point, or a neutral chip with the letters. False = no code."""
    code = (code or "").strip().upper()
    left, top = round(center_x - diameter / 2), round(center_y - diameter / 2)
    pixmap = flags.pixmap(code, diameter, ratio(painter)) if code else None
    if pixmap is not None:
        painter.drawPixmap(left, top, pixmap)
        return True
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(pal.subtle))
    painter.drawRoundedRect(QRectF(left, top, diameter, diameter), diameter * 0.3, diameter * 0.3)
    if code:
        font = QFont(painter.font())
        font.setPixelSize(max(8, diameter // 2 - 1))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(pal.muted))
        painter.drawText(QRectF(left, top, diameter, diameter), Qt.AlignmentFlag.AlignCenter, code[:2])
    else:
        painter.drawPixmap(left + diameter // 2 - 7, top + diameter // 2 - 7, ic.pixmap("globe", pal.faint, 14, dpr=ratio(painter)))
    painter.restore()
    return bool(code)


def draw_icon(painter: QPainter, name: str, color: str, left: float, top: float, size: int = 16,
              stroke: float = 1.75) -> None:
    painter.drawPixmap(round(left), round(top), ic.pixmap(name, color, size, stroke, ratio(painter)))


def draw_spinner(painter: QPainter, center_x: float, center_y: float, color: str, phase: int, size: int = 16) -> None:
    """A quarter-open ring turning with ``phase`` (degrees)."""
    painter.save()
    painter.translate(center_x, center_y)
    painter.rotate(phase)
    painter.drawPixmap(-size // 2, -size // 2, ic.pixmap("loader", color, size, 2.0, ratio(painter)))
    painter.restore()


def draw_text(painter: QPainter, rect: QRect, text: str, font: QFont, color: str | QColor,
              align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) -> None:
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(rect, align, elide(text, font, rect.width()))
