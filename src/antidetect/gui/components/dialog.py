"""Dialog base class plus ready-made confirm and error dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from antidetect.gui.components.basics import Button, IconLabel, divider, label
from antidetect.i18n import tr


class BaseDialog(QDialog):
    """Title row, a body you fill, and a right-aligned footer with a divider above it."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None, *,
                 width: int = 520, padding: int = 24, lead: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        self.title_label = label(title, "h2")
        self.title_label.setStyleSheet("font-size: 18px;")
        head.addWidget(self.title_label)
        self.subtitle_label = label(subtitle, "subtitle", wrap=True)
        self.subtitle_label.setVisible(bool(subtitle))
        head.addWidget(self.subtitle_label)
        top = QHBoxLayout()                      # an optional tile (the profile's avatar) before the texts
        top.setContentsMargins(padding, padding - 2, padding, 12)
        top.setSpacing(14)
        if lead is not None:
            top.addWidget(lead, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addLayout(head, 1)
        outer.addLayout(top)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(padding, 4, padding, padding - 6)
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)
        outer.addWidget(divider())
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(padding, 14, padding, 16)
        self.footer.setSpacing(8)
        self.footer.addStretch(1)
        outer.addLayout(self.footer)

    def add_footer_button(self, text: str, variant: str | None = None, callback=None) -> Button:
        btn = Button(text, variant)
        if callback is not None:
            btn.clicked.connect(callback)
        self.footer.addWidget(btn)
        return btn


class ConfirmDialog(BaseDialog):
    def __init__(self, parent: QWidget | None, title: str, text: str, confirm_text: str, *, danger: bool = False) -> None:
        super().__init__(title, parent=parent, width=440)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(IconLabel("alert" if danger else "info", "danger" if danger else "accent", 22), 0, Qt.AlignmentFlag.AlignTop)
        message = label(text, "muted", wrap=True)
        row.addWidget(message, 1)
        self.body.addLayout(row)
        self.add_footer_button(tr("common.cancel"), None, self.reject)
        self.confirm_button = self.add_footer_button(confirm_text, "danger-solid" if danger else "primary", self.accept)
        self.confirm_button.setDefault(True)


def confirm(parent: QWidget | None, title: str, text: str, confirm_text: str, *, danger: bool = False) -> bool:
    return ConfirmDialog(parent, title, text, confirm_text, danger=danger).exec() == QDialog.DialogCode.Accepted


class ErrorDialog(BaseDialog):
    """A plain-language message with the technical details one click away."""

    def __init__(self, parent: QWidget | None, message: str, details: str,
                 actions: list[tuple[str, object]] | None = None) -> None:
        super().__init__(tr("app.title"), parent=parent, width=560)
        self.chosen_action = None
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(IconLabel("alert", "warning", 22), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(label(message, wrap=True), 1)
        self.body.addLayout(row)
        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setProperty("role", "mono")
        self.details.setFixedHeight(150)
        self.details.setVisible(False)
        self.body.addWidget(self.details)
        self._toggle = Button(tr("error.details"), "link")
        self._toggle.clicked.connect(self._toggle_details)
        self.footer.insertWidget(0, self._toggle)
        copy = self.add_footer_button(tr("common.copy"), None, lambda: QGuiApplication.clipboard().setText(details))
        copy.setVisible(False)
        self._copy = copy
        for text, callback in actions or []:
            self.add_footer_button(text, None, lambda _=False, cb=callback: self._run(cb))
        close = self.add_footer_button(tr("common.close"), "primary", self.accept)
        close.setDefault(True)

    def _toggle_details(self) -> None:
        shown = not self.details.isVisible()
        self.details.setVisible(shown)
        self._copy.setVisible(shown)
        self.adjustSize()

    def _run(self, callback) -> None:
        self.chosen_action = callback
        self.accept()
