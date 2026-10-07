from datetime import datetime
from typing import Optional

from antidetect.domain.enums.profile_status import ProfileStatus


class Profile:
    """Immutable representation of a stored browser profile."""

    __slots__ = (
        "id",
        "name",
        "profile_path",
        "configuration_id",
        "proxy_id",
        "status",
        "created_at",
        "updated_at",
        "last_started_at",
        "last_stopped_at",
        "pid",
        "notes",
        "tags",
        "geo_auto",
        "start_url",
        "workspace_id",
        "deleted_at",
    )

    def __init__(
        self,
        id: int,
        name: str,
        profile_path: str,
        configuration_id: int,
        proxy_id: Optional[int] = None,
        status: ProfileStatus = ProfileStatus.STOPPED,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        last_started_at: Optional[datetime] = None,
        last_stopped_at: Optional[datetime] = None,
        pid: Optional[int] = None,
        notes: str = "",
        tags: Optional[list[str]] = None,
        geo_auto: bool = True,
        start_url: Optional[str] = None,
        workspace_id: Optional[int] = None,
        deleted_at: Optional[datetime] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.profile_path = profile_path
        self.configuration_id = configuration_id
        self.proxy_id = proxy_id
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.last_started_at = last_started_at
        self.last_stopped_at = last_stopped_at
        self.pid = pid
        self.notes = notes or ""
        self.tags = list(tags or [])
        self.geo_auto = bool(geo_auto)
        self.start_url = start_url or None
        self.workspace_id = workspace_id
        self.deleted_at = deleted_at      # set while the profile is in the trash

    @property
    def is_trashed(self) -> bool:
        return self.deleted_at is not None

    def replace(self, **changes) -> "Profile":
        values = {
            "id": self.id,
            "name": self.name,
            "profile_path": self.profile_path,
            "configuration_id": self.configuration_id,
            "proxy_id": self.proxy_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_started_at": self.last_started_at,
            "last_stopped_at": self.last_stopped_at,
            "pid": self.pid,
            "notes": self.notes,
            "tags": list(self.tags),
            "geo_auto": self.geo_auto,
            "start_url": self.start_url,
            "workspace_id": self.workspace_id,
            "deleted_at": self.deleted_at,
        }
        values.update(changes)
        return Profile(**values)

    def __repr__(self) -> str:
        return (
            f"Profile(id={self.id}, name={self.name!r}, status={self.status.value}, "
            f"profile_path={self.profile_path!r}, proxy_id={self.proxy_id})"
        )