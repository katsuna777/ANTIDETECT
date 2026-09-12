"""Lightweight GUI read-models consumed by pages after a worker returns.

These are plain immutable value objects — not Qt models — passed through
worker signals so pages can update their labels and controls in a single
atomic slot.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntitySummary:
    """Snapshot of aggregate counts, rebuilt every time a page reloads."""

    profiles: int = 0
    running_profiles: int = 0
    proxies: int = 0
    working_proxies: int = 0
    configurations: int = 0