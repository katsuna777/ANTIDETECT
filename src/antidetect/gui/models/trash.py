"""Qt model for the trash: the profiles that were deleted, newest first."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt

from antidetect.gui.models.base import RowsModel
from antidetect.gui.models.profiles import OS_NAMES, absolute_label, count_text
from antidetect.gui.models.roles import CHIPS_ROLE, ROW_ROLE, SORT_ROLE, SUB_ROLE
from antidetect.gui.models.rows import ProfileRow
from antidetect.i18n import tr

COL_NAME, COL_DELETED, COL_LEFT, COL_COOKIES, COL_ACTIONS = range(5)
COLUMN_COUNT = 5


def days_left(row: ProfileRow, retention_days: int, now: datetime | None = None) -> int | None:
    """Whole days until the profile is deleted for good (``None`` = never: the retention is off)."""
    if retention_days <= 0 or row.deleted_at is None:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0, retention_days - (now - row.deleted_at).days)


class TrashModel(RowsModel[ProfileRow]):
    COLUMNS = COLUMN_COUNT
    HEADERS = {COL_NAME: "col.name", COL_DELETED: "col.deleted", COL_LEFT: "col.left", COL_COOKIES: "col.cookies",
               COL_ACTIONS: ""}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self.retention_days = 30
        self._sort_column, self._sort_order = COL_DELETED, Qt.SortOrder.DescendingOrder

    def set_text(self, text: str) -> None:
        self._text = (text or "").strip().casefold()
        self.refilter()

    def set_retention(self, days: int) -> None:
        self.retention_days = days
        self.refresh_column(COL_LEFT)

    def accepts(self, row: ProfileRow) -> bool:
        if not self._text:
            return True
        return self._text in " ".join([row.name, row.notes, " ".join(row.tags)]).casefold()

    def sort_key(self, row: ProfileRow, column: int):
        if column == COL_NAME:
            return row.name.casefold()
        if column == COL_COOKIES:
            return -1 if row.cookie_count is None else row.cookie_count
        return row.deleted_at.timestamp() if row.deleted_at else 0.0     # deleted / left: the same order

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row, column = self._rows[index.row()], index.column()
        if role == ROW_ROLE:
            return row
        if role == SUB_ROLE and column == COL_NAME:
            return " · ".join(part for part in (OS_NAMES.get(row.platform or ""), row.browser) if part)
        if role == CHIPS_ROLE and column == COL_NAME:
            return row.tags
        if role == SORT_ROLE:
            return self.sort_key(row, column)
        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_NAME:
                return row.name
            if column == COL_DELETED:
                return absolute_label(row.deleted_at)
            if column == COL_LEFT:
                left = days_left(row, self.retention_days)
                return tr("trash.keep") if left is None else tr("trash.left", n=left)
            if column == COL_COOKIES:
                return count_text(row.cookie_count)
        return None
