"""The table every list page uses: flat header, hover row, per-pixel scrolling, a shared spinner."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter, QRegion
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHeaderView, QTableView, QWidget

from antidetect.gui.theme import current_palette
from antidetect.gui.theme import icons as ic
from antidetect.gui.views.paint import elide, ratio

CELL_PAD = 14
HEADER_HEIGHT = 34
_SPIN_MS = 33


class FlatHeader(QHeaderView):
    """Muted captions, no lines; a small chevron marks the sorted column."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setStretchLastSection(False)
        self.setSortIndicatorShown(True)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._font = QFont(self.font())
        self._font.setPixelSize(12)
        self._font.setWeight(QFont.Weight.Medium)

    def paintSection(self, painter: QPainter, rect: QRect, logical: int) -> None:  # noqa: N802
        pal = current_palette()
        model = self.model()
        text = str(model.headerData(logical, Qt.Orientation.Horizontal) or "") if model is not None else ""
        if not text:
            return
        painter.save()
        painter.setFont(self._font)
        sorted_here = self.isSortIndicatorShown() and self.sortIndicatorSection() == logical
        hovered = self.underMouse() and rect.contains(self.mapFromGlobal(self.cursor().pos()))
        painter.setPen(pal.text if sorted_here or hovered else pal.muted)
        inner = rect.adjusted(CELL_PAD, 0, -CELL_PAD // 2, 0)
        width = inner.width() - (16 if sorted_here else 0)
        elided = elide(text, self._font, max(0, width))
        painter.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        if sorted_here:
            used = painter.fontMetrics().horizontalAdvance(elided)
            name = "arrow-up" if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else "arrow-down"
            painter.drawPixmap(inner.left() + used + 4, rect.center().y() - 6,
                               ic.pixmap(name, pal.faint, 12, dpr=ratio(painter)))
        painter.restore()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        self.viewport().update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.viewport().update()


class DataTable(QTableView):
    """A borderless row-selecting table that remembers which row the mouse is over."""

    widthChanged = Signal(int)   # viewport width, for pages that hide columns when narrow
    rowClicked = Signal(object)  # a plain left click on a row (not on one of its buttons, not with a modifier)

    def __init__(self, row_height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHorizontalHeader(FlatHeader(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setSortingEnabled(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(row_height)
        self.verticalHeader().setMinimumSectionSize(row_height)
        self.verticalScrollBar().setSingleStep(24)
        self.hover_row = -1
        self.hover_pos = QPoint(-1, -1)
        #: When True a row is selected only through its checkbox (the delegate toggles it) or with
        #: Ctrl / Shift: a plain click on the row, or a plain arrow key, leaves the selection alone.
        self.select_by_checkbox = False
        self.hotspot: Callable[[QModelIndex, QPoint], bool] | None = None
        #: A table whose rows open into a drawer sets this (see ``RowExpander``); delegates ask it how tall a row's card is.
        self.expander = None
        self._pressed = QModelIndex()
        self.spin_phase = 0
        self._spin_columns: tuple[int, ...] = ()
        self._spinner = QTimer(self)
        self._spinner.setInterval(_SPIN_MS)
        self._spinner.timeout.connect(self._advance_spinner)

    # ------------------------------------------------------------------ selection
    _MODIFIERS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.MetaModifier
    _PLAIN = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
              QEvent.Type.MouseMove, QEvent.Type.KeyPress)

    def selectionCommand(self, index, event=None):  # noqa: N802
        if self.select_by_checkbox:
            if event is None:                       # "make this the current row" never ticks it either
                return QItemSelectionModel.SelectionFlag.NoUpdate
            if (event.type() in self._PLAIN and not event.modifiers() & self._MODIFIERS
                    and not (event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space)):
                return QItemSelectionModel.SelectionFlag.NoUpdate
        return super().selectionCommand(index, event)

    # ------------------------------------------------------------------ spinner
    def set_spinning(self, columns: tuple[int, ...]) -> None:
        """Turn the shared spinner on for the cells of ``columns`` (empty = off, no timer runs)."""
        self._spin_columns = columns
        if columns and not self._spinner.isActive() and self.isVisible():
            self._spinner.start()
        elif not columns:
            self._spinner.stop()

    def _advance_spinner(self) -> None:
        if not self.isVisible():
            return
        self.spin_phase = (self.spin_phase + 24) % 360
        region = QRegion()
        for column in self._spin_columns:
            region += QRect(self.columnViewportPosition(column), 0, self.columnWidth(column), self.viewport().height())
        self.viewport().update(region)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._spin_columns and not self._spinner.isActive():
            self._spinner.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._spinner.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------------ hover
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.widthChanged.emit(self.viewport().width())
        if self.expander is not None:
            self.expander.reposition()

    def expansion_extra(self, row: int) -> int:
        """Pixels the row has grown by because its drawer is open (0 for every other row)."""
        return self.expander.extra_of_row(row) if self.expander is not None else 0

    # ------------------------------------------------------------------ clicks
    def mousePressEvent(self, event) -> None:  # noqa: N802
        plain = event.button() == Qt.MouseButton.LeftButton and not event.modifiers() & self._MODIFIERS
        self._pressed = self.indexAt(event.position().toPoint()) if plain else QModelIndex()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        plain = (event.button() == Qt.MouseButton.LeftButton and not event.modifiers() & self._MODIFIERS
                 and index.isValid() and self._pressed.isValid() and index.row() == self._pressed.row()
                 and not (self.hotspot is not None and self.hotspot(index, pos)))
        self._pressed = QModelIndex()
        super().mouseReleaseEvent(event)
        if plain:
            self.rowClicked.emit(index)

    def _row_rect(self, row: int) -> QRect:
        return QRect(0, self.rowViewportPosition(row), self.viewport().width(), self.rowHeight(row))

    def _set_hover(self, row: int, pos: QPoint) -> None:
        previous = self.hover_row
        self.hover_row, self.hover_pos = row, pos
        for target in {previous, row}:
            if target >= 0:
                self.viewport().update(self._row_rect(target))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        self._set_hover(index.row() if index.isValid() else -1, pos)
        over = bool(index.isValid() and self.hotspot is not None and self.hotspot(index, pos))
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(-1, QPoint(-1, -1))
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        super().wheelEvent(event)
        # the pointer stays still while rows scroll under it: keep the hover in step
        pos = self.viewport().mapFromGlobal(self.cursor().pos())
        if self.viewport().rect().contains(pos):
            index = self.indexAt(pos)
            self._set_hover(index.row() if index.isValid() else -1, pos)
