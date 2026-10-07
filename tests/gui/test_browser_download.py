"""The Download Chrome dialog and the places that open it, against a pretend Google."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from antidetect.application.browser_service import BrowserService
from antidetect.domain.errors import BrowserDownloadError
from antidetect.gui.dialogs.browser_download import BrowserDownloadDialog
from antidetect.gui.sidebar import SECTION_PROFILES, SECTION_SETTINGS
from antidetect.gui.workers import TaskRunner
from antidetect.infrastructure.chromium import downloader as dl
from tests.application.test_browser_service import PLATFORM, Response, Server, _put_managed, _archive
from tests.support.gui import spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture()
def google(gui_container):
    """The container's browser service pointed at a pretend Google and a throwaway downloads folder."""
    managed = dl.ManagedBrowsers(gui_container.config.data_dir / "browsers", platform=PLATFORM)
    gui_container.browser._managed = managed
    server = Server("154.0.8037.93")
    gui_container.browsers = BrowserService(
        gui_container.browser, managed, fetch=server.fetch, opener=server.opener,
        trusted=lambda u: True, verify=dl.probe_version,
    )
    server.managed = managed
    return server


def _open(gui_container) -> BrowserDownloadDialog:
    dialog = BrowserDownloadDialog(gui_container, TaskRunner())
    dialog.show()
    return dialog


def _closed(dialog) -> bool:
    return dialog._state == "closed"


# ------------------------------------------------------------------- the dialog

def test_it_checks_downloads_installs_and_closes_by_itself(gui_container, google):
    dialog = _open(gui_container)
    assert spin_wait(lambda: dialog.release is not None)
    assert "154.0.8037.93" in dialog.subtitle_label.text() and "official build" in dialog.subtitle_label.text()
    assert spin_wait(lambda: _closed(dialog), 15000)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.installed.version == "154.0.8037.93" and dialog.already is False
    assert gui_container.browser.browser_source() == "managed"


def test_it_says_how_far_the_download_has_got(gui_container, google):
    gate = threading.Event()

    class Slow(Response):
        def read(self, n=-1):
            data = super().read(n)
            if data:
                gate.wait(5)
            return data

    google.opener = lambda url: Slow(_archive("154.0.8037.93"))
    gui_container.browsers._opener = google.opener
    dialog = _open(gui_container)
    assert spin_wait(lambda: dialog._state == "downloading")
    gate.set()
    assert spin_wait(lambda: "MB" in dialog._detail.text() or _closed(dialog), 15000)
    assert spin_wait(lambda: _closed(dialog), 15000)


def test_when_the_newest_chrome_is_already_here_nothing_is_downloaded(gui_container, google):
    _put_managed(google.managed, "154.0.8037.93")
    dialog = _open(gui_container)
    assert spin_wait(lambda: _closed(dialog))
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.already is True and dialog.installed is None
    assert google.fetched == []


