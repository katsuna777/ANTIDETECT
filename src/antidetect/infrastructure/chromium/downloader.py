"""Chrome for Testing: Google's own pinnable builds of Chrome, downloaded and kept by the app.

Why the app brings its own Chrome: the fingerprint must match the real engine, and a Chrome that
updates itself under the app's feet (or one that is not installed at all) breaks that. These
builds are the real Chrome, do not update by themselves and sit in the app's data folder next to
the profiles, so a version stays until the app is told to move on.

Trust: the index is read over HTTPS from Google, and a download is accepted only from Google's
storage bucket for these builds. The archive is checked for damage, unpacked with every path kept
inside its folder (a hostile archive cannot write elsewhere), installed atomically (a half-finished
download is never mistaken for a browser) and finally asked for its version, which proves it runs
on this computer.
"""

from __future__ import annotations

import json
import os
import platform as _platform
import re
import shutil
import stat
import subprocess
import sys
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import urlparse

from antidetect.domain.errors import BrowserDownloadError, DownloadCancelled

INDEX_URL = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
#: The only place a browser is downloaded from: (host, path prefix).
TRUSTED_SOURCE = ("storage.googleapis.com", "/chrome-for-testing-public/")
CHANNELS = ("Stable", "Beta", "Dev", "Canary")
_CHUNK = 256 * 1024
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)\.(\d+)")

#: Where the program is inside an unpacked archive, per platform.
_EXECUTABLES = {
    "mac-arm64": "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "mac-x64": "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "win64": "chrome-win64/chrome.exe",
    "win32": "chrome-win32/chrome.exe",
    "linux64": "chrome-linux64/chrome",
}


@dataclass(frozen=True)
class Release:
    version: str          # 154.0.8037.93
    url: str
    platform: str         # mac-arm64 | mac-x64 | win64 | win32 | linux64
    channel: str = "Stable"

    @property
    def major(self) -> int:
        return version_key(self.version)[0]


@dataclass(frozen=True)
class InstalledBrowser:
    version: str
    platform: str
    folder: Path
    executable: Path

    @property
    def major(self) -> int:
        return version_key(self.version)[0]


def version_key(version: str) -> tuple[int, ...]:
    match = _VERSION.search(version or "")
    return tuple(int(part) for part in match.groups()) if match else (0, 0, 0, 0)


def current_platform() -> str:
    """The download name of this computer's platform."""
    if sys.platform == "darwin":
        return "mac-arm64" if _platform.machine().lower() in ("arm64", "aarch64") else "mac-x64"
    if sys.platform.startswith("win"):
        return "win64" if sys.maxsize > 2 ** 32 else "win32"
    return "linux64"


def is_trusted_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host, prefix = TRUSTED_SOURCE
    return parsed.scheme == "https" and parsed.hostname == host and parsed.path.startswith(prefix)


# ---------------------------------------------------------------------------- the index

def parse_index(data: Any, platform: str, channel: str = "Stable") -> Release:
    """The release of ``channel`` for ``platform`` out of Google's index."""
    try:
        entry = data["channels"][channel]
        version = str(entry["version"])
        urls = {item["platform"]: item["url"] for item in entry["downloads"]["chrome"]}
        url = urls[platform]
    except (KeyError, TypeError, ValueError):
        raise BrowserDownloadError(f"Google's list has no {channel} Chrome for {platform}.") from None
    if not _VERSION.fullmatch(version):
        raise BrowserDownloadError(f"Google's list gives an unreadable version: {version!r}")
    return Release(version=version, url=str(url), platform=platform, channel=channel)


def _open(url: str, timeout: float = 30.0):
    request = urllib.request.Request(url, headers={"User-Agent": "Antidetect"})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https URLs only, checked by the callers


