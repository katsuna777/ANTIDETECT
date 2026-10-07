"""The small painted rows of the sidebar: navigation, tags, workspaces, section headers, the search pill."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from antidetect.gui.theme import current_palette
from antidetect.gui.theme import icons as ic
from antidetect.gui.theme.tags import slot_color, tag_color
from antidetect.gui.views.paint import ratio

ROW_HEIGHT = 36
SMALL_ROW = 32


def _fill(pal, checked: bool, hovered: bool) -> QColor | None:
    if checked:
        return QColor(pal.nav_selected)
    if hovered:
        color = QColor(pal.nav_selected)
        color.setAlpha(120)
        return color
    return None


class _Row(QAbstractButton):
    """A row that highlights under the pointer and when checked; subclasses paint what is inside."""

    RADIUS = 10

    def __init__(self, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedHeight(height)
        self._h = height

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, self._h)

    def _background(self, painter: QPainter, pal) -> tuple[bool, bool]:
        checked, hovered = self.isChecked(), self.underMouse()
        fill = _fill(pal, checked, hovered)
        if fill is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(self.rect()), self.RADIUS, self.RADIUS)
        return checked, hovered

    def _font(self, checked: bool, px: int = 13) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(px)
        font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Medium)
        return font

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class NavButton(_Row):
    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(ROW_HEIGHT, parent)
        self.setText(text)
        self.setCheckable(True)
        self._icon = icon_name
        self._count = ""
        self._badge = ""          # a filled red chip: something failed (the Activity feed)
        self._running = 0

    def set_count(self, text: str) -> None:
        self._count = text
        self.update()

    def set_badge(self, text: str) -> None:
        if text != self._badge:
            self._badge = text
            self.update()

    def set_running(self, count: int) -> None:
        self._running = max(0, count)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        checked, hovered = self._background(painter, pal)
        tint = pal.text if checked or hovered else pal.muted
        painter.drawPixmap(12, int(rect.center().y() - 9), ic.pixmap(self._icon, tint, 18, dpr=ratio(painter)))
        font = self._font(checked)
        small = QFont(font)
        small.setPixelSize(11)
        small.setWeight(QFont.Weight.DemiBold)
        right = rect.right() - 12
        if self._running:
            text = str(self._running)
            width = QFontMetrics(small).horizontalAdvance(text) + 18
            chip = QRectF(right - width, rect.center().y() - 9, width, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.success_soft))
            painter.drawRoundedRect(chip, 6, 6)
            painter.setBrush(QColor(pal.success))
            painter.drawEllipse(QRectF(chip.left() + 6, chip.center().y() - 2.5, 5, 5))
            painter.setFont(small)
            painter.setPen(QColor(pal.success))
            painter.drawText(QRectF(chip.left() + 13, chip.top(), width - 17, 18), Qt.AlignmentFlag.AlignCenter, text)
            right = chip.left() - 6
        elif self._badge:
            width = max(18, QFontMetrics(small).horizontalAdvance(self._badge) + 14)
            chip = QRectF(right - width, rect.center().y() - 9, width, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.danger))
            painter.drawRoundedRect(chip, 6, 6)
            painter.setFont(small)
            painter.setPen(QColor(pal.danger_text))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, self._badge)
            right = chip.left() - 6
        elif self._count:
            number = QFont(font)
            number.setPixelSize(12)
            number.setWeight(QFont.Weight.Normal)
            painter.setFont(number)
            painter.setPen(QColor(pal.faint))
            painter.drawText(QRectF(rect.left(), 0, right - rect.left(), rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._count)
        painter.setFont(font)
        painter.setPen(QColor(tint))
        painter.drawText(QRectF(40, 0, max(0, right - 48), rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class _CountedRow(_Row):
    """A name with a glyph on the left and a number on the right (tags, workspaces)."""

    def __init__(self, name: str, count: int, parent: QWidget | None = None) -> None:
        super().__init__(SMALL_ROW, parent)
        self.name, self.count = name, count
        self.setText(name)
        self.setCheckable(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _glyph(self, painter: QPainter, pal, rect: QRectF) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        checked, hovered = self._background(painter, pal)
        self._glyph(painter, pal, rect)
        font = self._font(checked)
        number = QFont(font)
        number.setPixelSize(12)
        number.setWeight(QFont.Weight.Normal)
        text = str(self.count)
        number_w = QFontMetrics(number).horizontalAdvance(text)
        text_w = max(0, rect.width() - 42 - number_w - 22)
        painter.setFont(font)
        painter.setPen(QColor(pal.text if checked or hovered else pal.muted))
        painter.drawText(QRectF(36, 0, text_w, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(font).elidedText(self.name, Qt.TextElideMode.ElideRight, int(text_w)))
        painter.setFont(number)
        painter.setPen(QColor(pal.faint))
        painter.drawText(QRectF(rect.right() - 12 - number_w - 2, 0, number_w + 2, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)


class TagRow(_CountedRow):
    """A tag: coloured dot, name, how many profiles carry it."""

    def __init__(self, tag: str, count: int, parent: QWidget | None = None) -> None:
        super().__init__(tag, count, parent)
        self.tag = tag

    def _glyph(self, painter: QPainter, pal, rect: QRectF) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tag_color(self.tag)))
        painter.drawEllipse(QRectF(15, rect.center().y() - 3.5, 7, 7))


class WorkspaceRow(_CountedRow):
    """A workspace: a rounded square in its colour with the first letter, name, number of profiles."""

    def __init__(self, workspace_id: int, name: str, color: int | None, count: int, parent: QWidget | None = None) -> None:
        super().__init__(name, count, parent)
        self.workspace_id, self.color = workspace_id, color

    def _glyph(self, painter: QPainter, pal, rect: QRectF) -> None:
        tile = QRectF(10, rect.center().y() - 9, 18, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.color is None:                                       # "no workspace": a neutral, dashed-looking tile
            painter.setBrush(QColor(pal.subtle))
            painter.drawRoundedRect(tile, 5.5, 5.5)
            painter.drawPixmap(int(tile.left() + 3), int(tile.top() + 3),
                               ic.pixmap("layers", pal.faint, 12, 2.0, ratio(painter)))
            return
        painter.setBrush(QColor(slot_color(self.color)))
        painter.drawRoundedRect(tile, 5.5, 5.5)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        letter = next((ch for ch in self.name.strip() if ch.isalnum()), "?").upper()
        painter.drawText(tile, Qt.AlignmentFlag.AlignCenter, letter)


class ActionRow(_Row):
    """A quiet row with an icon: "Create a workspace", "Manage tags"."""

    def __init__(self, text: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(SMALL_ROW, parent)
        self.setText(text)
        self._icon = icon_name

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        _checked, hovered = self._background(painter, pal)
        tint = pal.text if hovered else pal.faint
        painter.drawPixmap(11, int(rect.center().y() - 8), ic.pixmap(self._icon, tint, 16, dpr=ratio(painter)))
        font = self._font(False, 12)
        painter.setFont(font)
        painter.setPen(QColor(tint))
        painter.drawText(QRectF(36, 0, rect.width() - 44, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(font).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(rect.width() - 44)))


class SectionHeader(QAbstractButton):
    """"TAGS" with a chevron that folds the list away and, optionally, a "+" that adds an item."""

    actionClicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None, *, action: bool = False) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setFixedHeight(28)
        self.expanded = True
        self._action = action
        self._over_action = False
        self._press_action = False

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, 28)

    def _action_rect(self) -> QRectF:
        return QRectF(self.width() - 54, (self.height() - 22) / 2, 22, 22)

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        painter.setFont(font)
        painter.setPen(QColor(pal.text if self.underMouse() and not self._over_action else pal.faint))
        painter.drawText(QRectF(12, 0, self.width() - 70, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text().upper())
        if self._action:
            area = self._action_rect()
            if self._over_action:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(pal.nav_selected))
                painter.drawRoundedRect(area, 7, 7)
            painter.drawPixmap(int(area.left() + 4), int(area.top() + 4),
                               ic.pixmap("plus", pal.text if self._over_action else pal.faint, 14, 2.0, ratio(painter)))
        name = "chevron-down" if self.expanded else "chevron-right"
        painter.drawPixmap(self.width() - 28, self.height() // 2 - 7, ic.pixmap(name, pal.faint, 14, dpr=ratio(painter)))

    def _hit_action(self, pos: QPoint) -> bool:
        return self._action and self._action_rect().contains(QPointF(pos))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        over = self._hit_action(event.position().toPoint())
        if over != self._over_action:
            self._over_action = over
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press_action = self._hit_action(event.position().toPoint())
        if not self._press_action:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._press_action:
            self._press_action = False
            if self._hit_action(event.position().toPoint()):
                self.actionClicked.emit()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._over_action = False
        self.update()
        super().leaveEvent(event)


class MoreButton(QAbstractButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(28)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, 28)

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor(pal.text if self.underMouse() else pal.faint))
        painter.drawText(QRectF(36, 0, self.width() - 44, self.height()), Qt.AlignmentFlag.AlignVCenter, self.text())

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class SearchPill(QAbstractButton):
    """The quick-search button next to the brand: a magnifier and the shortcut."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._hint = QKeySequence("Ctrl+K").toString(QKeySequence.SequenceFormat.NativeText).replace("+", "")
        self.setFixedHeight(30)

    def sizeHint(self) -> QSize:  # noqa: N802
        font = QFont(self.font())
        font.setPixelSize(12)
        return QSize(QFontMetrics(font).horizontalAdvance(self._hint) + 44, 30)

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(pal.border), 1))
        painter.setBrush(QColor(pal.nav_selected if self.underMouse() else pal.surface))
        painter.drawRoundedRect(rect, 10, 10)
        painter.drawPixmap(10, self.height() // 2 - 7, ic.pixmap("search", pal.muted, 14, 2.0, ratio(painter)))
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(pal.faint))
        painter.drawText(QRectF(30, 0, self.width() - 36, self.height()), Qt.AlignmentFlag.AlignVCenter, self._hint)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)
