"""Before a profile is exported: what goes into the file, and whether its proxy does."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from antidetect.gui.components import BaseDialog, Callout, Switch, label
from antidetect.i18n import tr


class ExportDialog(BaseDialog):
    """``include_proxy`` is only offered when the profile has one, and is off unless asked for:
    the login and password are written into the file as plain text."""

    def __init__(self, profile_name: str, has_proxy: bool, parent: QWidget | None = None) -> None:
        super().__init__(tr("export.title"), profile_name, parent=parent, width=520)
        note = Callout("accent", "info")
        note.set_content(tr("export.cookies"), title=tr("export.what"))
        self.body.addWidget(note)

        self._proxy = Switch(False)
        self._proxy.setVisible(has_proxy)
        if has_proxy:
            tile = QFrame()
            tile.setProperty("role", "tile")
            row = QHBoxLayout(tile)
            row.setContentsMargins(16, 14, 16, 14)
            row.setSpacing(16)
            texts = QVBoxLayout()
            texts.setSpacing(3)
            texts.addWidget(label(tr("export.proxy"), "h3"))
            texts.addWidget(label(tr("export.proxy.hint"), "small", wrap=True))
            row.addLayout(texts, 1)
            row.addWidget(self._proxy)
            self.body.addWidget(tile)
        self.add_footer_button(tr("common.cancel"), None, self.reject)
        choose = self.add_footer_button(tr("export.choose"), "primary", self.accept)
        choose.setDefault(True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self) -> None:
        """A wrapped text is as tall as its width allows, which a dialog only knows once it is shown."""
        layout = self.layout()
        if layout is not None:
            self.setMinimumHeight(layout.totalHeightForWidth(self.width()))
            self.adjustSize()

    @property
    def include_proxy(self) -> bool:
        return self._proxy.isChecked()
