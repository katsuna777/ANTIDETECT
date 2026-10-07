from __future__ import annotations

from datetime import datetime


class Tag:
    """A label the user created once and hands out to profiles (``color`` is a palette slot)."""

    __slots__ = ("id", "name", "color", "created_at")

    def __init__(self, id: int, name: str, color: int = 0, created_at: datetime | None = None) -> None:
        self.id = id
        self.name = name
        self.color = color
        self.created_at = created_at

    def __repr__(self) -> str:
        return f"Tag(id={self.id}, name={self.name!r}, color={self.color})"


class Workspace:
    """A group of profiles (a client, a project, a team); a profile is in at most one."""

    __slots__ = ("id", "name", "color", "created_at")

    def __init__(self, id: int, name: str, color: int = 0, created_at: datetime | None = None) -> None:
        self.id = id
        self.name = name
        self.color = color
        self.created_at = created_at

    def __repr__(self) -> str:
        return f"Workspace(id={self.id}, name={self.name!r}, color={self.color})"
