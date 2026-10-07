"""Paste proxies in any common format; see how many are readable before adding."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from antidetect.gui.components import BaseDialog, Segmented, Switch, label, set_role
from antidetect.i18n import tr
from antidetect.infrastructure.proxy.proxy_parser import parse_line

_PROTOCOLS = ("HTTP", "SOCKS5", "HTTPS")


class ProxyImportDialog(BaseDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(tr("imp.title"), tr("imp.hint"), parent, width=560)
        formats = QFrame()
        formats.setProperty("role", "tile")
        formats_layout = QVBoxLayout(formats)
        formats_layout.setContentsMargins(14, 10, 14, 10)
        sample = label(tr("imp.formats"), "small")
        sample.setStyleSheet("font-family: Menlo, Consolas, monospace;")
        formats_layout.addWidget(sample)
        self.body.addWidget(formats)

        self._text = QPlainTextEdit()
        self._text.setPlaceholderText(tr("imp.placeholder"))
        self._text.setMinimumHeight(170)
        self._text.textChanged.connect(self._refresh)
        self.body.addWidget(self._text, 1)

        type_row = QHBoxLayout()
        type_row.setSpacing(10)
        type_row.addWidget(label(tr("imp.type"), "field"))
        self._protocol = Segmented([(name, name) for name in _PROTOCOLS])
        type_row.addWidget(self._protocol)
        type_row.addStretch(1)
        self.body.addLayout(type_row)
        check_row = QHBoxLayout()
        check_row.setSpacing(10)
        self._check = Switch(True)
        check_row.addWidget(self._check)
        check_row.addWidget(label(tr("imp.check"), "muted"), 1)
        self.body.addLayout(check_row)
        self._preview = label("", "small")
        self.body.addWidget(self._preview)

        self.add_footer_button(tr("common.cancel"), None, self.reject)
        self._add = self.add_footer_button(tr("imp.add"), "primary", self.accept)
        self._add.setDefault(True)
        self._refresh()

    def _counts(self) -> tuple[int, int]:
        ok = bad = 0
        for line in self._text.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if parse_line(line) is None:
                bad += 1
            else:
                ok += 1
        return ok, bad

    def _refresh(self) -> None:
        ok, bad = self._counts()
        self._preview.setText(tr("imp.preview", ok=ok, bad=bad) if (ok or bad) else "")
        set_role(self._preview, "danger" if bad and not ok else "small")
        self._add.setEnabled(ok > 0)

    def text(self) -> str:
        return self._text.toPlainText()

    def protocol(self) -> str:
        return self._protocol.value() or "HTTP"

    def check_after(self) -> bool:
        return self._check.isChecked()
