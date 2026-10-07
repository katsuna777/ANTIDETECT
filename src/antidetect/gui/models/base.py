"""A table model over immutable row objects that filters and sorts itself in plain Python.

A ``QSortFilterProxyModel`` calls back into Python for every comparison (and twice more for the
data behind it), which is ~0.5 s for 2000 rows. Sorting a list with a key function is a few
milliseconds for tens of thousands, so the model keeps ``_all`` (what the database returned)
and ``_rows`` (what is shown: filtered, then sorted) itself.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from antidetect.i18n import tr

R = TypeVar("R")


class RowsModel(QAbstractTableModel, Generic[R]):
    """Rows must be immutable, comparable and expose ``.id``.

    ``set_rows`` compares what would be shown with what is shown: when the same ids come back in
    the same order only the rows that differ emit ``dataChanged`` (nothing repaints needlessly).
    Any other change is a ``layoutChanged`` with the persistent indexes remapped by row id, so
    selection, current row and scroll position survive a filter, a sort or a refresh.

    Subclasses provide ``accepts(row)`` (filter) and ``sort_key(row, column)`` (sort).
    """

    COLUMNS = 0
    HEADERS: dict[int, str] = {}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all: list[R] = []
        self._rows: list[R] = []
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    # --------------------------------------------------------------- subclass hooks
    def accepts(self, row: R) -> bool:
        return True

    def sort_key(self, row: R, column: int):
        return row.id  # type: ignore[attr-defined]

    def _rows_replaced(self) -> None:
        """Hook: drop per-row state that no longer applies."""

    # ------------------------------------------------------------------ data
    def set_rows(self, rows: list[R]) -> None:
        self._all = list(rows)
        self._rows_replaced()
        self._rebuild()

    def refilter(self) -> None:
        """Re-run the filter and the sort (call after the filter state changed)."""
        self._rebuild()

    def _visible(self) -> list[R]:
        accepts = self.accepts
        rows = [row for row in self._all if accepts(row)]
        if self._sort_column >= 0:
            column = self._sort_column
            key = self.sort_key
            rows.sort(key=lambda row: key(row, column), reverse=self._sort_order == Qt.SortOrder.DescendingOrder)
        return rows

    def _rebuild(self) -> None:
        new = self._visible()
        old = self._rows
        if len(new) == len(old) and all(a.id == b.id for a, b in zip(old, new)):
            self._rows = new
            for position, (before, after) in enumerate(zip(old, new)):
                if before != after:
                    self.dataChanged.emit(self.index(position, 0), self.index(position, self.COLUMNS - 1))
            return
        self.layoutAboutToBeChanged.emit()
        persistent = self.persistentIndexList()
        ids = [old[index.row()].id if 0 <= index.row() < len(old) else None for index in persistent]
        self._rows = new
        position = {row.id: i for i, row in enumerate(new)}
        self.changePersistentIndexList(
            persistent,
            [self.index(position[i], index.column()) if i in position else QModelIndex()
             for i, index in zip(ids, persistent)],
        )
        self.layoutChanged.emit()

    def rows(self) -> list[R]:
        """Every row (ignoring the filter)."""
        return self._all

    def visible_rows(self) -> list[R]:
        return self._rows

    def total(self) -> int:
        return len(self._all)

    def row_at(self, position: int) -> R | None:
        return self._rows[position] if 0 <= position < len(self._rows) else None

    def position_of(self, row_id) -> int:
        """Where the row with this id is shown right now (-1 when it is not shown)."""
        for position, row in enumerate(self._rows):
            if row.id == row_id:                                  # type: ignore[attr-defined]
                return position
        return -1

    def refresh_column(self, column: int) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, column), self.index(len(self._rows) - 1, column))

    def retranslate(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, self.COLUMNS - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.COLUMNS - 1)

    # ----------------------------------------------------------- Qt interface
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # noqa: A003
        self._sort_column, self._sort_order = column, order
        self._rebuild()

    def sort_state(self) -> tuple[int, Qt.SortOrder]:
        return self._sort_column, self._sort_order

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else self.COLUMNS

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            key = self.HEADERS.get(section, "")
            return tr(key) if key else ""
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
