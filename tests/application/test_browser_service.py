"""Which Chrome runs the profiles, and fetching one."""

from __future__ import annotations

import io
import shutil
import threading
import zipfile
from pathlib import Path

import pytest

from antidetect.application.browser_service import KEEP_VERSIONS, BrowserService
from antidetect.domain.errors import BrowserDownloadError, ChromiumNotFoundError, DownloadCancelled
from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.infrastructure.chromium import chromium_manager as cm
from antidetect.infrastructure.chromium import downloader as dl

PLATFORM = "linux64"
EXE = "chrome-linux64/chrome"


def _release(version: str) -> dl.Release:
    return dl.Release(version, f"https://storage.googleapis.com/chrome-for-testing-public/{version}/{PLATFORM}/c.zip", PLATFORM)


def _archive(version: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        info = zipfile.ZipInfo(EXE)
        info.external_attr = 0o755 << 16
        z.writestr(info, f"#!/bin/sh\necho 'Google Chrome for Testing {version}'\n")
    return buffer.getvalue()


class Response:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._stream.read(min(n, 500) if n > 0 else n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Activity:
    def __init__(self) -> None:
        self.records: list[tuple] = []

    def record(self, kind, subject="", **data):
        self.records.append((kind, subject, data))


class Server:
    """What Google would answer: the newest version and the archive for any version."""

    def __init__(self, newest: str) -> None:
        self.newest = newest
        self.fetched: list[str] = []

    def fetch(self, channel="Stable", *, platform=None):
        return _release(self.newest)

    def opener(self, url: str):
        version = url.split("/chrome-for-testing-public/")[1].split("/")[0]
        self.fetched.append(version)
        return Response(_archive(version))


@pytest.fixture()
def managed(tmp_path: Path) -> dl.ManagedBrowsers:
    return dl.ManagedBrowsers(tmp_path / "browsers", platform=PLATFORM)


@pytest.fixture()
def manager(managed, monkeypatch, tmp_path):
    monkeypatch.delenv("ANTIDETECT_CHROMIUM_PATH", raising=False)
    monkeypatch.setattr(cm, "discover_chromium", lambda: (_ for _ in ()).throw(ChromiumNotFoundError()))
    return cm.ChromiumManager(logs_dir=tmp_path / "logs", managed_browsers=managed, enable_stealth=False)


def _service(manager, managed, server, **kw) -> BrowserService:
    return BrowserService(
        manager, managed, fetch=server.fetch, opener=server.opener, trusted=lambda url: True,
        verify=lambda exe: dl.probe_version(exe), **kw,
    )


# ------------------------------------------------------------ which browser wins

def _put_managed(managed, version: str) -> Path:
    exe = managed.executable_in(managed.folder_for(version))
    exe.parent.mkdir(parents=True)
    exe.write_text(f"#!/bin/sh\necho 'Google Chrome for Testing {version}'\n")
    exe.chmod(0o755)
    return exe


def test_with_nothing_installed_there_is_no_browser(manager):
    assert manager.browser_source() == "none" and manager.resolved_binary() is None
    assert manager.binary_full_version() is None and manager.binary_major() is None


def test_a_downloaded_chrome_is_used_when_nothing_was_chosen(manager, managed):
    exe = _put_managed(managed, "154.0.8037.93")
    assert manager.resolved_binary() == exe and manager.browser_source() == "managed"
    assert manager.binary_full_version() == "154.0.8037.93" and manager.binary_major() == 154


def test_the_newest_downloaded_version_runs(manager, managed):
    _put_managed(managed, "153.0.1.1")
    newest = _put_managed(managed, "154.0.8037.93")
    assert manager.resolved_binary() == newest


def test_a_path_the_user_chose_beats_the_downloaded_one(manager, managed, tmp_path):
    _put_managed(managed, "154.0.8037.93")
    mine = tmp_path / "mine"
    mine.write_text("#!/bin/sh\necho 'Google Chrome 150.0.1.2'\n")
    mine.chmod(0o755)
    manager.set_chromium_path(mine)
    assert manager.resolved_binary() == mine and manager.browser_source() == "configured"
    manager.set_chromium_path(None)                                         # "detect automatically" goes back to ours
    assert manager.browser_source() == "managed"


def test_an_installed_chrome_is_the_last_resort(managed, monkeypatch, tmp_path):
    installed = tmp_path / "installed-chrome"
    installed.write_text("x")
    monkeypatch.setattr(cm, "discover_chromium", lambda: installed)
    manager = cm.ChromiumManager(logs_dir=tmp_path / "logs", managed_browsers=managed, enable_stealth=False)
    assert manager.resolved_binary() == installed and manager.browser_source() == "auto"
    _put_managed(managed, "154.0.8037.93")
    assert manager.browser_source() == "managed"                           # downloading it changes what runs


def test_without_a_managed_folder_nothing_changes(monkeypatch, tmp_path):
    installed = tmp_path / "chrome"
    installed.write_text("x")
    monkeypatch.setattr(cm, "discover_chromium", lambda: installed)
    manager = cm.ChromiumManager(logs_dir=tmp_path / "logs", enable_stealth=False)
    assert manager.browser_source() == "auto" and manager.resolved_binary() == installed


def test_a_profile_really_starts_on_the_downloaded_chrome(managed, fake_chromium, monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "discover_chromium", lambda: (_ for _ in ()).throw(ChromiumNotFoundError()))
    exe = managed.executable_in(managed.folder_for("152.0.0.0"))
    exe.parent.mkdir(parents=True)
    shutil.copy(fake_chromium, exe)                                         # the stub that records its own start
    exe.chmod(0o755)
    manager = cm.ChromiumManager(logs_dir=tmp_path / "logs", managed_browsers=managed, enable_stealth=False, stop_timeout=1.0)
    profile = tmp_path / "p"
    pid = manager.start(profile, BrowserConfiguration(id=1, name="x"))
    try:
        assert (tmp_path / "fake_chromium.args").exists()                    # it was the downloaded one that ran
    finally:
        manager.stop(profile, pid)


# --------------------------------------------------------------------- status

def test_status_names_the_browser_its_version_and_the_downloaded_ones(manager, managed):
    service = _service(manager, managed, Server("154.0.8037.93"))
    assert service.status().source == "none" and service.status().downloaded == ()
    _put_managed(managed, "154.0.8037.93")
    status = service.status()
    assert (status.source, status.version) == ("managed", "154.0.8037.93")
    assert [b.version for b in status.downloaded] == ["154.0.8037.93"]


# --------------------------------------------------------------------- updates

def test_an_update_is_offered_only_when_google_has_something_newer(manager, managed):
    server = Server("155.0.1.1")
    service = _service(manager, managed, server)
    assert service.update_available().version == "155.0.1.1"                # nothing downloaded yet: it is on offer
    _put_managed(managed, "154.0.8037.93")
    assert service.update_available().version == "155.0.1.1"
    server.newest = "154.0.8037.93"
    assert service.update_available() is None                               # same version: nothing to do
    server.newest = "153.0.0.1"
    assert service.update_available() is None                               # never "update" backwards


# ------------------------------------------------------------------ installing

def test_installing_the_latest_downloads_unpacks_and_makes_it_the_active_browser(manager, managed):
    activity = Activity()
    server = Server("154.0.8037.93")
    service = _service(manager, managed, server, activity=activity)
    seen = []
    release, installed = service.install_latest(on_progress=lambda a, b: seen.append((a, b)))
    assert installed.version == "154.0.8037.93" and release.version == installed.version
    assert seen and seen[-1][0] == seen[-1][1]
    assert manager.browser_source() == "managed" and manager.binary_full_version() == "154.0.8037.93"
    assert activity.records == [("act.browser.installed", "154.0.8037.93", {})]
    assert [p.name for p in managed.root.iterdir()] == ["154.0.8037.93-linux64"]


def test_asking_again_for_a_version_already_here_downloads_nothing(manager, managed):
    server = Server("154.0.8037.93")
    service = _service(manager, managed, server)
    service.install_latest()
    release, installed = service.install_latest()
    assert installed is None and release.version == "154.0.8037.93" and server.fetched == ["154.0.8037.93"]


def test_only_the_newest_versions_are_kept(manager, managed):
    server = Server("1.0.0.1")
    service = _service(manager, managed, server)
    for version in ("1.0.0.1", "2.0.0.1", "3.0.0.1"):
        server.newest = version
        service.install_latest()
    assert KEEP_VERSIONS == 2
    assert [b.version for b in managed.installed()] == ["3.0.0.1", "2.0.0.1"]


def test_stopping_the_download_changes_nothing(manager, managed):
    cancel = threading.Event()
    cancel.set()
    service = _service(manager, managed, Server("154.0.8037.93"))
    with pytest.raises(DownloadCancelled):
        service.install_latest(cancel=cancel)
    assert managed.installed() == [] and manager.browser_source() == "none"


def test_a_failed_install_does_not_change_what_runs(manager, managed):
    _put_managed(managed, "153.0.1.1")
    service = BrowserService(manager, managed, fetch=Server("154.0.8037.93").fetch, opener=Server("154.0.8037.93").opener,
                             trusted=lambda u: True, verify=lambda exe: None)
    with pytest.raises(BrowserDownloadError):
        service.install_latest()
    assert manager.browser_source() == "managed" and manager.binary_full_version() == "153.0.1.1"


def test_an_untrusted_address_from_the_index_is_never_downloaded(manager, managed):
    class Hostile(Server):
        def fetch(self, channel="Stable", *, platform=None):
            return dl.Release("154.0.8037.93", "https://evil.example/chrome-for-testing-public/c.zip", PLATFORM)

    service = BrowserService(manager, managed, fetch=Hostile("x").fetch, opener=Hostile("x").opener)     # default trust rules
    with pytest.raises(BrowserDownloadError, match="not Google"):
        service.install_latest()
    assert managed.installed() == []
