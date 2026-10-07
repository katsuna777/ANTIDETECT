"""The Activity feed: a short, persistent record of what happened (profiles, proxies, tags, workspaces).

Unlike the technical log (``LogService``: English lines, wiped on every launch) an entry here is
structured — ``kind`` + ``subject`` + ``data`` — so the GUI writes the sentence in the user's language
when it shows the feed, and it survives restarts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from antidetect.domain.models.activity_entry import ActivityEntry

if TYPE_CHECKING:
    from antidetect.application.ports import ActivityRepository, SettingsRepository

SEEN_KEY = "seen.activity_id"

ACT = "act."          # every kind is the translation key of its sentence: ``act.<area>.<what happened>``

#: the filter groups of the page: which kinds belong to each
GROUPS: dict[str, tuple[str, ...]] = {
    "profiles": (ACT + "profile.", ACT + "trash."),
    "proxies": (ACT + "proxy.",),
    "organize": (ACT + "tag.", ACT + "workspace."),
}


class ActivityService:
    def __init__(self, repository: "ActivityRepository", settings: "SettingsRepository | None" = None) -> None:
        self._repository = repository
        self._settings = settings

    # -------------------------------------------------------------- writing
    def record(self, kind: str, subject: str = "", *, level: str = "INFO", **data) -> None:
        """Add a line. Reporting must never break the action it reports, so errors are swallowed."""
        try:
            self._repository.insert(
                ActivityEntry(id=0, ts=datetime.now(timezone.utc), kind=kind, subject=subject or "",
                              data={k: v for k, v in data.items() if v is not None}, level=level)
            )
        except Exception:
            pass

    # -------------------------------------------------------------- reading
    def list(self, *, before_id: int | None = None, after_id: int | None = None, limit: int = 200,
             group: str | None = None, errors_only: bool = False) -> list[ActivityEntry]:
        """Newest first; ``group`` is one of :data:`GROUPS` (``None`` = everything)."""
        return self._repository.list(
            before_id=before_id, after_id=after_id, limit=limit, prefixes=GROUPS.get(group or "", ()),
            level="ERROR" if errors_only else None,
        )

    def latest_id(self) -> int:
        return self._repository.latest_id()

    def unseen(self) -> int:
        """How many entries were added since the page was last opened."""
        return self._repository.count_after(self._seen_id())

    def unseen_errors(self) -> int:
        """...of which failures (a profile that could not start): the only thing worth interrupting for."""
        return self._repository.count_after(self._seen_id(), "ERROR")

    def mark_seen(self) -> None:
        if self._settings is not None:
            self._settings.set(SEEN_KEY, str(self._repository.latest_id()))

    def clear(self) -> int:
        removed = self._repository.clear()
        self.mark_seen()
        return removed

    def _seen_id(self) -> int:
        if self._settings is None:
            return 0
        setting = self._settings.get(SEEN_KEY)
        try:
            return int(setting.value) if setting is not None and setting.value else 0
        except ValueError:
            return 0
