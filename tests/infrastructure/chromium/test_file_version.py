"""Windows prints nothing for ``chrome.exe --version``: the version is read from the exe's resource instead."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from antidetect.infrastructure.chromium import chromium_manager, downloader
from antidetect.infrastructure.chromium.file_version import windows_file_version


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(chromium_manager, "_BINARY_VERSION_CACHE", {})


def _no_process(*_a, **_k):
    raise AssertionError("the browser must not be started to learn its version when the exe states it")


def test_the_manager_reads_the_stamped_version_without_starting_the_browser(monkeypatch):
    monkeypatch.setattr(chromium_manager, "windows_file_version", lambda binary: "155.0.8059.39")
    monkeypatch.setattr(subprocess, "run", _no_process)
    text = chromium_manager.chromium_binary_version(Path("C:/chrome/chrome.exe"))
    assert text == "Chrome 155.0.8059.39"
    assert chromium_manager.chromium_binary_major(Path("C:/chrome/chrome.exe")) == 155


def test_the_downloader_accepts_a_browser_whose_version_is_only_in_the_exe(monkeypatch):
    monkeypatch.setattr(downloader, "windows_file_version", lambda executable: "155.0.8059.39")
    monkeypatch.setattr(subprocess, "run", _no_process)
    assert downloader.probe_version(Path("C:/chrome/chrome.exe")) == "155.0.8059.39"


def test_without_a_stamped_version_the_command_line_answer_is_used(monkeypatch):
    monkeypatch.setattr(chromium_manager, "windows_file_version", lambda binary: None)
    done = subprocess.CompletedProcess([], 0, stdout="Google Chrome 152.0.7977.83\n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    assert chromium_manager.chromium_binary_version(Path("/opt/chrome")) == "Google Chrome 152.0.7977.83"


@pytest.mark.skipif(sys.platform == "win32", reason="off Windows there is no version resource to read")
def test_off_windows_there_is_nothing_to_read(tmp_path):
    assert windows_file_version(tmp_path / "chrome") is None


@pytest.mark.skipif(sys.platform != "win32", reason="reads a real Windows executable")
def test_a_real_windows_executable_states_its_version():
    python = Path(sys.base_prefix) / "python.exe"
    found = windows_file_version(python)
    assert found and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", found), found
    assert found.startswith(f"{sys.version_info.major}.{sys.version_info.minor}."), found
    assert windows_file_version(python.with_name("no-such-file.exe")) is None