def test_a_failure_is_explained_and_can_be_retried(gui_container, google, monkeypatch):
    attempts = []

    def flaky(channel="Stable", *, platform=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise BrowserDownloadError("Could not reach Google's list of Chrome versions: offline")
        return Server.fetch(google, channel, platform=platform)

    gui_container.browsers._fetch = flaky
    dialog = _open(gui_container)
    assert spin_wait(lambda: dialog._state == "error")
    assert "Could not reach Google" in dialog._error.text() and dialog._error.isVisibleTo(dialog)
    assert dialog._retry.isVisibleTo(dialog) and dialog._stop.text() == "Close"
    dialog._retry.click()
    assert spin_wait(lambda: _closed(dialog), 15000)
    assert dialog.result() == QDialog.DialogCode.Accepted and len(attempts) == 2


def test_cancelling_while_it_downloads_leaves_nothing_behind(gui_container, google):
    gate = threading.Event()

    class Held(Response):
        def read(self, n=-1):
            gate.wait(5)
            return super().read(n)

    gui_container.browsers._opener = lambda url: Held(_archive("154.0.8037.93"))
    dialog = _open(gui_container)
    assert spin_wait(lambda: dialog._state == "downloading")
    dialog._stop.click()
    gate.set()
    assert dialog.result() == QDialog.DialogCode.Rejected and _closed(dialog)
    TaskRunner.drain_all()
    assert google.managed.installed() == []
    root = google.managed.root
    assert not root.exists() or [p.name for p in root.iterdir()] == []


def test_it_cannot_be_cancelled_once_it_is_unpacking(gui_container, google):
    dialog = BrowserDownloadDialog(gui_container, TaskRunner())          # never shown: no task is started
    dialog._state = "installing"
    dialog.reject()
    assert dialog._state == "installing"
    assert not dialog._cancel.is_set()                                   # nothing was told to stop
    dialog._state = "idle"
    dialog.reject()
    assert dialog._state == "closed" and dialog._cancel.is_set()


def test_the_dialog_explains_that_the_version_stays_put(gui_container, google):
    dialog = _open(gui_container)
    assert "until you update it" in dialog._note.text()
    dialog.reject()


# ----------------------------------------------------------- the places that open it

def test_the_banner_asks_to_download_chrome(window, gui_container, monkeypatch):
    monkeypatch.setattr(BrowserDownloadDialog, "exec", lambda self: QDialog.DialogCode.Rejected)   # the window's own handler
    page = window.page(SECTION_PROFILES)
    asked = []
    page.browserDownloadRequested.connect(lambda: asked.append(1))
    page.set_browser_found(False)
    assert page._banner.isVisibleTo(page) and "about 150 MB" in page._banner._text.text()
    page._banner._button.click()
    assert asked == [1]


def test_settings_offers_download_then_update(window, gui_container, google, monkeypatch):
    monkeypatch.setattr(BrowserDownloadDialog, "exec", lambda self: QDialog.DialogCode.Rejected)   # the window's own handler
    settings = window.page(SECTION_SETTINGS)
    asked = []
    settings.browserDownloadRequested.connect(lambda: asked.append(1))
    settings.show_browser(gui_container.browser_info())
    assert settings._download.text() == "Download Chrome"
    settings._download.click()
    assert asked == [1]

    gui_container.set_browser_path(None)                       # the window's fixture chose a browser; that would win
    _put_managed(google.managed, "154.0.8037.93")
    settings.show_browser(gui_container.browser_info())
    assert settings._download.text() == "Update Chrome"
    assert "Downloaded by the app" in settings._r_browser.description.text()


def test_settings_names_where_the_browser_came_from(window, gui_container, google, tmp_path):
    settings = window.page(SECTION_SETTINGS)
    mine = tmp_path / "my-chrome"
    mine.write_text("#!/bin/sh\necho 'Google Chrome 150.0.1.2'\n")
    mine.chmod(0o755)
    gui_container.set_browser_path(str(mine))
    settings.show_browser(gui_container.browser_info())
    assert "Chosen by you" in settings._r_browser.description.text()


def test_the_command_palette_and_the_window_reach_it(window, monkeypatch):
    assert "Download Chrome…" in {entry.title for entry in window.palette_entries()}


def test_a_finished_download_clears_an_older_chosen_path_and_tells_the_user(window, gui_container, google, monkeypatch, tmp_path):
    mine = tmp_path / "old-choice"
    mine.write_text("x")
    gui_container.set_browser_path(str(mine))
    _put_managed(google.managed, "154.0.8037.93")

    def finish(self):
        self.release = dl.Release("154.0.8037.93", "https://x", PLATFORM)
        self.already = False
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BrowserDownloadDialog, "exec", finish)
    window.download_browser()
    assert gui_container.browser.browser_source() == "managed"                  # the path chosen before no longer wins
    texts = " ".join(label.text() for toast in window.toasts._toasts for label in toast.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "154.0.8037.93" in texts and "profiles now run on it" in texts


def test_cancelling_the_dialog_changes_nothing(window, gui_container, google, monkeypatch, tmp_path):
    mine = tmp_path / "keep-me"
    mine.write_text("x")
    gui_container.set_browser_path(str(mine))
    monkeypatch.setattr(BrowserDownloadDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.download_browser()
    assert gui_container.browser.browser_source() == "configured" and window.toasts.count() == 0