def fetch_latest(
    channel: str = "Stable",
    *,
    platform: str | None = None,
    index_url: str = INDEX_URL,
    opener: Callable[[str], Any] | None = None,
) -> Release:
    """Ask Google which version is current. Raises :class:`BrowserDownloadError` when it cannot be reached."""
    if channel not in CHANNELS:
        raise BrowserDownloadError(f"Unknown channel {channel!r}; expected one of {', '.join(CHANNELS)}.")
    try:
        with (opener or _open)(index_url) as response:       # looked up now, so a test can cut the network off
            data = json.loads(response.read().decode("utf-8"))
    except BrowserDownloadError:
        raise
    except Exception as exc:
        raise BrowserDownloadError(f"Could not reach Google's list of Chrome versions: {exc}") from exc
    return parse_index(data, platform or current_platform(), channel)


# --------------------------------------------------------------------------- the folder

class ManagedBrowsers:
    """The browsers the app downloaded: one folder per version, ``<root>/<version>-<platform>``."""

    def __init__(self, root: Path, *, platform: str | None = None) -> None:
        self._root = Path(root)
        self._platform = platform or current_platform()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def platform(self) -> str:
        return self._platform

    def folder_for(self, version: str) -> Path:
        return self._root / f"{version}-{self._platform}"

    def executable_in(self, folder: Path) -> Path:
        return Path(folder) / _EXECUTABLES[self._platform]

    def installed(self) -> list[InstalledBrowser]:
        """Every working install for this platform, newest first. A folder without its program is not one."""
        found: list[InstalledBrowser] = []
        suffix = f"-{self._platform}"
        try:
            names = sorted(os.listdir(self._root))
        except OSError:
            return []
        for name in names:
            folder = self._root / name
            if name.startswith(".") or not name.endswith(suffix) or not folder.is_dir():
                continue
            version = name[: -len(suffix)]
            executable = self.executable_in(folder)
            if _VERSION.fullmatch(version) and executable.is_file():
                found.append(InstalledBrowser(version, self._platform, folder, executable))
        return sorted(found, key=lambda b: version_key(b.version), reverse=True)

    def active(self) -> InstalledBrowser | None:
        installed = self.installed()
        return installed[0] if installed else None

    def has(self, version: str) -> bool:
        return any(b.version == version for b in self.installed())

    # ------------------------------------------------------------------ download
    def _archive_path(self, release: Release) -> Path:
        return self._root / f".download-{release.version}-{release.platform}.zip"

    def download(
        self,
        release: Release,
        *,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
        opener: Callable[[str], Any] | None = None,
        trusted: Callable[[str], bool] | None = None,
    ) -> Path:
        """Fetch the archive. Returns its path; stopping with ``cancel`` leaves nothing behind."""
        if release.platform != self._platform:
            raise BrowserDownloadError(f"This release is for {release.platform}, not {self._platform}.")
        if not (trusted or is_trusted_url)(release.url):
            raise BrowserDownloadError("Refusing to download from an address that is not Google's Chrome for Testing storage.")
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._archive_path(release)
        scratch = target.with_name(target.name + ".part")
        try:
            with (opener or _open)(release.url) as response, open(scratch, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                self._require_room(total)
                done = 0
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled("Download stopped.")
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, max(total, done))
            if total and done != total:
                raise BrowserDownloadError(f"The download ended early ({done} of {total} bytes).")
            os.replace(scratch, target)
        except BaseException as exc:
            scratch.unlink(missing_ok=True)
            if isinstance(exc, (BrowserDownloadError, KeyboardInterrupt)):
                raise
            raise BrowserDownloadError(f"Could not download Chrome: {exc}") from exc
        return target

    def _require_room(self, archive_bytes: int) -> None:
        """The archive, its unpacked copy and some slack."""
        if archive_bytes <= 0:
            return
        try:
            free = shutil.disk_usage(self._root).free
        except OSError:
            return
        need = archive_bytes * 3
        if free < need:
            raise BrowserDownloadError(
                f"Not enough free disk space: {need // 2 ** 20} MB needed, {free // 2 ** 20} MB free."
            )

    # ------------------------------------------------------------------- install
    def install(
        self,
        release: Release,
        archive: Path,
        *,
        verify: Callable[[Path], str | None] | None = None,
    ) -> InstalledBrowser:
        """Unpack ``archive`` into this release's folder (replacing an older copy of it) and check it runs.

        The unpacking happens beside the final folder and is moved into place in one step, so a
        crash or a cancelled app never leaves a folder that looks like a browser but is half of one.
        """
        probe = verify or probe_version
        self._root.mkdir(parents=True, exist_ok=True)
        staging = self._root / f".unpack-{release.version}-{release.platform}-{os.getpid()}"
        final = self.folder_for(release.version)
        shutil.rmtree(staging, ignore_errors=True)
        try:
            try:
                with zipfile.ZipFile(archive) as bundle:
                    bad = bundle.testzip()
                    if bad is not None:
                        raise BrowserDownloadError(f"The download is damaged ({bad}). Try again.")
                    unpack_safely(bundle, staging)
            except zipfile.BadZipFile:
                raise BrowserDownloadError("The download is not a valid archive. Try again.") from None
            executable = self.executable_in(staging)
            if not executable.is_file():
                raise BrowserDownloadError("The archive does not contain Chrome where it should.")
            _make_executable(executable)
            reported = probe(executable)
            if reported is None:
                raise BrowserDownloadError("The downloaded Chrome does not start on this computer.")
            if version_key(reported) != version_key(release.version):
                raise BrowserDownloadError(f"The downloaded Chrome says it is {reported}, not {release.version}.")
            if final.exists():
                shutil.rmtree(final)
            os.replace(staging, final)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            archive.unlink(missing_ok=True)
        return InstalledBrowser(release.version, release.platform, final, self.executable_in(final))

    # -------------------------------------------------------------------- upkeep
    def prune(self, keep: int = 2) -> list[str]:
        """Remove all but the ``keep`` newest versions; returns the versions removed. A folder that is
        in use (Windows locks the files of a running program) is left for next time."""
        removed: list[str] = []
        for browser in self.installed()[max(keep, 1):]:
            try:
                shutil.rmtree(browser.folder)
            except OSError:
                continue
            removed.append(browser.version)
        return removed

    def clean_leftovers(self) -> None:
        """Delete what an interrupted download or unpack left behind."""
        try:
            for name in os.listdir(self._root):
                if name.startswith((".download-", ".unpack-")):
                    path = self._root / name
                    shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
        except OSError:
            pass


