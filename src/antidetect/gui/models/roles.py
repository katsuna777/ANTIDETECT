"""Custom item-data roles shared by the table models and their delegates."""

from PySide6.QtCore import Qt

ROW_ROLE = Qt.ItemDataRole.UserRole + 1     # the whole read-model row
SORT_ROLE = Qt.ItemDataRole.UserRole + 2
SUB_ROLE = Qt.ItemDataRole.UserRole + 3     # second line of a two-line cell
BUSY_ROLE = Qt.ItemDataRole.UserRole + 4    # "starting" | "stopping" | "checking" | None
CHIPS_ROLE = Qt.ItemDataRole.UserRole + 5   # tuple[str, ...] tag chips
CHECKING_ROLE = Qt.ItemDataRole.UserRole + 6   # bool: the row's proxy is being re-checked
