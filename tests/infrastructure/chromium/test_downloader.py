"""Downloading Chrome for Testing: the index, the source check, the archive and the install."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from antidetect.domain.errors import BrowserDownloadError, DownloadCancelled
from antidetect.infrastructure.chromium import downloader as dl

PLATFORM = "linux64"
VERSION = "154.0.8037.93"
EXE = "chrome-linux64/chrome"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="file modes and symbolic links are POSIX")


def _index(version=VERSION, platform=PLATFORM, channel="Stable") -> dict:
    return {"channels": {channel: {"version": version, "downloads": {"chrome": [
        {"platform": "mac-arm64", "url": "https://storage.googleapis.com/chrome-for-testing-public/x/mac-arm64/a.zip"},
        {"platform": platform, "url": f"https://storage.googleapis.com/chrome-for-testing-public/{version}/{platform}/chrome-{platform}.zip"},
    ]}}}}


def _zip(entries: dict[str, bytes | tuple[bytes, int]]) -> bytes:
    """An archive; a value may be ``(content, unix mode)``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            content, mode = value if isinstance(value, tuple) else (value, 0o644)
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _chrome_zip(**extra) -> bytes:
    return _zip({EXE: (b"#!/bin/sh\necho 'Google Chrome for Testing 154.0.8037.93'\n", 0o755), "chrome-linux64/locales/en.pak": b"x", **extra})


class FakeResponse:
    def __init__(self, data: bytes, *, length: int | None = None, chunk: int = 1000) -> None:
        self._stream = io.BytesIO(data)
        self._chunk = chunk
        self.headers = {} if length == -1 else {"Content-Length": str(len(data) if length is None else length)}
        self.on_read = None

    def read(self, n: int = -1) -> bytes:
        if self.on_read:
            self.on_read()
        return self._stream.read(min(n, self._chunk) if n > 0 else n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _always(data: bytes, **kw):
    return lambda url: FakeResponse(data, **kw)


@pytest.fixture()
def browsers(tmp_path: Path) -> dl.ManagedBrowsers:
    return dl.ManagedBrowsers(tmp_path / "browsers", platform=PLATFORM)


def _release(version=VERSION) -> dl.Release:
    return dl.Release(version, f"https://storage.googleapis.com/chrome-for-testing-public/{version}/{PLATFORM}/c.zip", PLATFORM)


def _install(browsers, data=None, version=VERSION, verify=lambda exe: VERSION, **kw):
    release = _release(version)
    archive = browsers.download(release, opener=_always(data or _chrome_zip()), **kw)
    return browsers.install(release, archive, verify=verify)


# ----------------------------------------------------------------- the index

def test_the_stable_release_for_a_platform_is_picked_out_of_the_index():
    release = dl.parse_index(_index(), PLATFORM)
    assert (release.version, release.platform, release.channel, release.major) == (VERSION, PLATFORM, "Stable", 154)
    assert release.url.endswith("chrome-linux64.zip")


@pytest.mark.parametrize(
    "data, platform",
    [({}, PLATFORM), ({"channels": {}}, PLATFORM), (None, PLATFORM), (_index(), "win64"), (_index(version="soon"), PLATFORM)],
)
def test_an_index_without_what_is_needed_is_refused_with_a_reason(data, platform):
    with pytest.raises(BrowserDownloadError):
        dl.parse_index(data, platform)


def test_other_channels_can_be_asked_for():
    assert dl.parse_index(_index(channel="Beta", version="155.0.1.2"), PLATFORM, "Beta").version == "155.0.1.2"


def test_fetch_latest_reads_the_index_through_the_opener():
    release = dl.fetch_latest(platform=PLATFORM, opener=_always(json.dumps(_index()).encode()))
    assert release.version == VERSION


def test_an_unreachable_or_unreadable_index_is_a_download_error_not_a_crash():
    def down(url):
        raise OSError("no route to host")

    with pytest.raises(BrowserDownloadError, match="Could not reach"):
        dl.fetch_latest(platform=PLATFORM, opener=down)
    with pytest.raises(BrowserDownloadError):
        dl.fetch_latest(platform=PLATFORM, opener=_always(b"<html>captive portal</html>"))
    with pytest.raises(BrowserDownloadError, match="Unknown channel"):
        dl.fetch_latest("Nightly", platform=PLATFORM)


def test_the_platform_name_is_one_google_publishes():
    assert dl.current_platform() in dl._EXECUTABLES


def test_versions_compare_as_numbers_not_as_text():
    keys = sorted(["154.0.8037.93", "99.0.1.1", "154.0.8037.100", "154.0.999.1"], key=dl.version_key)
    assert keys == ["99.0.1.1", "154.0.999.1", "154.0.8037.93", "154.0.8037.100"]


# ------------------------------------------------------------ the source check

@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://storage.googleapis.com/chrome-for-testing-public/154.0.1.2/mac-arm64/chrome-mac-arm64.zip", True),
        ("http://storage.googleapis.com/chrome-for-testing-public/x.zip", False),                    # not encrypted
        ("https://storage.googleapis.com/some-other-bucket/x.zip", False),
        ("https://evil.example/chrome-for-testing-public/x.zip", False),
        ("https://storage.googleapis.com.evil.example/chrome-for-testing-public/x.zip", False),     # look-alike host
        ("https://storage.googleapis.com@evil.example/chrome-for-testing-public/x.zip", False),
        ("file:///etc/passwd", False),
        ("", False),
    ],
)
def test_only_googles_chrome_for_testing_bucket_is_trusted(url, ok):
    assert dl.is_trusted_url(url) is ok


