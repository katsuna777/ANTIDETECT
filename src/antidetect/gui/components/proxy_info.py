"""What a profile's proxy is, at a glance: where it exits, how to reach it, how healthy it is."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from antidetect.gui.components.basics import Button, IconLabel, divider, label
from antidetect.gui.components.popover import Popover
from antidetect.gui.countries import country_name
from antidetect.gui.models.profiles import relative_label
from antidetect.gui.models.rows import ProfileRow
from antidetect.gui.theme import current_palette
from antidetect.i18n import tr


class FlagLabel(QWidget):
    def __init__(self, code: str | None, size: int = 30) -> None:
        super().__init__()
        self._code, self._size = code, size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802
        from antidetect.gui.views.paint import draw_flag

        painter = QPainter(self)
        draw_flag(painter, self._size / 2, self._size / 2, self._code, current_palette(), self._size)


class _Line(QWidget):
    def __init__(self, icon: str, key: str, value: str, *, tone: str | None = None) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(IconLabel(icon, "muted", 16))
        row.addWidget(label(key))
        row.addStretch(1)
        self.value = label(value, tone or "muted")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.value)


class ProxyInfoPopover(Popover):
    """Anchored under the (i) button of a profile row."""

    checkRequested = Signal()

    def __init__(self, row: ProfileRow, parent: QWidget | None = None) -> None:
        super().__init__(parent, width=330)
        self._row = row
        code = row.proxy_country_code
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(FlagLabel(code, 32))
        names = QVBoxLayout()
        names.setSpacing(1)
        where = country_name(code, row.proxy_country) if (code or row.proxy_country) else tr("proxy.info.unknown")
        names.addWidget(label(where, "h2"))
        names.addWidget(label(row.proxy_endpoint or "", "small"))
        head.addLayout(names, 1)
        protocol = QLabel((row.proxy_protocol or "").lower())
        protocol.setProperty("role", "pill")
        head.addWidget(protocol, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(head)
        self.body.addWidget(divider())

        status = (row.proxy_status or "UNKNOWN").upper()
        tone = {"WORKING": "success", "DEAD": "danger", "ERROR": "warning"}.get(status)
        lines = [
            ("globe", tr("proxy.info.host"), row.proxy_endpoint or "—", None),
            ("lock", tr("proxy.info.auth"), row.proxy_username or tr("proxy.info.noauth"), None),
            ("clock", tr("proxy.info.timezone"), row.timezone or "—", None),
            ("check-circle", tr("proxy.info.status"), tr(f"proxy.status.{status.lower()}"), tone),
        ]
        if row.proxy_latency:
            lines.append(("arrow-up-down", tr("col.ping"), f"{row.proxy_latency} ms", None))
        lines.append(("refresh", tr("proxy.info.checked"),
                      relative_label(row.proxy_checked_at) if row.proxy_checked_at else tr("common.never"), None))
        for icon, key, value, line_tone in lines:
            self.body.addWidget(_Line(icon, key, value, tone=line_tone))
        if row.proxy_free:
            note = label(tr("proxy.free.warn.text"), "small", wrap=True)
            note.setProperty("role", "warning")
            self.body.addWidget(divider())
            self.body.addWidget(note)

        self.body.addWidget(divider())
        actions = QHBoxLayout()
        actions.setSpacing(8)
        check = Button(tr("proxy.info.check"), "soft", icon="refresh", size="sm")
        check.clicked.connect(self._check)
        copy = Button(tr("proxy.menu.copy"), "soft", icon="copy", size="sm")
        copy.clicked.connect(self._copy)
        actions.addWidget(check)
        actions.addWidget(copy)
        actions.addStretch(1)
        self.body.addLayout(actions)

    def _check(self) -> None:
        self.checkRequested.emit()
        self.close()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._row.proxy_endpoint or "")
        self.close()
