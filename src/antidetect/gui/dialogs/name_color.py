"""A small dialog: a name and a colour (a new or renamed tag, a new or edited workspace)."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QWidget

from antidetect.application import palette
from antidetect.gui.components import BaseDialog, label, repolish
from antidetect.gui.components.tags import SwatchRow
from antidetect.i18n import tr


class NameColorDialog(BaseDialog):
    """``name()`` and ``color()`` after ``exec()``; the confirm button is off while the name is empty or taken."""

    def __init__(self, title: str, *, name: str = "", color: int | None = None, taken: set[str] = frozenset(),
                 placeholder: str = "", confirm: str = "", used_colors: list[int] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(title, parent=parent, width=420)
        self._taken = {n.casefold() for n in taken if n.casefold() != name.casefold()}
        self.body.addWidget(label(tr("field.name"), "field"))
        self._name = QLineEdit(name)
        self._name.setPlaceholderText(placeholder)
        self._name.setMaxLength(40)
        self._name.textChanged.connect(self._validate)
        self.body.addWidget(self._name)
        self._error = label("", "danger")
        self._error.setVisible(False)
        self.body.addWidget(self._error)
        self.body.addSpacing(6)
        self.body.addWidget(label(tr("field.color"), "field"))
        self._swatches = SwatchRow(palette.least_used(used_colors or []) if color is None else color)
        self.body.addWidget(self._swatches)
        self.add_footer_button(tr("common.cancel"), None, self.reject)
        self._ok = self.add_footer_button(confirm or tr("common.save"), "primary", self.accept)
        self._ok.setDefault(True)
        self._validate()

    def _validate(self) -> None:
        text = " ".join(self._name.text().split())
        error = tr("err.name.empty") if not text else tr("err.name.exists") if text.casefold() in self._taken else ""
        self._error.setText(error)
        self._error.setVisible(bool(error) and bool(text))
        self._name.setProperty("invalid", bool(error) and bool(text))
        repolish(self._name)
        self._ok.setEnabled(not error)

    def name(self) -> str:
        return " ".join(self._name.text().replace(",", " ").split())

    def color(self) -> int:
        return self._swatches.value()