def test_an_untrusted_address_is_refused_before_anything_is_fetched(browsers):
    touched = []
    release = dl.Release(VERSION, "https://evil.example/chrome-for-testing-public/x.zip", PLATFORM)
    with pytest.raises(BrowserDownloadError, match="not Google"):
        browsers.download(release, opener=lambda url: touched.append(url))
    assert touched == [] and not browsers.root.exists()


def test_a_release_for_another_platform_is_refused(browsers):
    with pytest.raises(BrowserDownloadError, match="not linux64"):
        browsers.download(dl.Release(VERSION, _release().url, "win64"), opener=_always(b"x"))


# ------------------------------------------------------------------- download

def test_the_archive_is_saved_and_progress_runs_up_to_the_whole(browsers):
    data = _chrome_zip()
    seen: list[tuple[int, int]] = []
    path = browsers.download(_release(), on_progress=lambda a, b: seen.append((a, b)), opener=_always(data, chunk=50))
    assert path.read_bytes() == data
    assert seen[0][0] <= seen[1][0] and seen[-1] == (len(data), len(data)) and {t for _, t in seen} == {len(data)}
    assert not list(browsers.root.glob("*.part"))


def test_a_download_without_a_known_size_still_reports_what_has_arrived(browsers):
    seen = []
    browsers.download(_release(), on_progress=lambda a, b: seen.append((a, b)), opener=_always(_chrome_zip(), length=-1, chunk=60))
    assert seen[-1][0] == seen[-1][1] > 0


def test_stopping_a_download_leaves_no_file_behind(browsers):
    cancel = threading.Event()
    response = FakeResponse(_chrome_zip(), chunk=40)
    reads = []
    response.on_read = lambda: (reads.append(1), cancel.set() if len(reads) == 3 else None)
    with pytest.raises(DownloadCancelled):
        browsers.download(_release(), cancel=cancel, opener=lambda url: response)
    assert os.listdir(browsers.root) == [] and len(reads) <= 4                      # stopped promptly, tidied up


def test_a_connection_that_drops_early_is_an_error_and_is_cleaned_up(browsers):
    with pytest.raises(BrowserDownloadError, match="ended early"):
        browsers.download(_release(), opener=_always(b"only part", length=5000))
    assert os.listdir(browsers.root) == []


def test_a_network_failure_in_the_middle_is_reported_plainly(browsers):
    class Breaks(FakeResponse):
        def read(self, n=-1):
            raise ConnectionResetError("reset by peer")

    with pytest.raises(BrowserDownloadError, match="Could not download"):
        browsers.download(_release(), opener=lambda url: Breaks(b"x"))
    assert os.listdir(browsers.root) == []


def test_too_little_disk_space_is_said_before_the_download_starts(browsers, monkeypatch):
    monkeypatch.setattr(dl.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024})())
    with pytest.raises(BrowserDownloadError, match="Not enough free disk space"):
        browsers.download(_release(), opener=_always(b"x" * 5000))
    assert os.listdir(browsers.root) == []


# -------------------------------------------------------------------- install

def test_installing_puts_the_browser_in_its_own_versioned_folder(browsers):
    installed = _install(browsers)
    assert installed.version == VERSION and installed.folder == browsers.folder_for(VERSION)
    assert installed.executable.is_file() and installed.executable == browsers.executable_in(installed.folder)
    assert (installed.folder / "chrome-linux64" / "locales" / "en.pak").read_bytes() == b"x"
    assert [b.version for b in browsers.installed()] == [VERSION] and browsers.active().version == VERSION
    assert os.listdir(browsers.root) == [f"{VERSION}-{PLATFORM}"]                  # no archive, no staging folder left


@posix_only
def test_the_program_comes_out_executable_even_when_the_archive_forgot_to_say_so(browsers):
    data = _zip({EXE: (b"#!/bin/sh\necho x\n", 0o644)})
    installed = _install(browsers, data)
    assert installed.executable.stat().st_mode & stat.S_IXUSR


@posix_only
def test_links_inside_the_bundle_are_restored_as_links(browsers):
    data = _chrome_zip(**{"chrome-linux64/lib/current": (b"A/lib.so", 0o120777), "chrome-linux64/lib/A/lib.so": b"lib"})
    installed = _install(browsers, data)
    link = installed.folder / "chrome-linux64" / "lib" / "current"
    assert link.is_symlink() and os.readlink(link) == "A/lib.so"


