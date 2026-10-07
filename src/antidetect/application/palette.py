"""Colour slots for tags and workspaces.

The database stores a slot number, never a colour: the GUI maps a slot to a hex value for the
current theme (``antidetect.gui.theme.tags``). New items get the least used slot, so the first
twelve are all different.
"""

from __future__ import annotations

from typing import Iterable

SLOTS = 12


def least_used(taken: Iterable[int], start: int = 0) -> int:
    """The slot used by the fewest of ``taken`` (ties: the first one at or after ``start``)."""
    used = [0] * SLOTS
    for slot in taken:
        if 0 <= slot < SLOTS:
            used[slot] += 1
    return min(range(SLOTS), key=lambda i: (used[i], (i - start) % SLOTS))
