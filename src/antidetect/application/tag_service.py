"""Tags: created once, then handed out to profiles.

The registry (name + colour) is a table of its own; the profile keeps its tag *names* in
``profiles.tags``, so scripts, the CLI and the API can keep reading and writing plain names. This
service keeps both in step: renaming a tag rewrites the profiles that carry it, deleting one strips it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from antidetect.application import palette
from antidetect.domain.errors import TagAlreadyExistsError, TagNotFoundError
from antidetect.domain.models.tag import Tag

if TYPE_CHECKING:
    from antidetect.application.ports import ActivitySink, LogSink, ProfileRepository, TagRepository

MAX_NAME = 40


def clean_name(name: str) -> str:
    """A tag name as stored: no commas (they separate the names on a profile), single spaces, bounded."""
    return " ".join(str(name or "").replace(",", " ").split())[:MAX_NAME]


@dataclass(frozen=True)
class TagInfo:
    tag: Tag
    count: int          # live (not trashed) profiles that carry it


class TagService:
    def __init__(self, tags: "TagRepository", profiles: "ProfileRepository",
                 activity: "ActivitySink | None" = None, log_sink: "LogSink | None" = None) -> None:
        self._tags = tags
        self._profiles = profiles
        self._activity = activity
        self._log = log_sink

    # ------------------------------------------------------------------ reads
    def list_tags(self) -> list[TagInfo]:
        counts: dict[str, int] = {}
        for profile in self._profiles.list():
            for name in profile.tags:
                counts[name.casefold()] = counts.get(name.casefold(), 0) + 1
        return [TagInfo(tag, counts.get(tag.name.casefold(), 0)) for tag in self._tags.list()]

    def get_tag(self, tag_id: int) -> Tag:
        tag = self._tags.get(tag_id)
        if tag is None:
            raise TagNotFoundError(tag_id)
        return tag

    # ----------------------------------------------------------------- writes
    def create_tag(self, name: str, color: int | None = None) -> Tag:
        name = clean_name(name)
        if not name:
            raise ValueError("Tag name must not be empty.")
        if self._tags.find(name) is not None:
            raise TagAlreadyExistsError(name)
        tag = self._tags.create(name, self._pick_color(color, name))
        self._report("act.tag.created", tag.name)
        return tag

    def rename_tag(self, tag_id: int, name: str) -> Tag:
        current = self.get_tag(tag_id)
        name = clean_name(name)
        if not name:
            raise ValueError("Tag name must not be empty.")
        clash = self._tags.find(name)
        if clash is not None and clash.id != tag_id:
            raise TagAlreadyExistsError(name)
        if name == current.name:
            return current
        renamed = self._tags.rename(tag_id, name)
        old = current.name.casefold()
        for profile in self._profiles.list_all():
            if any(t.casefold() == old for t in profile.tags):
                self._profiles.update(profile.id, tags=[name if t.casefold() == old else t for t in profile.tags])
        self._report("act.tag.renamed", name, old=current.name)
        return renamed  # type: ignore[return-value]

    def set_color(self, tag_id: int, color: int) -> Tag:
        self.get_tag(tag_id)
        updated = self._tags.set_color(tag_id, color % palette.SLOTS)
        return updated  # type: ignore[return-value]

    def delete_tag(self, tag_id: int) -> int:
        """Remove the tag from the registry and from every profile; returns how many profiles carried it."""
        tag = self.get_tag(tag_id)
        key, affected = tag.name.casefold(), 0
        for profile in self._profiles.list_all():
            if any(t.casefold() == key for t in profile.tags):
                self._profiles.update(profile.id, tags=[t for t in profile.tags if t.casefold() != key])
                affected += 1
        self._tags.delete(tag_id)
        self._report("act.tag.deleted", tag.name, profiles=affected)
        return affected

    def ensure(self, names: Iterable[str]) -> list[str]:
        """Register the names that are new and return all of them in their canonical spelling.

        A script that sends ``"work"`` for a tag the user created as ``"Work"`` gets ``"Work"`` back,
        and a name nobody has used before becomes a tag of its own (so it shows up in the GUI).
        """
        known = {tag.name.casefold(): tag for tag in self._tags.list()}
        out: list[str] = []
        for raw in names:
            name = clean_name(raw)
            if not name:
                continue
            tag = known.get(name.casefold())
            if tag is None:
                tag = self._tags.create(name, self._pick_color(None, name, taken=[t.color for t in known.values()]))
                known[name.casefold()] = tag
                self._report("act.tag.created", tag.name)
            if tag.name not in out:
                out.append(tag.name)
        return out

    def assign(self, profile_ids: list[int], *, add: Iterable[str] = (), remove: Iterable[str] = ()) -> int:
        """Add and remove tags on many profiles at once; returns how many profiles changed."""
        added = self.ensure(add)
        dropped = {clean_name(n).casefold() for n in remove}
        changed = 0
        for profile_id in profile_ids:
            profile = self._profiles.get(profile_id)
            if profile is None:
                continue
            tags = [t for t in profile.tags if t.casefold() not in dropped]
            for name in added:
                if all(t.casefold() != name.casefold() for t in tags):
                    tags.append(name)
            if tags != list(profile.tags):
                self._profiles.update(profile_id, tags=tags)
                changed += 1
        if changed:
            self._report("act.profile.tagged", "", count=changed, added=added, removed=sorted(dropped))
        return changed

    # ---------------------------------------------------------------- helpers
    def _pick_color(self, color: int | None, name: str, taken: list[int] | None = None) -> int:
        if color is not None:
            return int(color) % palette.SLOTS
        used = taken if taken is not None else [t.color for t in self._tags.list()]
        return palette.least_used(used, start=sum(map(ord, name.casefold())) % palette.SLOTS)

    def _report(self, kind: str, subject: str, **data) -> None:
        if self._activity is not None:
            self._activity.record(kind, subject, **data)
        if self._log is not None:
            self._log.info("tags", f"{kind} {subject}".strip())
