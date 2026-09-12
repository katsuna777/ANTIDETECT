"""Wrapping row layout: widgets flow to the next line on narrow windows.

A plain QHBoxLayout squeezes children down to their minimum size and then
clips them off-screen. These control rows must survive small laptop windows,
so pairs (label + combo, buttons) wrap instead of sliding away.
Classic Qt flow-layout algorithm, dependency-free.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget


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
        spacing = self.spacing()
        # First pass: split items into lines. Second pass (placement only)
        # centers every item vertically within its line, so short labels sit
        # on the same axis as tall combos instead of floating at the top.
        lines: list[tuple[list, int, int]] = []
        current: list = []
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            widget = item.widget()
            # Hidden widgets take no space on screen. Height queries run
            # before the first show (when isHidden() is true for
            # everything), so the skip applies to placement only.
            if widget is not None and not test_only and widget.isHidden():
                continue
            size = self._item_size(item)
            width, height = size.width(), size.height()
            if x + width > effective.right() and current:
                lines.append((current, y, line_height))
                y += line_height + spacing
                x = effective.x()
                line_height = 0
                current = []
            current.append((item, x, width, height))
            x += width + spacing
            line_height = max(line_height, height)
        if current:
            lines.append((current, y, line_height))
            y += line_height
        if not test_only:
            for line_items, line_y, line_h in lines:
                for item, item_x, width, height in line_items:
                    item.setGeometry(
                        QRect(
                            QPoint(item_x, line_y + (line_h - height) // 2),
                            QSize(width, height),
                        )
                    )
        return y - rect.y() + margins.top() + margins.bottom()


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


def glued_pair(label: QWidget, control: QWidget, spacing: int = 6) -> QWidget:
    """Glue a label to its control so a line break never splits them.

    Use for ``Label + ComboBox`` pairs inside flow rows: without this the
    label can end one line while its combo starts the next.
    """
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return box
