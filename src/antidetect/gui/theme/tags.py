"""Colours of tags and workspaces.

The database stores a *slot* (0-11); this module turns it into a colour. ``Catalog`` registers
the slot of every tag by name (``register``), so the table, the sidebar and quick search all paint
a tag the same way without asking the database. A name nobody has registered yet falls back to a
slot derived from the name.
"""

from __future__ import annotations

import zlib
from typing import Iterable

from antidetect.application.palette import SLOTS

#: slot -> colour. The first ten are the colours the app has always used (a remembered tag keeps its look).
_HUES = (
    "#E5484D",   # 0  red
    "#F5A524",   # 1  amber
    "#30A46C",   # 2  green
    "#3E63DD",   # 3  blue
    "#8E4EC6",   # 4  violet
    "#12A594",   # 5  teal
    "#D6409F",   # 6  magenta
    "#7C8794",   # 7  slate
    "#0090FF",   # 8  sky
    "#A18072",   # 9  brown
    "#F76B15",   # 10 orange
    "#6E56CF",   # 11 indigo
)
assert len(_HUES) == SLOTS

_slots: dict[str, int] = {}


def slot_color(slot: int) -> str:
    return _HUES[slot % SLOTS]


def _fallback(key: str) -> int:
    return zlib.crc32(key.encode("utf-8")) % SLOTS


def tag_color(tag: str) -> str:
    key = (tag or "").strip().casefold()
    slot = _slots.get(key)
    return slot_color(_fallback(key) if slot is None else slot)


def register(tags: Iterable[tuple[str, int]]) -> None:
    """Replace the known tags: ``(name, slot)`` pairs."""
    _slots.clear()
    for name, slot in tags:
        _slots[(name or "").strip().casefold()] = int(slot) % SLOTS


def colors() -> tuple[str, ...]:
    """Every colour of the palette, in slot order (the swatches of the colour pickers)."""
    return _HUES
