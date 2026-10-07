"""Create several profiles at once: one name with numbers, one system, one proxy each."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from antidetect.application.bulk_service import MAX_COUNT, BulkRequest, numbered_names
from antidetect.application.fingerprint import data as fd
from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.gui.catalog import Catalog
from antidetect.gui.components import BaseDialog, Cards, Segmented, Select, Switch, label, repolish, set_role
from antidetect.gui.components.tags import TagField, workspace_icon
from antidetect.gui.dialogs.profile import _OS_GLYPH, _OS_LABEL, _OS_ORDER, _PROTOCOLS, _captioned, _page, _scrolling
from antidetect.i18n import tr
from antidetect.infrastructure.proxy.proxy_parser import parse_line

BODY_HEIGHT = 520


def proxy_lines(text: str) -> list[str]:
    """The lines of a pasted proxy list that carry a proxy (blank lines and ``#`` comments do not)."""
    return [line.strip() for line in (text or "").splitlines() if line.strip() and not line.strip().startswith("#")]


class BulkDialog(BaseDialog):
    def __init__(self, existing_names: set[str], catalog: Catalog, *, default_workspace: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(tr("bulk.title"), tr("bulk.subtitle"), parent=parent, width=620)
        self._catalog = catalog
        self._taken = set(existing_names)
        self._platform = fd.host_platform()

        page, col = _page()
        col.setContentsMargins(0, 8, 0, 4)

        # ---- name and how many
        self._name = QLineEdit(tr("bulk.name.default"))
        self._count = QLineEdit("10")
        self._count.setValidator(QIntValidator(1, MAX_COUNT, self))
        self._count.setFixedWidth(96)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addLayout(_captioned(tr("field.name"), self._name), 1)
        row.addLayout(_captioned(tr("bulk.count"), self._count), 0)
        col.addLayout(row)
        self._preview = label("", "small")
        col.addWidget(self._preview)

        # ---- system
        self._os = Cards([(key, tr(_OS_LABEL[key]), _OS_GLYPH[key]) for key in _OS_ORDER], self._platform)
        for key, button in self._os.buttons().items():
            button.clicked.connect(lambda _=False, k=key: setattr(self, "_platform", k))
        col.addSpacing(14)
        col.addWidget(label(tr("field.os"), "field"))
        col.addSpacing(2)
        col.addWidget(self._os)

        # ---- proxies
        self._proxies = QPlainTextEdit()
        self._proxies.setPlaceholderText(tr("bulk.proxies.placeholder"))
        self._proxies.setFixedHeight(76)
        self._protocol = Segmented([(name, name) for name in _PROTOCOLS])     # for lines that don't say which type
        caption = QHBoxLayout()
        caption.setSpacing(10)
        caption.addWidget(label(tr("bulk.proxies"), "field"), 1)
        caption.addWidget(self._protocol)
        col.addSpacing(14)
        col.addLayout(caption)
        col.addSpacing(4)
        col.addWidget(self._proxies)
        self._proxy_note = label("", "small", wrap=True)
        col.addSpacing(6)
        col.addWidget(self._proxy_note)

        # ---- where they go
        self._workspace = None
        if catalog.workspaces:
            self._workspace = Select()
            self._workspace.fit_to_width(16)
            self._workspace.addItem(workspace_icon(None), tr("workspace.none"), None)
            for item in catalog.workspaces:
                self._workspace.addItem(workspace_icon(item.color, item.name), item.name, item.id)
            if not self._workspace.select_data(default_workspace):
                self._workspace.setCurrentIndex(0)
        self._tags = TagField(catalog)
        col.addSpacing(14)
        where = QHBoxLayout()
        where.setSpacing(14)
        cells = []
        if self._workspace is not None:
            cells.append((_captioned(tr("drawer.workspace"), self._workspace), 2))
        cells.append((_captioned(tr("field.tags"), self._tags), 3))
        for cell, stretch in cells:
            where.addLayout(cell, stretch)
            where.setAlignment(cell, Qt.AlignmentFlag.AlignTop)       # the captions share one line
        col.addLayout(where)

        # ---- geo
        col.addSpacing(14)
        tile = QFrame()                                        # one line: the long explanation is the tooltip
        tile.setProperty("role", "tile")
        tile.setToolTip(tr("geo.hint"))
        tile_row = QHBoxLayout(tile)
        tile_row.setContentsMargins(16, 12, 16, 12)
        tile_row.setSpacing(16)
        tile_row.addWidget(label(tr("field.geo"), "h3"), 1)
        self._geo = Switch(True)
        tile_row.addWidget(self._geo, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addWidget(tile)
        col.addStretch(1)

        area = _scrolling(page)
        area.setFixedHeight(BODY_HEIGHT)
        self.body.addWidget(area)
        self.add_footer_button(tr("common.cancel"), None, self.reject)
        self._create = self.add_footer_button("", "primary", self.accept)
        self._create.setDefault(True)

        for edit in (self._name, self._count):
            edit.textChanged.connect(self._refresh)
        self._proxies.textChanged.connect(self._refresh)
        self._protocol.changed.connect(lambda _key: self._refresh())
        self._refresh()

    # ------------------------------------------------------------------ state
    def _how_many(self) -> int:
        try:
            return int(self._count.text())
        except ValueError:
            return 0

    def _protocol_value(self) -> ProxyProtocol:
        try:
            return ProxyProtocol[(self._protocol.value() or "HTTP").upper()]
        except KeyError:
            return ProxyProtocol.HTTP

    def proxy_summary(self) -> tuple[int, int]:
        """(proxies that can be read and are different, lines that cannot be read)."""
        usable: set[tuple] = set()
        unreadable = 0
        for text in proxy_lines(self._proxies.toPlainText()):
            entry = parse_line(text, self._protocol_value())
            if entry is None:
                unreadable += 1
            else:
                usable.add(entry.dedupe_key())
        return len(usable), unreadable

    def _refresh(self) -> None:
        count = self._how_many()
        name = " ".join(self._name.text().split())
        valid_count = 1 <= count <= MAX_COUNT
        self._count.setProperty("invalid", not valid_count)
        repolish(self._count)
        self._name.setProperty("invalid", not name)
        repolish(self._name)

        if name and valid_count:
            names = numbered_names(name, count, self._taken)
            self._preview.setText(", ".join(names) if count <= 3 else f"{names[0]}, {names[1]} … {names[-1]}")
        else:
            self._preview.setText(tr("err.bulk.count", max=MAX_COUNT) if not valid_count else "")

        usable, unreadable = self.proxy_summary()
        if usable == 0 and unreadable == 0:
            text, role = tr("bulk.proxies.none"), "small"
        elif valid_count and usable < count:
            text, role = tr("bulk.proxies.short", have=usable, n=count, missing=count - usable), "warning"
        elif valid_count and usable > count:
            text, role = tr("bulk.proxies.extra", extra=usable - count), "success"
        else:
            text, role = tr("bulk.proxies.enough"), "success"
        if unreadable:
            text = f"{text} {tr('bulk.proxies.invalid', k=unreadable)}"
            role = "danger"
        self._proxy_note.setText(text)
        set_role(self._proxy_note, role)

        self._create.setText(tr("bulk.create", n=count) if valid_count else tr("bulk.create.none"))
        self._create.setEnabled(bool(name) and valid_count and unreadable == 0)

    # ----------------------------------------------------------------- result
    def request(self) -> BulkRequest:
        return BulkRequest(
            name=" ".join(self._name.text().split()),
            count=self._how_many(),
            platform=self._platform,
            proxy_text="\n".join(proxy_lines(self._proxies.toPlainText())),
            proxy_protocol=self._protocol_value().value,
            workspace_id=self._workspace.currentData() if self._workspace is not None else None,
            tags=tuple(self._tags.tags()),
            geo_auto=self._geo.isChecked(),
        )
