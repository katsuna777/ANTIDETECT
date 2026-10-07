"""Qt model + filter for the proxies table."""

from __future__ import annotations

from PySide6.QtCore import Qt

from antidetect.gui.models.base import RowsModel
from antidetect.gui.models.roles import BUSY_ROLE, ROW_ROLE, SORT_ROLE, SUB_ROLE
from antidetect.gui.models.rows import ProxyRow
from antidetect.i18n import tr

COL_ADDRESS, COL_COUNTRY, COL_PING, COL_STATUS, COL_ANON, COL_SOURCE, COL_USED = range(7)
COLUMN_COUNT = 7

_STATUS_KEY = {"WORKING": "working", "DEAD": "dead", "UNKNOWN": "unknown", "ERROR": "error"}
_STATUS_ORDER = {"WORKING": 0, "UNKNOWN": 1, "ERROR": 2, "DEAD": 3}


def status_label(status: str) -> str:
    return tr(f"proxy.status.{_STATUS_KEY.get(status, 'unknown')}")


def anonymity_label(value: str | None) -> str:
    return tr(f"proxy.anon.{(value or 'unknown').lower()}")


class ProxiesModel(RowsModel[ProxyRow]):
    COLUMNS = COLUMN_COUNT
    HEADERS = {
        COL_ADDRESS: "col.address",
        COL_COUNTRY: "col.country",
        COL_PING: "col.ping",
        COL_STATUS: "col.status",
        COL_ANON: "col.anonymity",
        COL_SOURCE: "col.source",
        COL_USED: "col.usedby",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy: set[int] = set()
        self._text = ""
        self._sort_column, self._sort_order = COL_ADDRESS, Qt.SortOrder.AscendingOrder

    def set_busy(self, ids: set[int]) -> None:
        self._busy = set(ids)
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, COLUMN_COUNT - 1))

    def busy_ids(self) -> set[int]:
        return set(self._busy)

    def set_text(self, text: str) -> None:
        self._text = (text or "").strip().casefold()
        self.refilter()

    def accepts(self, row: ProxyRow) -> bool:
        if not self._text:
            return True
        haystack = " ".join(
            [row.address, row.protocol, row.country or "", row.country_code or "", " ".join(row.used_by)]
        ).casefold()
        return self._text in haystack

    def sort_key(self, row: ProxyRow, column: int):
        if column == COL_ADDRESS:
            return (row.host, row.port)
        if column == COL_COUNTRY:
            return row.country or "~"
        if column == COL_PING:
            return row.latency_ms if row.latency_ms else 10**9
        if column == COL_STATUS:
            return _STATUS_ORDER.get(row.status, 4)
        if column == COL_ANON:
            return anonymity_label(row.anonymity)
        if column == COL_SOURCE:
            return 0 if row.is_manual else 1
        return ", ".join(row.used_by)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == ROW_ROLE:
            return row
        checking = row.id in self._busy
        if role == BUSY_ROLE:
            return "checking" if checking else None
        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_ADDRESS:
                return row.address
            if column == COL_COUNTRY:
                return row.country or row.country_code or "—"
            if column == COL_PING:
                return f"{row.latency_ms} ms" if row.latency_ms else "—"
            if column == COL_STATUS:
                return tr("proxies.checking", done="…", total="") if checking else status_label(row.status)
            if column == COL_ANON:
                return anonymity_label(row.anonymity)
            if column == COL_SOURCE:
                return tr("proxy.source.manual") if row.is_manual else tr("proxy.source.pool")
            if column == COL_USED:
                return ", ".join(row.used_by) or "—"
        if role == SUB_ROLE and column == COL_ADDRESS:
            return row.protocol.lower() + (f" · {row.username}" if row.username else "")
        if role == SORT_ROLE:
            return self.sort_key(row, column)
        return None