@posix_only
@pytest.mark.parametrize("target", ["../../../../etc/passwd", "/etc/passwd"])
def test_a_link_that_points_out_of_the_folder_is_refused(browsers, target):
    data = _chrome_zip(**{"chrome-linux64/evil": (target.encode(), 0o120777)})
    with pytest.raises(BrowserDownloadError, match="leaves its folder"):
        _install(browsers, data)
    assert browsers.installed() == [] and not list(browsers.root.glob(".unpack-*"))


@pytest.mark.parametrize("evil", ["../escape.txt", "chrome-linux64/../../escape.txt", "/tmp/escape.txt"])
def test_a_path_that_climbs_out_is_refused_and_nothing_is_written(browsers, evil, tmp_path):
    with pytest.raises(BrowserDownloadError, match="unsafe path"):
        _install(browsers, _chrome_zip(**{evil: b"gotcha"}))
    assert browsers.installed() == []
    assert not (tmp_path / "escape.txt").exists() and not (browsers.root / "escape.txt").exists()


def test_a_damaged_or_foreign_archive_is_refused(browsers):
    with pytest.raises(BrowserDownloadError, match="not a valid archive"):
        _install(browsers, b"this is not a zip file at all")
    with pytest.raises(BrowserDownloadError, match="does not contain Chrome"):
        _install(browsers, _zip({"readme.txt": b"hi"}))
    corrupt = bytearray(_chrome_zip())
    corrupt[len(corrupt) // 3] ^= 0xFF
    with pytest.raises(BrowserDownloadError):
        _install(browsers, bytes(corrupt))
    assert browsers.installed() == []


def test_a_browser_that_does_not_start_or_is_the_wrong_version_is_not_kept(browsers):
    with pytest.raises(BrowserDownloadError, match="does not start"):
        _install(browsers, verify=lambda exe: None)
    with pytest.raises(BrowserDownloadError, match="not 154.0.8037.93"):
        _install(browsers, verify=lambda exe: "153.0.1.1")
    assert browsers.installed() == [] and os.listdir(browsers.root) == []


@posix_only
def test_the_real_check_runs_the_program_and_reads_its_version(browsers):
    installed = _install(browsers, verify=None)                                    # no stub: the shell script is run
    assert dl.probe_version(installed.executable) == VERSION


def test_installing_a_version_again_replaces_it(browsers):
    first = _install(browsers)
    (first.folder / "stale.txt").write_text("old")
    second = _install(browsers)
    assert not (second.folder / "stale.txt").exists() and len(browsers.installed()) == 1


def test_a_failed_reinstall_keeps_the_working_copy(browsers):
    _install(browsers)
    with pytest.raises(BrowserDownloadError):
        _install(browsers, verify=lambda exe: None)
    assert browsers.active() is not None and browsers.active().version == VERSION


# ---------------------------------------------------------------- what is there

def test_installed_lists_newest_first_and_ignores_what_is_not_a_browser(browsers):
    for version in ("99.0.1.1", "154.0.8037.100", "154.0.8037.93"):
        _install(browsers, version=version, verify=lambda exe, v=version: v)
    root = browsers.root
    (root / f"150.0.1.1-{PLATFORM}").mkdir()                       # no program inside
    (root / "151.0.1.1-win64").mkdir()                             # another platform
    (root / ".download-1.zip").write_bytes(b"x")
    (root / "notes").mkdir()
    assert [b.version for b in browsers.installed()] == ["154.0.8037.100", "154.0.8037.93", "99.0.1.1"]
    assert browsers.has("99.0.1.1") and not browsers.has("150.0.1.1")
    assert dl.ManagedBrowsers(root / "missing", platform=PLATFORM).installed() == []
    assert dl.ManagedBrowsers(root / "missing", platform=PLATFORM).active() is None


def test_pruning_keeps_the_newest_few(browsers):
    for version in ("1.0.0.1", "2.0.0.1", "3.0.0.1", "4.0.0.1"):
        _install(browsers, version=version, verify=lambda exe, v=version: v)
    assert browsers.prune(keep=2) == ["2.0.0.1", "1.0.0.1"]
    assert [b.version for b in browsers.installed()] == ["4.0.0.1", "3.0.0.1"]
    assert browsers.prune(keep=0) == ["3.0.0.1"]                                   # never removes the last one
    assert [b.version for b in browsers.installed()] == ["4.0.0.1"]


def test_a_folder_that_cannot_be_removed_is_left_and_not_reported(browsers, monkeypatch):
    for version in ("1.0.0.1", "2.0.0.1"):
        _install(browsers, version=version, verify=lambda exe, v=version: v)
    monkeypatch.setattr(dl.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(PermissionError("in use")))
    assert browsers.prune(keep=1) == []


def test_leftovers_of_an_interrupted_download_are_cleared_but_installs_are_not(browsers):
    _install(browsers)
    (browsers.root / ".download-9.9.9.9-linux64.zip.part").write_bytes(b"half")
    (browsers.root / ".unpack-9.9.9.9-linux64-123").mkdir()
    browsers.clean_leftovers()
    assert os.listdir(browsers.root) == [f"{VERSION}-{PLATFORM}"]
