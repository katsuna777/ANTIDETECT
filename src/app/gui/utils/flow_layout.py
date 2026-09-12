"""Wrapping row layout: widgets flow to the next line on narrow windows.

A plain QHBoxLayout squeezes children down to their minimum size and then
clips them off-screen. These control rows must survive small laptop windows,
so pairs (label + combo, buttons) wrap instead of sliding away.
Classic Qt flow-layout algorithm, dependency-free.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """Left-to-right layout that wraps into as many rows as needed."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 12) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt override
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802 - Qt override
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        size = QSize()
        for item in self._items:
            size = size.expandedTo(self._item_size(item))
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    # ------------------------------------------------------------ internals

    @staticmethod
    def _item_size(item) -> QSize:
        """Effective item size honoring hard constraints.

        Reads metrics off the widget itself: QWidgetItem.sizeHint() reports
        (0, 0) for parentless widgets on some Qt builds, which would collapse
        every row before the layout is installed into a page.
        """
        widget = item.widget()
        if widget is None:
            return item.sizeHint()
        return (
            widget.sizeHint()
            .expandedTo(widget.minimumSize())
            .boundedTo(widget.maximumSize())
        )

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins: QMargins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            widget = item.widget()
            # Explicitly hidden widgets take no space on screen. Height
            # queries run before the first show (when isHidden() is true
            # for everything), so the skip applies to placement only —
            # otherwise pre-show heights collapse to zero.
            if widget is not None and not test_only and widget.isHidden():
                continue
            # Respect hard constraints like a real layout engine does:
            # effective size = hint bounded by [minimum, maximum].
            item_hint = self._item_size(item)
            next_x = x + item_hint.width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + spacing
                next_x = x + item_hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_hint))
            x = next_x
            line_height = max(line_height, item_hint.height())
        return y + line_height - rect.y() + margins.top() + margins.bottom()


def make_flow_row(*widgets: QWidget, spacing: int = 12) -> FlowLayout:
    """Build a wrapping row out of widgets (labels stay glued to controls)."""
    row = FlowLayout(spacing=spacing)
    for widget in widgets:
        policy = widget.sizePolicy()
        # Never stretch across the whole row: wrapping only works when every
        # item keeps its own width.
        policy.setHorizontalPolicy(QSizePolicy.Policy.Maximum)
        widget.setSizePolicy(policy)
        row.addWidget(widget)
    return row