# ------------------------------------------------------------------------------ helpers

def probe_version(executable: Path) -> str | None:
    """What ``executable --version`` says, or ``None`` when it does not run."""
    try:
        completed = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    match = _VERSION.search((completed.stdout or "") + (completed.stderr or ""))
    return match.group(0) if match else None


def _make_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def unpack_safely(bundle: zipfile.ZipFile, target: Path) -> None:
    """Unpack into ``target`` with every path (and every link) kept inside it.

    ``zipfile`` drops file modes and writes links as plain files; a macOS ``.app`` needs both (its
    frameworks are links, its program is executable), so they are restored here.
    """
    root = target.resolve()
    root.mkdir(parents=True, exist_ok=True)
    links: list[tuple[Path, str]] = []
    for info in bundle.infolist():
        name = PurePosixPath(info.filename)
        if name.is_absolute() or ".." in name.parts or not name.parts:
            raise BrowserDownloadError(f"The archive holds an unsafe path: {info.filename!r}")
        path = root.joinpath(*name.parts)
        if root != path.resolve() and root not in path.resolve().parents:
            raise BrowserDownloadError(f"The archive holds an unsafe path: {info.filename!r}")
        mode = info.external_attr >> 16
        if info.is_dir():
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if stat.S_ISLNK(mode):
            links.append((path, bundle.read(info).decode("utf-8")))
            continue
        with bundle.open(info) as read, open(path, "wb") as write:
            _copy(read, write)
        if mode & 0o777:
            try:
                path.chmod((mode & 0o777) | stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
    for path, destination in links:
        resolved = (path.parent / destination).resolve()
        if os.path.isabs(destination) or (root != resolved and root not in resolved.parents):
            raise BrowserDownloadError(f"The archive holds a link that leaves its folder: {destination!r}")
        if path.is_symlink() or path.exists():
            path.unlink()
        os.symlink(destination, path)


def _copy(read: BinaryIO, write: BinaryIO) -> None:
    shutil.copyfileobj(read, write, 1024 * 1024)
