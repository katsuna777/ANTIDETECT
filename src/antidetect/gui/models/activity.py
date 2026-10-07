"""The Activity feed as a list: day headers and one row per event, with the sentence written in the UI language."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from antidetect.application.activity_service import ACT
from antidetect.domain.models.activity_entry import ActivityEntry
from antidetect.gui.models.profiles import date_label
from antidetect.gui.models.rows import local_time
from antidetect.i18n import tr

ITEM_ROLE = Qt.ItemDataRole.UserRole + 1

_STYLE = {                    # kind -> (icon, tone)
    "act.profile.created": ("plus", "success"),
    "act.profile.updated": ("edit", "muted"),
    "act.profile.started": ("play", "success"),
    "act.profile.stopped": ("stop", "muted"),
    "act.profile.start_failed": ("alert", "danger"),
    "act.profile.trashed": ("trash", "warning"),
    "act.profile.restored": ("rotate-ccw", "success"),
    "act.profile.purged": ("trash", "danger"),
    "act.profile.duplicated": ("copy", "accent"),
    "act.browser.installed": ("download", "success"),
    "act.profile.imported": ("download", "accent"),
    "act.profile.exported": ("upload", "muted"),
    "act.profile.tagged": ("tag", "accent"),
    "act.profile.moved": ("briefcase", "accent"),
    "act.trash.emptied": ("trash", "danger"),
    "act.trash.expired": ("clock", "warning"),
}
_PREFIX_STYLE = ((ACT + "tag.", ("tag", "accent")), (ACT + "workspace.", ("briefcase", "accent")),
                 (ACT + "proxy.", ("globe", "muted")), (ACT + "trash.", ("trash", "muted")))

_FIELDS = {"name": "act.field.name", "notes": "act.field.notes", "tags": "act.field.tags", "proxy": "act.field.proxy"}


def style_of(kind: str) -> tuple[str, str]:
    """(icon, tone) of an entry."""
    style = _STYLE.get(kind)
    if style is not None:
        return style
    return next((s for prefix, s in _PREFIX_STYLE if kind.startswith(prefix)), ("activity", "muted"))


def describe(entry: ActivityEntry) -> tuple[str, str]:
    """(sentence, detail line) in the current language."""
    kind, data = entry.kind, entry.data
    params = {"name": entry.subject, "old": "", "source": "", "count": 0, "added": 0, "existing": 0, "working": 0,
              "checked": 0, "days": 0, "collected": 0, **{k: v for k, v in data.items() if not isinstance(v, (list, dict))}}
    detail = ""
    if kind == "act.profile.updated":
        fields = data.get("fields") or []
        if "name" in fields and data.get("old"):
            kind = "act.profile.renamed"
            fields = [f for f in fields if f != "name"]
        detail = ", ".join(tr(_FIELDS[f]) for f in fields if f in _FIELDS)
    elif kind == "act.profile.stopped" and data.get("closed"):
        kind = "act.profile.closed"
    elif kind == "act.profile.start_failed":
        detail = str(data.get("error") or "")
    elif kind == "act.profile.moved":
        if not entry.subject:
            kind = "act.profile.unmoved"
        detail = ", ".join(data.get("names") or [])
    elif kind == "act.profile.tagged":
        added, removed = data.get("added") or [], data.get("removed") or []
        detail = "  ".join(x for x in ("+ " + ", ".join(added) if added else "", "− " + ", ".join(removed) if removed else "") if x)
    elif kind == "act.proxy.imported" and data.get("invalid"):
        detail = tr("act.detail.unreadable", n=data["invalid"])
    elif kind == "act.tag.deleted" and data.get("profiles"):
        detail = tr("act.detail.profiles", n=data["profiles"])
    elif kind == "act.workspace.deleted" and data.get("profiles"):
        detail = tr("act.detail.profiles", n=data["profiles"])
    return tr(kind, **params), detail


def day_label(day: date, today: date | None = None) -> str:
    today = today or date.today()
    if day == today:
        return tr("act.today")
    if day == today - timedelta(days=1):
        return tr("act.yesterday")
    return date_label(datetime.combine(day, datetime.min.time()))


def time_label(moment: datetime | None) -> str:
    local = local_time(moment)
    return local.strftime("%H:%M") if local is not None else ""


@dataclass(frozen=True)
class Item:
    """A row of the list: a day header (``entry`` is None) or an event."""

    day: date
    entry: ActivityEntry | None = None
    title: str = ""
    detail: str = ""
    icon: str = ""
    tone: str = ""
    time: str = ""


class ActivityModel(QAbstractListModel):
    """Newest first. ``set_entries`` / ``prepend`` / ``append`` keep the loaded entries; the list is rebuilt from them."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[ActivityEntry] = []
        self._items: list[Item] = []
        self._text = ""

    # ----------------------------------------------------------------- entries
    def entries(self) -> list[ActivityEntry]:
        return self._entries

    def oldest_id(self) -> int | None:
        return self._entries[-1].id if self._entries else None

    def newest_id(self) -> int:
        return self._entries[0].id if self._entries else 0

    def set_entries(self, entries: list[ActivityEntry]) -> None:
        self._entries = list(entries)
        self._rebuild()

    def prepend(self, entries: list[ActivityEntry]) -> None:
        known = {e.id for e in self._entries}
        fresh = [e for e in entries if e.id not in known]
        if fresh:
            self._entries = sorted(fresh + self._entries, key=lambda e: -e.id)
            self._rebuild()

    def append(self, entries: list[ActivityEntry]) -> None:
        known = {e.id for e in self._entries}
        older = [e for e in entries if e.id not in known]
        if older:
            self._entries = self._entries + sorted(older, key=lambda e: -e.id)
            self._rebuild()

    def set_text(self, text: str) -> None:
        self._text = (text or "").strip().casefold()
        self._rebuild()

    def retranslate(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        items: list[Item] = []
        last_day: date | None = None
        for entry in self._entries:
            title, detail = describe(entry)
            if self._text and self._text not in f"{title} {detail}".casefold():
                continue
            local = local_time(entry.ts)
            day = local.date() if local is not None else date.today()
            if day != last_day:
                items.append(Item(day))
                last_day = day
            icon, tone = style_of(entry.kind)
            items.append(Item(day, entry, title, detail, icon, "danger" if entry.level == "ERROR" else tone,
                              time_label(entry.ts)))
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    # ---------------------------------------------------------------- Qt model
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == ITEM_ROLE:
            return self._items[index.row()]
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled if index.isValid() else Qt.ItemFlag.NoItemFlags
