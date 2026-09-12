"""Placeholder page scaffold shared by the Stage-1 sections.

Each page keeps the same editorial skeleton — a kicker, a large title and a
hairline — and fills the middle with its own Stage-1 widgets. The scaffold
also provides a small metric strip so sections can show live aggregate counts
refreshed through background workers.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.gui.utils.flow_layout import make_flow_row


class Metric(QWidget):
    """A value + oversized label pair shown on the metric strip."""

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 30, 0)
        layout.setSpacing(0)

        self._value = QLabel("—")
        self._value.setObjectName("MetricValue")
        self._label = QLabel(label)
        self._label.setObjectName("MetricLabel")

        layout.addWidget(self._value)
        layout.addWidget(self._label)

    def set_value(self, text: str | int) -> None:
        self._value.setText(str(text))


class Hairline(QFrame):
    """The single 1px separator in the system."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Hairline")


class PlaceholderPage(QWidget):
    """Base class for the current placeholder screens."""

    def __init__(
        self,
        title: str,
        kicker: str = "SECTION",
        parent=None,
        scroll: bool = True,
    ) -> None:
        """Build the kicker/title/hairline skeleton.

        :param scroll: when False the body canvas is placed directly (no
            QScrollArea) — for short pages like Settings where everything
            must be visible at once.
        """
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(0)

        self._kicker_label = QLabel(kicker.upper())
        self._kicker_label.setObjectName("PageKicker")
        outer.addWidget(self._kicker_label)
        outer.addSpacing(4)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("PageTitle")
        outer.addWidget(self._title_label)
        outer.addSpacing(12)

        rule = Hairline()
        outer.addWidget(rule)
        # Air between the header hairline and the first content block:
        # QFrame contentsMargins do NOT create layout spacing, so an
        # explicit gap is needed — otherwise group boxes stick to the rule.
        outer.addSpacing(28)

        self._canvas = QWidget()
        self._body = QVBoxLayout(self._canvas)
        self._body.setContentsMargins(0, 4, 0, 0)
        self._body.setSpacing(24)
        if scroll:
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll_area.setWidget(self._canvas)
            outer.addWidget(scroll_area, 1)
        else:
            outer.addWidget(self._canvas, 1)

    # ------------------------------------------------------------ helpers

    def add_metrics(self, *labels: str) -> list[Metric]:
        """Append a horizontal metric strip; returns the created Metrics."""
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(24)
        metrics = [Metric(label) for label in labels]
        for metric in metrics:
            strip.addWidget(metric)
        strip.addStretch(1)
        self._body.addLayout(strip)
        return metrics

    def add_control_row(self, *widgets: QWidget, stretch: bool = True) -> QHBoxLayout:
        """Pack a row of controls under the metrics."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for widget in widgets:
            row.addWidget(widget)
        if stretch:
            row.addStretch(1)
        self._body.addLayout(row)
        return row

    def add_flow_row(self, *widgets: QWidget, spacing: int = 12):
        """Pack a wrapping row: items flow to the next line on narrow windows.

        Use for long control strips ( Combos + buttons) so nothing slides
        off-screen — the horizontal scrollbar is disabled on every page.
        """
        row = make_flow_row(*widgets, spacing=spacing)
        self._body.addLayout(row)
        return row

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self._body.addWidget(widget, stretch)

    def add_stretch(self) -> None:
        self._body.addStretch(1)

    def make_empty_state(self, text: str) -> QLabel:
        """A centered monochrome hint shown when a list has no rows."""
        label = QLabel(text)
        label.setObjectName("EmptyState")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def make_hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("HintLabel")
        label.setWordWrap(True)
        return label