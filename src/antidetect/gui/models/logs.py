"""A bounded, virtual list model for the log view (appends are O(1) row inserts)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt

LEVELS = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3}
MAX_LINES = 5000

LINE_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True, slots=True)
class LogLine:
    id: int
    clock: str
    level: int            # 0 debug · 1 info · 2 warn · 3 error
    source: str
    message: str
    haystack: str         # lower-cased text the search box matches against


def level_of(entry) -> int:
    raw = str(getattr(getattr(entry, "level", None), "value", getattr(entry, "level", "INFO"))).upper()
    return LEVELS.get(raw, 1)


def make_line(entry) -> LogLine:
    stamp = getattr(entry, "ts", None)
    clock = stamp.strftime("%H:%M:%S") if isinstance(stamp, datetime) else str(stamp or "")[-12:-4]
    source = str(getattr(entry, "source", ""))
    message = str(getattr(entry, "message", ""))
    return LogLine(
        id=getattr(entry, "id", 0), clock=clock, level=level_of(entry), source=source,
        message=message, haystack=f"{clock} {source} {message}".casefold(),
    )


def format_line(line: LogLine) -> str:
    names = {0: "DEBUG", 1: "INFO", 2: "WARN", 3: "ERROR"}
    return f"{line.clock}  {names[line.level]:<5}  {line.source}: {line.message}"


class LogModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lines: list[LogLine] = []
        self.last_id = 0

    def append(self, entries) -> None:
        lines = [make_line(e) for e in entries]
        if not lines:
            return
        self.last_id = max(self.last_id, max(line.id for line in lines))
        start = len(self._lines)
        self.beginInsertRows(QModelIndex(), start, start + len(lines) - 1)
        self._lines.extend(lines)
        self.endInsertRows()
        overflow = len(self._lines) - MAX_LINES
        if overflow > 0:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            del self._lines[:overflow]
            self.endRemoveRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._lines.clear()
        self.last_id = 0
        self.endResetModel()

    def lines(self) -> list[LogLine]:
        return self._lines

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._lines)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._lines)):
            return None
        line = self._lines[index.row()]
        if role == LINE_ROLE:
            return line
        if role == Qt.ItemDataRole.DisplayRole:
            return format_line(line)
        return None


class LogFilter(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._minimum = 0
        self._needle = ""

    def set_level(self, minimum: int) -> None:
        self._minimum = minimum or 0
        self._refilter()

    def set_text(self, text: str) -> None:
        self._needle = (text or "").strip().casefold()
        self._refilter()

    def _refilter(self) -> None:
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:  # pragma: no cover - older Qt
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:  # noqa: N802
        line: LogLine = self.sourceModel().index(source_row, 0).data(LINE_ROLE)
        if line is None or line.level < self._minimum:
            return False
        return not self._needle or self._needle in line.haystack
