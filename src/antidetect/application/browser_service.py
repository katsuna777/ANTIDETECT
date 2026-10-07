"""Which Chrome runs the profiles, and getting one: the app can download Google's own build.

A profile's fingerprint claims a Chrome version, and that has to be the version that really runs.
An installed Chrome updates itself whenever it likes; one the app downloaded stays what it was until
the user asks for a newer one. And a computer without Chrome (a fresh Windows machine, say) can
start working after one click instead of a trip to a download page.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from antidetect.infrastructure.chromium import downloader as dl

if TYPE_CHECKING:
    from antidetect.application.ports import ActivitySink, LogSink
    from antidetect.infrastructure.chromium.chromium_manager import ChromiumManager

#: How many downloaded versions are kept: the newest, and the one before it to go back to.
KEEP_VERSIONS = 2


@dataclass(frozen=True)
class BrowserStatus:
    path: Path | None
    version: str | None
    #: ``configured`` (a path the user chose), ``managed`` (downloaded by the app),
    #: ``auto`` (found installed on the computer) or ``none``.
    source: str
    downloaded: tuple[dl.InstalledBrowser, ...]


class BrowserService:
    def __init__(
        self,
        manager: "ChromiumManager",
        managed: dl.ManagedBrowsers,
        *,
        log_sink: "LogSink | None" = None,
        activity: "ActivitySink | None" = None,
        fetch: Callable[..., dl.Release] | None = None,
        opener: Callable[[str], Any] | None = None,
        trusted: Callable[[str], bool] | None = None,
        verify: Callable[[Path], str | None] | None = None,
    ) -> None:
        self._manager = manager
        self._managed = managed
        self._log = log_sink
        self._activity = activity
        # None means "the real thing", resolved when it is needed (see downloader: tests cut the network off there).
        self._fetch = fetch
        self._opener = opener
        self._trusted = trusted
        self._verify = verify

    # ---------------------------------------------------------------- reading

    def status(self) -> BrowserStatus:
        return BrowserStatus(
            path=self._manager.resolved_binary(),
            version=self._manager.binary_full_version(),
            source=self._manager.browser_source(),
            downloaded=tuple(self._managed.installed()),
        )

    def status_downloaded(self) -> tuple[dl.InstalledBrowser, ...]:
        """The downloaded browsers (a quick look at the folder; unlike :meth:`status` it never runs Chrome)."""
        return tuple(self._managed.installed())

    def is_downloaded(self, version: str) -> bool:
        """Whether this exact version is already here (a quick look at the folder, no network)."""
        return self._managed.has(version)

    def latest(self, channel: str = "Stable") -> dl.Release:
        """The newest release Google publishes for this computer (needs the network)."""
        return (self._fetch or dl.fetch_latest)(channel, platform=self._managed.platform)

    def update_available(self, channel: str = "Stable") -> dl.Release | None:
        """The newest release when it is newer than every downloaded one (or none is downloaded)."""
        release = self.latest(channel)
        newest = self._managed.active()
        if newest is not None and dl.version_key(newest.version) >= dl.version_key(release.version):
            return None
        return release

    # ------------------------------------------------------------- installing

    def download(
        self,
        release: dl.Release,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> Path:
        self._managed.clean_leftovers()
        self._info(f"Downloading Chrome {release.version} ({release.platform})")
        return self._managed.download(
            release, on_progress=on_progress, cancel=cancel, opener=self._opener, trusted=self._trusted
        )

    def install(self, release: dl.Release, archive: Path) -> dl.InstalledBrowser:
        """Unpack and check a downloaded archive, then tidy up older versions."""
        installed = self._managed.install(release, archive, verify=self._verify)
        removed = self._managed.prune(KEEP_VERSIONS)
        self._info(
            f"Chrome {installed.version} installed",
            {"version": installed.version, "folder": str(installed.folder), "removed": removed},
        )
        if self._activity is not None:
            self._activity.record("act.browser.installed", installed.version)
        return installed

    def install_latest(
        self,
        channel: str = "Stable",
        on_progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[dl.Release, dl.InstalledBrowser | None]:
        """Download and install the newest release unless it is already here (``None`` then)."""
        release = self.latest(channel)
        if self._managed.has(release.version):
            return release, None
        archive = self.download(release, on_progress, cancel)
        return release, self.install(release, archive)

    def _info(self, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.info("browser", message, extra)
