"""Opens one row of a table into a drawer: the row grows downwards, the drawer is revealed inside the new space.

How it works. The row's height is animated (``setRowHeight`` each frame), so the rows below slide down by
themselves and nothing is re-laid-out except that one section. The drawer is an ordinary widget that sits
over the viewport in the space the row has gained; it keeps its full size and is only *clipped* by a
container whose height follows the animation, so its contents are never squeezed — they are revealed, like
a drawer sliding out from under the row. The delegate paints the row's card behind it (see
``DataTable.expansion_extra``).

Only one row is open at a time. Opening another one closes the first at the same moment; the closing row
keeps showing a still picture of its drawer (a "ghost") while it shrinks.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QModelIndex, QObject, QPointF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

EXPAND_MS = 300
COLLAPSE_MS = 240
REFIT_MS = 180                 # the open drawer needs another height (a tag wrapped onto a new line)
CARD_INSET = 2                 # the row card is painted this far inside the row (see ``paint_row``)


def _curve() -> QEasingCurve:
    """cubic-bezier(.3, 0, .15, 1): it leaves slowly (the first, always the most expensive, frame hardly moves — the
    old OutCubic jumped 60 px at once) and settles gently. About 16 px/frame at most near the start."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.30, 0.0), QPointF(0.15, 1.0), QPointF(1.0, 1.0))
    return curve


class _Clip(QWidget):
    """A window onto the drawer: its height follows the animation, its child keeps the drawer's full size."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()


class _Ghost(QWidget):
    """A still picture of a drawer that is closing."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.full_width = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.full_width = round(pixmap.deviceIndependentSize().width()) if not pixmap.isNull() else 0

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._pixmap.isNull():
            QPainter(self).drawPixmap(0, 0, self._pixmap)


