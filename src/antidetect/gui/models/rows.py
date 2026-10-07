"""Flat read-models the tables show. Built off the UI thread, immutable."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

NO_WORKSPACE = -1        # the "profiles in no workspace" view (a real workspace id is always positive)


@dataclass(frozen=True)
class ProfileRow:
    id: int
    name: str
    running: bool
    pid: int | None
    notes: str
    tags: tuple[str, ...]
    platform: str | None          # windows | macos | linux
    browser: str                  # "Chrome 154"
    user_agent: str | None
    timezone: str | None
    locale: str | None
    language: str | None
    screen: str | None            # "1920×1080"
    gpu: str | None               # "NVIDIA GeForce RTX 3060"
    cores: int | None
    memory_gb: int | None
    proxy_id: int | None
    proxy_endpoint: str | None    # "host:port"
    proxy_protocol: str | None
    proxy_country_code: str | None
    proxy_country: str | None
    proxy_latency: int | None
    last_started_at: datetime | None
    geo_auto: bool
    start_url: str | None
    configuration_id: int | None
    profile_path: str
    proxy_free: bool = False      # the proxy came from the free list, not from the user
    created_at: datetime | None = None
    cookie_count: int | None = None        # cookies the browser has saved so far (None = unknown / never ran)
    proxy_status: str | None = None        # WORKING | DEAD | UNKNOWN | ERROR
    proxy_username: str | None = None
    proxy_checked_at: datetime | None = None
    workspace_id: int | None = None
    updated_at: datetime | None = None
    last_stopped_at: datetime | None = None
    deleted_at: datetime | None = None     # set only for the rows of the trash


@dataclass(frozen=True)
class ProxyRow:
    id: int
    protocol: str
    host: str
    port: int
    username: str | None
    country_code: str | None
    country: str | None
    latency_ms: int | None
    status: str                   # WORKING | DEAD | UNKNOWN | ERROR
    anonymity: str | None
    source: str | None
    used_by: tuple[str, ...]      # names of profiles using it
    checked_at: datetime | None

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def is_manual(self) -> bool:
        return (self.source or "") == "manual"


_GPU_RE = re.compile(r"^ANGLE \((?:[^,]+), (.*?)(?: \(0x[0-9A-Fa-f]+\))?(?: Direct3D|,|$)")


def short_gpu(renderer: str | None) -> str | None:
    """``ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x..) Direct3D11 ...)`` -> model name."""
    if not renderer:
        return None
    match = _GPU_RE.match(renderer)
    name = match.group(1) if match else renderer
    name = re.sub(r"^ANGLE Metal Renderer:\s*", "", name)
    name = re.sub(r"^Mesa\s+", "", name)
    name = name.split("/")[0]
    name = re.sub(r"\s*\((?:CFL|KBL|SKL|TGL|ADL|radeonsi)[^)]*\)", "", name)
    name = name.replace("(R)", "").replace("(TM)", "")
    return re.sub(r"\s{2,}", " ", name).strip() or None


def browser_label(user_agent: str | None) -> str:
    match = re.search(r"Chrome/(\d+)", user_agent or "")
    return f"Chrome {match.group(1)}" if match else "Chrome"


def local_time(moment: datetime | None) -> datetime | None:
    """A stored (UTC-naive) moment as local wall-clock time."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().replace(tzinfo=None)


def relative_time(moment: datetime | None, now: datetime | None = None):
    """(unit, n) for 'N minutes ago' style labels; ``None`` when never."""
    if moment is None:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    base = moment.replace(tzinfo=None) if moment.tzinfo else moment
    seconds = max(0, int((now - base).total_seconds()))
    if seconds < 60:
        return ("now", 0)
    if seconds < 3600:
        return ("minutes", seconds // 60)
    if seconds < 86400:
        return ("hours", seconds // 3600)
    return ("days", seconds // 86400)
