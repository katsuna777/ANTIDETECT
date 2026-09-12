"""Ports (abstract contracts) used by the application layer.

Infrastructure implementations (SQLite repositories, ChromiumManager) satisfy
these contracts. The application layer depends only on these abstractions, so
the future GUI can reuse the exact same business logic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.enums.profile_status import ProfileStatus
from app.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from app.domain.models.app_setting import AppSetting
from app.domain.models.browser_configuration import BrowserConfiguration
from app.domain.models.profile import Profile
from app.domain.models.proxy import Proxy, ProxyWithCheck
from app.domain.models.proxy_check import ProxyCheck
from app.domain.models.proxy_entry import ProxyEntry
from app.domain.models.log_entry import LogEntry


@runtime_checkable
class ProfileRepository(Protocol):
    def create(
        self,
        name: str,
        profile_path: str,
        configuration_id: int,
        created_at: datetime,
        proxy_id: int | None = None,
    ) -> Profile: ...

    def get(self, profile_id: int) -> Profile | None: ...

    def list(self) -> list[Profile]: ...

    def find_by_name(self, name: str) -> Profile | None: ...

    def update(
        self,
        profile_id: int,
        *,
        name: str | None = None,
        profile_path: str | None = None,
        configuration_id: int | None = None,
        proxy_id: int | None = None,
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
    ) -> BrowserConfiguration | None: ...

    def delete(self, configuration_id: int) -> bool: ...


@runtime_checkable
class SettingsRepository(Protocol):
    def get(self, key: str) -> AppSetting | None: ...

    def set(self, key: str, value: str | None) -> None: ...

    def get_int(self, key: str, default: int) -> int: ...


@runtime_checkable
class BrowserManager(Protocol):
    """Controls a single Chromium process instance bound to a profile data dir."""

    def start(
        self,
        profile_path: Path,
        configuration: BrowserConfiguration,
        proxy: Proxy | None = None,
    ) -> int:
        """Launch the browser; returns the OS pid of the new process.

        When ``proxy`` is provided the browser routes all traffic through it.
        """

    def stop(self, profile_path: Path, pid: int, timeout: float = 10.0) -> None: ...

    def is_running(self, profile_path: Path, pid: int | None) -> bool: ...


@runtime_checkable
class ProxyRepository(Protocol):
    def keys(self) -> set[tuple[str, str, int]]: ...

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