class RowExpander(QObject):
    """Owns the open row of ``table``. ``drawer`` is the one widget that is reused for every row."""

    opened = Signal(object)     # the key of the row that opened
    closed = Signal()

    def __init__(self, table, drawer: QWidget, *, base_height: int, key_of: Callable[[int], object | None],
                 row_of: Callable[[object], int], drawer_height: Callable[[int], int]) -> None:
        super().__init__(table)
        self._table = table
        self._view = table.viewport()
        self._drawer = drawer
        self._base = base_height
        self._key_of, self._row_of, self._height_for = key_of, row_of, drawer_height
        self._clip = _Clip(self._view)
        drawer.setParent(self._clip)
        drawer.move(0, 0)
        self._ghost = _Ghost(self._view)
        self._key: object | None = None          # the open (or opening) row
        self._ghost_key: object | None = None    # the row that is closing
        self._extra = 0.0                        # px the open row has gained so far
        self._ghost_extra = 0.0
        self._full = 0                           # the drawer's full height for the current width
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._on_step)
        self._anim.finished.connect(self._on_finished)
        self._extra_from = 0.0
        self._ghost_from = 0.0
        self._scroll_from = 0
        self._scroll_by = 0
        self._row_cache: dict[object, int] = {}
        model = table.model()
        for signal in (model.layoutChanged, model.modelReset, model.rowsInserted, model.rowsRemoved):
            signal.connect(self._resync)
        model.dataChanged.connect(self._data_changed)
        table.verticalScrollBar().valueChanged.connect(self._place)

    def warm_up(self, key: object) -> None:
        """Render the drawer once, unseen, in idle time: the first real opening then does not pay for the style
        sheet polish of its ~40 widgets, the first text layouts and icon caches (it used to hitch for ~25 ms)."""
        if self._key is not None or self._row_of(key) < 0 or self._anim.state() == QVariantAnimation.State.Running:
            return
        self.opened.emit(key)                                      # a real row, so the chips and icons get painted too
        width = max(self._view.width(), 320)
        self._drawer.setFixedSize(width, self._height_for(width))
        self._drawer.grab()
        # ...and "show" it once far above the viewport, where nothing is painted: the show events (text edits,
        # combo boxes, the tag field) are then also behind us when the real opening happens.
        self._clip.setGeometry(0, -50000, width, 40)
        self._clip.show()
        self._clip.hide()

    # ------------------------------------------------------------------ queries
    @property
    def key(self) -> object | None:
        return self._key

    def is_open(self) -> bool:
        return self._key is not None

    def extra_of_row(self, row: int) -> int:
        """How many pixels row ``row`` has gained (the delegate paints the card that tall)."""
        if self._key is not None and self._row_of(self._key) == row:
            return int(self._extra)
        if self._ghost_key is not None and self._row_of(self._ghost_key) == row:
            return int(self._ghost_extra)
        return 0

    # ------------------------------------------------------------------- toggling
    def toggle(self, index: QModelIndex) -> None:
        key = self._key_of(index.row())
        if key is None:
            return
        self.close() if key == self._key else self.open(key)

    def open(self, key: object) -> None:
        """Open the row ``key``; the one that was open (if any) closes."""
        row = self._row_of(key)
        if row < 0 or key == self._key:
            return
        self._finish_now()
        previous = self._key
        if previous is not None:                                   # it keeps its picture while it shrinks
            self._start_ghost(previous)
        self._key = key
        self.opened.emit(key)                                      # the drawer fills itself first: its height depends on it
        self._full = self._height_for(self._view.width())
        self._extra_from = 0.0
        self._extra = 0.0
        self._drawer.setFixedSize(self._view.width(), self._full)
        self._scroll_from = self._table.verticalScrollBar().value()
        self._scroll_by = self._scroll_needed(row)
        self._clip.show()
        self._clip.raise_()
        self._run(EXPAND_MS)

    def close(self, *, animated: bool = True) -> None:
        if self._key is None:
            return
        self._finish_now()
        key = self._key
        if not animated or not self._table.isVisible():
            self._set_row_height(key, 0)
            self._key, self._extra = None, 0.0
            self._clip.hide()
            self._place()
            self.closed.emit()
            return
        self._start_ghost(key)
        self._key, self._extra = None, 0.0
        self._clip.hide()
        self._scroll_by = 0
        self._extra_from = 0.0
        self._run(COLLAPSE_MS)
        self.closed.emit()

    # ------------------------------------------------------------------ animation
    def _run(self, duration: int) -> None:
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(_curve())
        if not self._table.isVisible():
            self._on_step(1.0)
            self._on_finished()
            return
        self._anim.start()

    def _finish_now(self) -> None:
        if self._anim.state() == QVariantAnimation.State.Running:
            self._anim.stop()
            self._on_step(1.0)
            self._on_finished()

    def _start_ghost(self, key: object) -> None:
        """Freeze the drawer of ``key`` as a picture and let its row shrink around it."""
        if self._ghost_key is not None:
            self._set_row_height(self._ghost_key, 0)
        pixmap = self._drawer.grab() if self._drawer.isVisible() and self._extra > 0 else QPixmap()
        self._ghost_key = key
        self._ghost_extra = self._ghost_from = max(self._extra, 0.0) if key == self._key else self._ghost_extra
        self._ghost.set_pixmap(pixmap)
        self._ghost.show()
        self._ghost.raise_()

    def _on_step(self, value) -> None:
        t = float(value)
        table = self._table
        if self._key is not None:
            self._extra = self._extra_from + (self._full - self._extra_from) * t
            self._set_row_height(self._key, int(self._extra))
        if self._ghost_key is not None:
            self._ghost_extra = self._ghost_from * (1.0 - t)
            self._set_row_height(self._ghost_key, int(self._ghost_extra))
        table.updateGeometries()
        if self._scroll_by:
            table.verticalScrollBar().setValue(self._scroll_from + int(self._scroll_by * t))
        self._place()

    def _on_finished(self) -> None:
        if self._ghost_key is not None:
            self._set_row_height(self._ghost_key, 0)
            self._ghost_key, self._ghost_extra = None, 0.0
            self._ghost.hide()
        if self._key is not None:
            self._extra = float(self._full)
            self._set_row_height(self._key, self._full)
        self._table.updateGeometries()
        self._place()
        self._table.viewport().update()

    def _scroll_needed(self, row: int) -> int:
        """How far to scroll so that the whole drawer of ``row`` is in view (never past the row's own top)."""
        top = self._table.rowViewportPosition(row)
        bottom = top + self._base + self._full + 6
        overflow = bottom - self._view.height()
        return max(0, min(overflow, top - 4)) if overflow > 0 else 0

    # ------------------------------------------------------------------ geometry
    def _set_row_height(self, key: object, extra: int) -> None:
        row = self._row_of(key)
        if row >= 0:
            self._table.setRowHeight(row, self._base + max(0, extra))
            self._row_cache[key] = row

    def _place(self, *_args) -> None:
        """Put the clip (and the ghost) where their rows are."""
        table = self._table
        if self._key is not None:
            row = self._row_of(self._key)
            if row < 0:
                return
            top = table.rowViewportPosition(row) + self._base
            height = max(0, int(self._extra) - CARD_INSET)
            self._clip.setGeometry(0, top, self._view.width(), height)
            self._clip.setVisible(height > 0)
            if self._drawer.width() != self._view.width():
                self._drawer.setFixedWidth(self._view.width())
        if self._ghost_key is not None:
            row = self._row_of(self._ghost_key)
            if row >= 0:
                top = table.rowViewportPosition(row) + self._base
                height = max(0, int(self._ghost_extra) - CARD_INSET)
                self._ghost.setGeometry(0, top, self._ghost.full_width, height)
                self._ghost.setVisible(height > 0)

    def reposition(self) -> None:
        """The table was resized: the drawer may need another height for the new width."""
        if self._key is None:
            return
        full = self._height_for(self._view.width())
        if full != self._full:
            self._full = full
            self._drawer.setFixedHeight(full)
            if self._anim.state() != QVariantAnimation.State.Running:
                self._extra = float(full)
                self._set_row_height(self._key, full)
                self._table.updateGeometries()
        self._place()

    def refit(self) -> None:
        """The drawer's content changed height while it is open: grow or shrink the row to fit, smoothly."""
        if self._key is None or not self._table.isVisible():
            return self.reposition()
        full = self._height_for(self._view.width())
        if full == self._full:
            return
        if self._anim.state() == QVariantAnimation.State.Running and self._ghost_key is None:
            self._extra_from = self._extra               # re-aim a growing/shrinking row without restarting from zero
        else:
            self._finish_now()
            self._extra_from = self._extra = float(self._full)
        self._full = full
        self._drawer.setFixedHeight(full)
        row = self._row_of(self._key)
        self._scroll_from = self._table.verticalScrollBar().value()
        self._scroll_by = self._scroll_needed(row) if row >= 0 else 0
        self._run(REFIT_MS)

    # ------------------------------------------------------------- model changes
    def _resync(self, *_args) -> None:
        """Rows moved (sort, filter, reload): the open row has another index now, or is gone."""
        for key in (self._key, self._ghost_key):
            old = self._row_cache.get(key) if key is not None else None
            if old is not None and 0 <= old < self._table.model().rowCount():
                self._table.setRowHeight(old, self._base)           # whatever stood there is not tall any more
        if self._ghost_key is not None:
            if self._row_of(self._ghost_key) < 0:
                self._ghost_key, self._ghost_extra = None, 0.0
                self._ghost.hide()
            else:
                self._set_row_height(self._ghost_key, int(self._ghost_extra))
        if self._key is not None:
            if self._row_of(self._key) < 0:
                self._key, self._extra = None, 0.0
                self._clip.hide()
                self.closed.emit()
                return
            self._set_row_height(self._key, int(self._extra))
            self._table.updateGeometries()
        self._place()

    def _data_changed(self, top: QModelIndex, bottom: QModelIndex, *_roles) -> None:
        if self._key is None:
            return
        row = self._row_of(self._key)
        if top.row() <= row <= bottom.row():
            self.opened.emit(self._key)                              # the drawer re-reads its row
            self.reposition()                                        # ...which may need another height

    def shutdown(self) -> None:
        self._anim.stop()
