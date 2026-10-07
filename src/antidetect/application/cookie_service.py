"""Cookie backup/restore for a single profile.

Cookies are stored by Chromium inside the profile directory (``Default/Cookies``
or ``Cookies``) as a SQLite database. ``export`` produces a consistent snapshot
of that database via SQLite's online backup API, so it is safe even while the
browser is running; ``import`` replaces the target database and requires the
profile to be stopped so Chromium is not holding a write lock.

The cookie *payloads* are never read, printed or written to application logs.
Only filesystem paths are reported. Notably, Chromium encrypts cookie values
with per-profile keys derived from the OS keychain/DPAPI, so an exported
database is only readable by the exact profile (and OS user) it came from.
"""

from __future__ import annotations

import os
import sqlite3
import stat as stat_module
import time
from pathlib import Path

from antidetect.application.ports import BrowserManager, ProfileRepository
from antidetect.domain.errors import (
    CookieError,
    CookieFileNotFoundError,
    CookieImportError,
    ProfileNotFoundError,
)
from antidetect.domain.models.profile import Profile

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from antidetect.application.ports import LogSink

_COOKIE_CANDIDATES = ("Default/Network/Cookies", "Default/Cookies", "Cookies")


def _locate(profile_dir: Path | str) -> tuple[str, os.stat_result] | None:
    """The cookie database Chrome writes to — the most recently modified of the known locations — with its stat."""
    base = os.fspath(profile_dir)
    best: tuple[str, os.stat_result] | None = None
    for name in _COOKIE_CANDIDATES:
        path = os.path.join(base, name)
        try:
            info = os.stat(path)
        except OSError:
            continue
        if stat_module.S_ISREG(info.st_mode) and (best is None or info.st_mtime_ns > best[1].st_mtime_ns):
            best = (path, info)
    return best


def _find_cookies_db(profile_dir: Path) -> Path | None:
    found = _locate(profile_dir)
    return Path(found[0]) if found else None


_count_cache: dict[str, tuple[int, int, int | None]] = {}


def count_cookies(profile_dir: Path | str) -> int | None:
    """How many cookies a profile has saved, read without touching the running browser.

    The database is opened read-only and ``immutable`` (no locks, no journal), so this is safe
    while Chrome runs; it sees what Chrome has flushed to disk. Results are cached per file
    version, so polling a hundred profiles costs a ``stat`` each. ``None`` = no database yet.
    """
    found = _locate(profile_dir)
    if found is None:
        return None
    db, info = found
    version = (info.st_mtime_ns, info.st_size)
    cached = _count_cache.get(db)
    if cached is not None and cached[:2] == version:
        return cached[2]
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, timeout=0.2)
        try:
            count = int(con.execute("SELECT COUNT(*) FROM cookies").fetchone()[0])
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        count = None
    _count_cache[db] = (version[0], version[1], count)
    return count


class CookieService:
    def __init__(
        self,
        profiles: ProfileRepository,
        browsers: BrowserManager,
        export_dir: Path,
        log_sink: "LogSink | None" = None,
    ) -> None:
        self._profiles = profiles
        self._browsers = browsers
        self._export_dir = export_dir
        self._log = log_sink

    # ---------------------------------------------------------------- export

    def export(self, profile_id: int, output: Path | None = None) -> str:
        """Export the profile's cookie database to a file; returns its path."""
        profile = self._require_profile(profile_id)
        cookies_db = _find_cookies_db(Path(profile.profile_path))
        if cookies_db is None:
            raise CookieFileNotFoundError(
                profile_id,
                "no cookie database found (profile never ran? remove it and start "
                "the browser once to create one)",
            )

        destination = output or self._default_export_path(profile)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _sqlite_backup(cookies_db, destination)
        if self._log is not None:
            self._log.info(
                "cookies",
                f"Profile #{profile_id} cookies exported",
                extra={"profile_id": profile_id, "path": str(destination)},
            )
        return str(destination)

    # ---------------------------------------------------------------- import

    def import_(self, profile_id: int, source: Path) -> str:
        """Replace the profile's cookie database with ``source``."""
        profile = self._require_profile(profile_id)
        source = Path(source).expanduser()

        if not source.is_file():
            raise CookieImportError(f"cookie file does not exist: {source}")
        _require_sqlite(source)

        profile_dir = Path(profile.profile_path)
        if self._browsers.is_running(profile_dir, profile.pid):
            raise CookieImportError(
                f"profile {profile_id} is running; stop it before importing "
                "cookies (the browser holds a write lock on the cookie database)"
            )

        profile_dir.mkdir(parents=True, exist_ok=True)
        target = _find_cookies_db(profile_dir) or profile_dir / "Default" / "Cookies"
        target.parent.mkdir(parents=True, exist_ok=True)
        _replace_cookie_db(source, target)
        if self._log is not None:
            self._log.info(
                "cookies",
                f"Profile #{profile_id} cookies imported",
                extra={"profile_id": profile_id, "source": str(source)},
            )
        return str(target)

    # --------------------------------------------------------------- helpers

    def _require_profile(self, profile_id: int) -> Profile:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)
        return profile

    def _default_export_path(self, profile: Profile) -> Path:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return (
            self._export_dir
            / f"profile_{profile.id:03d}"
            / f"cookies_{stamp}.db"
        )


def _sqlite_backup(source: Path, destination: Path) -> None:
    """Online backup producing a consistent copy (safe under WAL)."""
    try:
        src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise CookieError(f"cannot open cookie database {source}: {exc}") from exc
    dest_conn = sqlite3.connect(
        f"file:{destination}?mode=rwc", uri=True
    )
    try:
        with dest_conn:
            src_conn.backup(dest_conn)
    finally:
        src_conn.close()
        dest_conn.close()


def _require_sqlite(path: Path) -> None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise CookieImportError(
            f"{path} is not a valid cookie database: {exc}"
        ) from exc


def _replace_cookie_db(source: Path, target: Path) -> None:
    """Replace the target cookies db and drop stale WAL/journal sidecar files."""
    for sidecar in (
        Path(f"{target}-wal"),
        Path(f"{target}-shm"),
        Path(f"{target}-journal"),
    ):
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass
    try:
        import shutil

        shutil.copy2(source, target)
    except OSError as exc:
        raise CookieImportError(
            f"failed to write cookie database to {target}: {exc}"
        ) from exc