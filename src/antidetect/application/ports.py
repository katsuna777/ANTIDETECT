"""Ports (abstract contracts) used by the application layer.

Infrastructure implementations (SQLite repositories, ChromiumManager) satisfy
these contracts. The application layer depends only on these abstractions, so
the future GUI can reuse the exact same business logic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from antidetect.domain.enums.profile_status import ProfileStatus
from antidetect.domain.enums.proxy_status import ProxyStatus
from antidetect.domain.models.app_setting import AppSetting
from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.domain.models.profile import Profile
from antidetect.domain.models.proxy import Proxy, ProxyWithCheck
from antidetect.domain.models.proxy_check import ProxyCheck
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.domain.models.activity_entry import ActivityEntry
from antidetect.domain.models.log_entry import LogEntry
from antidetect.domain.models.tag import Tag, Workspace


@runtime_checkable
class ProfileRepository(Protocol):
    def create(
        self,
        name: str,
        profile_path: str,
        configuration_id: int,
        created_at: datetime,
        proxy_id: int | None = None,
        *,
        notes: str = "",
        tags: list[str] | None = None,
        geo_auto: bool = True,
        start_url: str | None = None,
        workspace_id: int | None = None,
    ) -> Profile: ...

    def get(self, profile_id: int) -> Profile | None:
        """The profile, whether it is alive or in the trash."""

    def list(self) -> list[Profile]:
        """Profiles that are not in the trash."""

    def list_all(self) -> list[Profile]:
        """Every profile, the trash included."""

    def list_trashed(self) -> list[Profile]: ...

    def count_trashed(self) -> int: ...

    def trash(self, profile_ids: list[int], moment: datetime) -> int: ...

    def restore(self, profile_id: int, name: str | None = None) -> Profile | None: ...

    def set_workspace(self, profile_ids: list[int], workspace_id: int | None) -> int: ...

    def find_by_name(self, name: str) -> Profile | None: ...

    def update(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        profile_path: str | None = None,
        configuration_id: int | None = None,
        proxy_id: int | None = None,
        notes: str | None = None,
        tags: list[str] | None = None,
        geo_auto: bool | None = None,
        start_url: str | None = None,
    ) -> Profile | None: ...

    def set_configuration(
        self, profile_id: int, configuration_id: int | None
    ) -> Profile | None:
        """Explicitly set the profile's configuration (None removes it)."""

    def set_proxy(self, profile_id: int, proxy_id: int | None) -> Profile | None:
        """Explicitly set the profile's proxy (None removes it)."""

    def update_runtime(
        self,
        profile_id: int,
        *,
        status: ProfileStatus,
        pid: int | None = None,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> None: ...

    def delete(self, profile_id: int) -> bool: ...


@runtime_checkable
class BrowserConfigurationRepository(Protocol):
    def create(
        self,
        name: str,
        *,
        user_agent: str | None = None,
        platform: str | None = None,
        language: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        screen_width: int | None = None,
        screen_height: int | None = None,
        device_pixel_ratio: float | None = None,
        color_depth: int | None = None,
        webgl_settings: dict | None = None,
        hardware_settings: dict | None = None,
        privacy_settings: dict | None = None,
    ) -> BrowserConfiguration: ...

    def get(self, configuration_id: int) -> BrowserConfiguration | None: ...

    def list(self) -> list[BrowserConfiguration]: ...

    def find_by_name(self, name: str) -> BrowserConfiguration | None: ...

    def get_default(self) -> BrowserConfiguration | None: ...

    def update(
        self,
        configuration_id: int,
        *,
        name: str | None = None,
        user_agent: str | None = None,
        platform: str | None = None,
        language: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        screen_width: int | None = None,
        screen_height: int | None = None,
        device_pixel_ratio: float | None = None,
        color_depth: int | None = None,
        webgl_settings: dict | None = None,
        hardware_settings: dict | None = None,
        privacy_settings: dict | None = None,
    ) -> BrowserConfiguration | None: ...

    def delete(self, configuration_id: int) -> bool: ...


@runtime_checkable
class SettingsRepository(Protocol):
    def get(self, key: str) -> AppSetting | None: ...

    def set(self, key: str, value: str | None) -> None: ...

@runtime_checkable
class BrowserManager(Protocol):
    """Controls a single Chromium process instance bound to a profile data dir."""

    def start(
        self,
        profile_path: Path,
        configuration: BrowserConfiguration,
        proxy: Proxy | None = None,
        start_url: str | None = None,
    ) -> int:
        """Launch the browser; returns the OS pid of the new process.

        When ``proxy`` is provided the browser routes all traffic through it.
        ``start_url`` opens that page instead of the saved/new-tab session.
        """

    def stop(self, profile_path: Path, pid: int, timeout: float = 10.0) -> None: ...

    def is_running(self, profile_path: Path, pid: int | None) -> bool: ...

    def open_url(self, pid: int, url: str) -> bool:
        """Open ``url`` in a new tab of the running browser; False if unsupported."""
        ...


@runtime_checkable
class ProxyRepository(Protocol):
    def keys(self) -> set[tuple[str, str, int]]: ...

    def ids_for_keys(self, keys: Iterable[tuple[str, str, int]]) -> dict[tuple[str, str, int], int]: ...

    def get(self, proxy_id: int) -> Proxy | None: ...

    def list(self) -> list[Proxy]: ...

    def list_for_check(self, stale_before: datetime | None = None) -> list[Proxy]: ...

    def list_with_latest_check(
        self,
        status: ProxyStatus | None = None,
        limit: int | None = None,
        proxy_ids: list[int] | None = None,
    ) -> list[ProxyWithCheck]: ...

    def upsert_many(self, entries: list[ProxyEntry]) -> int: ...

    def apply_outcomes(
        self, updates: list[tuple[int, ProxyStatus, int, datetime]]
    ) -> None: ...

    def delete(self, proxy_id: int) -> bool: ...

    def delete_many(self, proxy_ids: list[int]) -> int: ...

    def delete_all(self) -> int: ...

    def delete_dead(self) -> int: ...


@runtime_checkable
class ProxyCheckRepository(Protocol):
    def insert_many(self, checks: list[ProxyCheck]) -> None: ...

    def latest_for(self, proxy_id: int) -> ProxyCheck | None: ...


@runtime_checkable
class TagRepository(Protocol):
    def list(self) -> list[Tag]: ...

    def get(self, tag_id: int) -> Tag | None: ...

    def find(self, name: str) -> Tag | None: ...

    def create(self, name: str, color: int) -> Tag: ...

    def rename(self, tag_id: int, name: str) -> Tag | None: ...

    def set_color(self, tag_id: int, color: int) -> Tag | None: ...

    def delete(self, tag_id: int) -> bool: ...


@runtime_checkable
class WorkspaceRepository(Protocol):
    def list(self) -> list[Workspace]: ...

    def get(self, workspace_id: int) -> Workspace | None: ...

    def find(self, name: str) -> Workspace | None: ...

    def counts(self) -> dict[int | None, int]: ...

    def create(self, name: str, color: int) -> Workspace: ...

    def rename(self, workspace_id: int, name: str) -> Workspace | None: ...

    def set_color(self, workspace_id: int, color: int) -> Workspace | None: ...

    def delete(self, workspace_id: int) -> bool: ...


@runtime_checkable
class ActivityRepository(Protocol):
    def insert(self, entry: ActivityEntry) -> int: ...

    def list(self, *, before_id: int | None = None, after_id: int | None = None, limit: int = 200,
             prefixes: tuple[str, ...] = (), level: str | None = None) -> list[ActivityEntry]: ...

    def latest_id(self) -> int: ...

    def count_after(self, after_id: int, level: str | None = None) -> int: ...

    def trim(self, keep: int) -> int: ...

    def clear(self) -> int: ...


@runtime_checkable
class ActivitySink(Protocol):
    """Where services report what happened, for the Activity page (never raises)."""

    def record(self, kind: str, subject: str = "", *, level: str = "INFO", **data) -> None: ...


@runtime_checkable
class LogRepository(Protocol):
    """The persistence half of the log stream (SQLite-backed in production)."""

    def insert(self, entry: LogEntry) -> int: ...

    def insert_many(self, entries: list[LogEntry]) -> int: ...

    def list_after(self, after_id: int = 0, limit: int = 5000) -> list[LogEntry]: ...

    def all(self, limit: int = 100_000) -> list[LogEntry]: ...

    def latest_id(self) -> int: ...

    def count(self) -> int: ...

    def clear(self) -> int: ...


@runtime_checkable
class LogSink(Protocol):
    """The write half of the log stream consumed by services/browser manager.

    Services depend on this narrow interface (never the concrete
    ``LogService``), so business logic stays testable with a no-op sink.
    """

    def log(
        self,
        level: str,
        source: str,
        message: str,
        extra: dict | None = None,
    ) -> None: ...

    def info(self, source: str, message: str, extra: dict | None = None) -> None: ...

    def warn(self, source: str, message: str, extra: dict | None = None) -> None: ...

    def error(self, source: str, message: str, extra: dict | None = None) -> None: ...

    def debug(self, source: str, message: str, extra: dict | None = None) -> None: ...