"""Qt model for the profiles table: rows, busy markers, filter and sort."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt

from antidetect.gui.models.base import RowsModel
from antidetect.gui.models.roles import BUSY_ROLE, CHECKING_ROLE, CHIPS_ROLE, ROW_ROLE, SORT_ROLE, SUB_ROLE
from antidetect.gui.models.rows import NO_WORKSPACE, ProfileRow, local_time, relative_time
from antidetect.i18n import is_ru, tr

COL_PLAY, COL_NAME, COL_PROXY, COL_STATUS, COL_COOKIES, COL_LAST, COL_CREATED, COL_MORE = range(8)
COLUMN_COUNT = 8
COL_ACTION = COL_PLAY    # the column whose button starts / stops the profile

OS_NAMES = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}
CREATED_DAYS = {"today": 0, "week": 7, "month": 30}


def relative_label(moment: datetime | None) -> str:
    rel = relative_time(moment)
    if rel is None:
        return tr("common.never")
    unit, amount = rel
    if unit == "now":
        return tr("time.now")
    return tr(f"time.{unit}", n=amount)


def absolute_label(moment: datetime | None) -> str:
    """``05.10.2026 17:19`` (``10/05/2026 17:19`` in English), in local time."""
    local = local_time(moment)
    if local is None:
        return "—"
    return local.strftime("%d.%m.%Y %H:%M" if is_ru() else "%m/%d/%Y %H:%M")


def date_label(moment: datetime | None) -> str:
    """``05.10.2026`` (``10/05/2026`` in English), in local time."""
    local = local_time(moment)
    if local is None:
        return "—"
    return local.strftime("%d.%m.%Y" if is_ru() else "%m/%d/%Y")


def when_label(moment: datetime | None) -> str:
    """'5 min ago' for the last day, the date after that, 'Never' before the first run."""
    if moment is None:
        return tr("common.never")
    rel = relative_time(moment)
    return relative_label(moment) if rel is not None and rel[0] != "days" else date_label(moment)


def status_text(row: ProfileRow, busy: str | None) -> str:
    if busy == "starting":
        return tr("status.starting")
    if busy == "stopping":
        return tr("status.stopping")
    if busy == "preparing":
        return tr("status.preparing")
    return tr("status.running") if row.running else tr("status.stopped")


def count_text(value: int | None) -> str:
    """``1 153`` — thin-grouped so a long count stays readable inside a small pill."""
    return "—" if value is None else f"{value:,}".replace(",", " ")


class ProfilesModel(RowsModel[ProfileRow]):
    COLUMNS = COLUMN_COUNT
    HEADERS = {
        COL_PLAY: "",
        COL_NAME: "col.name",
        COL_PROXY: "col.proxy",
        COL_STATUS: "col.status",
        COL_COOKIES: "col.cookies",
        COL_LAST: "col.lastrun",
        COL_CREATED: "col.created",
        COL_MORE: "",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy: dict[int, str] = {}
        self._checking: set[int] = set()
        self._text = ""
        self._state: str | None = None            # "running" | "stopped" | None
        self._tag: str | None = None
        self._platforms: frozenset[str] = frozenset()
        self._proxy: str | None = None            # "with" | "without" | None
        self._cookies: str | None = None          # "with" | "without" | None
        self._created: str | None = None          # "today" | "week" | "month" | None
        self._workspace: int | None = None        # None = all, NO_WORKSPACE, or a workspace id
        self._sort_column, self._sort_order = COL_NAME, Qt.SortOrder.AscendingOrder

    # ------------------------------------------------------------------ busy markers
    def _rows_replaced(self) -> None:
        alive = {r.id for r in self._all}
        self._busy = {k: v for k, v in self._busy.items() if k in alive}
        self._checking &= alive

    def set_busy(self, profile_id: int, state: str | None) -> None:
        if state is None:
            self._busy.pop(profile_id, None)
        else:
            self._busy[profile_id] = state
        for position, row in enumerate(self._rows):
            if row.id == profile_id:
                self.dataChanged.emit(self.index(position, 0), self.index(position, COLUMN_COUNT - 1))
                return

    def busy(self, profile_id: int) -> str | None:
        return self._busy.get(profile_id)

    def set_checking(self, profile_id: int, checking: bool) -> None:
        """The row's proxy is being re-checked (its refresh button spins)."""
        (self._checking.add if checking else self._checking.discard)(profile_id)
        for position, row in enumerate(self._rows):
            if row.id == profile_id:
                self.dataChanged.emit(self.index(position, COL_PROXY), self.index(position, COL_PROXY))
                return

    def checking(self, profile_id: int) -> bool:
        return profile_id in self._checking

    def has_busy(self) -> bool:
        return bool(self._busy) or bool(self._checking)

    def running_ids(self) -> frozenset[int]:
        return frozenset(r.id for r in self._all if r.running)

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self._all:
            for tag in row.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    # ------------------------------------------------------------------ filter
    def set_text(self, text: str) -> None:
        self._text = (text or "").strip().casefold()
        self.refilter()

    def set_state(self, state: str | None) -> None:
        self._state = state
        self.refilter()

    def set_tag(self, tag: str | None) -> None:
        self._tag = tag
        self.refilter()

    def set_platforms(self, platforms) -> None:
        self._platforms = frozenset(platforms)
        self.refilter()

    def set_proxy(self, mode: str | None) -> None:
        self._proxy = mode
        self.refilter()

    def set_cookies(self, mode: str | None) -> None:
        self._cookies = mode
        self.refilter()

    def set_created(self, period: str | None) -> None:
        self._created = period
        self.refilter()

    def set_workspace(self, workspace: int | None) -> None:
        self._workspace = workspace
        self.refilter()

    def clear_filters(self) -> None:
        self._text, self._state, self._tag, self._platforms, self._proxy = "", None, None, frozenset(), None
        self._cookies, self._created, self._workspace = None, None, None
        self.refilter()

    def active_filters(self) -> int:
        """How many of the popover's filters are on (the search box, the tag and the workspace are shown elsewhere)."""
        return ((self._state is not None) + bool(self._platforms) + (self._proxy is not None)
                + (self._cookies is not None) + (self._created is not None))

    def cookies_filter(self) -> str | None:
        return self._cookies

    def created_filter(self) -> str | None:
        return self._created

    def workspace_filter(self) -> int | None:
        return self._workspace

    def workspace_counts(self) -> dict[int | None, int]:
        counts: dict[int | None, int] = {}
        for row in self._all:
            counts[row.workspace_id] = counts.get(row.workspace_id, 0) + 1
        return counts

    def state_filter(self) -> str | None:
        return self._state

    def platform_filter(self) -> frozenset[str]:
        return self._platforms

    def proxy_filter(self) -> str | None:
        return self._proxy

    def tag_filter(self) -> str | None:
        return self._tag

    def accepts(self, row: ProfileRow) -> bool:
        if self._state == "running" and not row.running:
            return False
        if self._state == "stopped" and row.running:
            return False
        if self._tag and self._tag.casefold() not in {t.casefold() for t in row.tags}:
            return False
        if self._platforms and (row.platform or "") not in self._platforms:
            return False
        if self._proxy == "with" and row.proxy_endpoint is None:
            return False
        if self._proxy == "without" and row.proxy_endpoint is not None:
            return False
        if self._cookies == "with" and not row.cookie_count:
            return False
        if self._cookies == "without" and row.cookie_count:
            return False
        if self._workspace is not None and (
                row.workspace_id is not None if self._workspace == NO_WORKSPACE else row.workspace_id != self._workspace):
            return False
        if self._created is not None:
            created = local_time(row.created_at)
            if created is None or created.date() < self._created_since():
                return False
        if self._text:
            haystack = " ".join(
                [row.name, row.notes, " ".join(row.tags), row.proxy_endpoint or "",
                 row.proxy_country or "", row.platform or "", row.timezone or ""]
            ).casefold()
            return self._text in haystack
        return True

    def _created_since(self) -> date:
        return date.today() - timedelta(days=CREATED_DAYS.get(self._created or "", 0))

    # ------------------------------------------------------------------ sort
    def sort_key(self, row: ProfileRow, column: int):
        name = row.name.casefold()
        if column == COL_NAME:
            return name
        if column in (COL_PLAY, COL_STATUS):
            return (0 if row.running else 1, name)
        if column == COL_PROXY:
            return (row.proxy_endpoint is None, row.proxy_endpoint or "")
        if column == COL_COOKIES:
            return -1 if row.cookie_count is None else row.cookie_count
        if column == COL_LAST:
            return row.last_started_at.timestamp() if row.last_started_at else 0.0
        if column == COL_CREATED:
            return row.created_at.timestamp() if row.created_at else 0.0
        return row.id

    # ------------------------------------------------------------------ Qt data
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == ROW_ROLE:
            return row
        busy = self._busy.get(row.id)
        if role == BUSY_ROLE:
            return busy
        if role == CHECKING_ROLE:
            return row.id in self._checking
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, column, busy)
        if role == SUB_ROLE:
            return self._sub(row, column)
        if role == CHIPS_ROLE and column == COL_NAME:
            return row.tags
        if role == SORT_ROLE:
            return self.sort_key(row, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(row, column, busy)
        return None

    @staticmethod
    def _display(row: ProfileRow, column: int, busy: str | None) -> str:
        if column == COL_NAME:
            return row.name
        if column == COL_STATUS:
            return status_text(row, busy)
        if column == COL_PROXY:
            return row.proxy_endpoint or tr("proxy.none")
        if column == COL_COOKIES:
            return count_text(row.cookie_count)
        if column == COL_LAST:
            return when_label(row.last_started_at)
        if column == COL_CREATED:
            return date_label(row.created_at)
        return ""

    @staticmethod
    def _sub(row: ProfileRow, column: int) -> str:
        if column == COL_NAME:
            return " · ".join(part for part in (OS_NAMES.get(row.platform or ""), row.browser) if part)
        if column == COL_PROXY:
            if not row.proxy_endpoint:
                return ""
            parts = []
            if row.proxy_country_code or row.proxy_country:
                parts.append((row.proxy_country_code or row.proxy_country or "").upper())
            if row.proxy_latency:
                parts.append(f"{row.proxy_latency} ms")
            return " · ".join(parts)
        return ""

    @staticmethod
    def _tooltip(row: ProfileRow, column: int, busy: str | None) -> str | None:
        if column == COL_PLAY:
            return tr("action.stop") if row.running else tr("action.start")
        if column == COL_NAME:
            lines = [row.name, *([row.notes] if row.notes else []), row.user_agent or ""]
            extras = [x for x in (row.gpu, f"{row.cores} cores" if row.cores else None,
                                  f"{row.memory_gb} GB" if row.memory_gb else None) if x]
            if extras:
                lines.append(" · ".join(extras))
            if row.screen:
                lines.append(row.screen)
            if row.timezone:
                lines.append(f"{row.timezone} · {row.locale or ''}".strip(" ·"))
            return "\n".join(line for line in lines if line)
        if column == COL_PROXY:
            if not row.proxy_endpoint:
                return tr("proxy.none.tip")
            return None   # the proxy cell has its own buttons with their own tips
        if column == COL_COOKIES:
            return tr("cookies.tip")
        if column == COL_LAST:
            return relative_label(row.last_started_at)
        return None
