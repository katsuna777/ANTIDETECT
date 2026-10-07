"""Settings-style rows: a title and description on the left, the controls on the right, grouped in a card."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from antidetect.gui.components.basics import Card, divider, label


class SettingRow(QWidget):
    """A setting: title and description on the left, the control on the right."""

    def __init__(self, title: str, description: str, *controls: QWidget, stacked: bool = False) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = label(title, "h3")
        self.description = label(description, "small", wrap=True)
        texts.addWidget(self.title)
        texts.addWidget(self.description)
        row.addLayout(texts, 1)
        outer.addLayout(row)
        target = QHBoxLayout() if stacked else row
        target.setSpacing(8)
        for control in controls:
            target.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        if stacked:
            target.addStretch(1)
            outer.addLayout(target)

    def set_texts(self, title: str, description: str) -> None:
        self.title.setText(title)
        self.description.setText(description)


class SettingGroup(QWidget):
    """A small caption over a card whose rows are split by hairlines."""

    def __init__(self, title: str) -> None:
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        self.caption = label(title.upper(), "section")
        self.caption.setVisible(bool(title))        # a group without a title is just the card
        col.addWidget(self.caption)
        self.card = Card()
        col.addWidget(self.card)
        self._rows = 0

    def add(self, row: QWidget) -> None:
        if self._rows:
            self.card.body.addWidget(divider())
        self.card.body.addWidget(row)
        self._rows += 1

    def clear(self) -> None:
        """Remove every row (the card is about to be filled again)."""
        while self.card.body.count():
            item = self.card.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()                 # deleteLater() is deferred: until then it would still be painted
                widget.setParent(None)
                widget.deleteLater()
        self._rows = 0

    def set_title(self, title: str) -> None:
        self.caption.setText(title.upper())
        self.caption.setVisible(bool(title))
