"""``antidetect browser``: status, download and the update check, against a pretend Google."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from antidetect.application.browser_service import BrowserService
from antidetect.cli.commands import browser_commands as bc
from antidetect.cli.main import main
from antidetect.domain.errors import BrowserDownloadError, ChromiumNotFoundError
from antidetect.infrastructure.chromium import chromium_manager as cm
from antidetect.infrastructure.chromium import downloader as dl
from tests.application.test_browser_service import PLATFORM, Server, _put_managed


@pytest.fixture()
def container(tmp_path, monkeypatch):
    from antidetect.config import AppConfig
    from antidetect.container import bootstrap

    monkeypatch.delenv("ANTIDETECT_CHROMIUM_PATH", raising=False)
    monkeypatch.setattr(cm, "discover_chromium", lambda: (_ for _ in ()).throw(ChromiumNotFoundError()))
    c = bootstrap(AppConfig(data_dir=tmp_path / "data"))
    managed = dl.ManagedBrowsers(c.config.data_dir / "browsers", platform=PLATFORM)
    c.browser._managed = managed
    server = Server("154.0.8037.93")
    c.browsers = BrowserService(c.browser, managed, fetch=server.fetch, opener=server.opener,
                                trusted=lambda u: True, verify=dl.probe_version)
    c.pretend_google = server
    yield c
    c.close()


def _args(**kw) -> Namespace:
    return Namespace(channel="Stable", **kw)


def test_status_without_any_chrome_says_how_to_get_one(container, capsys):
    bc.cmd_status(container, _args())
    out = capsys.readouterr().out
    assert "none found" in out and "antidetect browser download" in out


def test_download_installs_chrome_and_reports_it(container, capsys):
    bc.cmd_download(container, _args())
    captured = capsys.readouterr()
    assert "Chrome 154.0.8037.93 installed" in captured.out
    assert "Running profiles use: Chrome downloaded by the app 154.0.8037.93" in captured.out
    assert "Downloading Chrome: 100%" in captured.err                       # progress goes to stderr, results to stdout
    bc.cmd_status(container, _args())
    status = capsys.readouterr().out
    assert "Chrome downloaded by the app" in status and "(in use)" in status


def test_downloading_again_is_a_quiet_no_op(container, capsys):
    bc.cmd_download(container, _args())
    capsys.readouterr()
    bc.cmd_download(container, _args())
    assert "already downloaded" in capsys.readouterr().out and container.pretend_google.fetched == ["154.0.8037.93"]


def test_a_path_the_user_had_chosen_is_cleared_so_the_downloaded_chrome_is_used(container, capsys, tmp_path):
    mine = tmp_path / "my-chrome"
    mine.write_text("x")
    container.set_browser_path(str(mine))
    assert container.browsers.status().source == "configured"
    bc.cmd_download(container, _args())
    assert "path you had chosen was cleared" in capsys.readouterr().out
    assert container.browsers.status().source == "managed"
    assert container.settings.get(container.BROWSER_PATH_KEY).value == ""


def test_the_environment_variable_still_wins_and_the_command_says_so(container, capsys, tmp_path, monkeypatch):
    mine = tmp_path / "env-chrome"
    mine.write_text("x")
    container.browser.set_chromium_path(mine)                                 # what ANTIDETECT_CHROMIUM_PATH does at start-up
    bc.cmd_download(container, _args())
    assert "takes precedence over the downloaded Chrome" in capsys.readouterr().out


def test_check_update_reports_each_situation(container, capsys):
    bc.cmd_check_update(container, _args())
    assert "Chrome 154.0.8037.93" in capsys.readouterr().out                 # nothing downloaded: Google's is on offer
    bc.cmd_download(container, _args())
    capsys.readouterr()
    bc.cmd_check_update(container, _args())
    assert "up to date" in capsys.readouterr().out
    container.pretend_google.newest = "155.0.1.1"
    bc.cmd_check_update(container, _args())
    assert "Chrome 155.0.1.1" in capsys.readouterr().out


def test_a_download_error_reaches_the_user_as_a_message_not_a_traceback(cli_env, capsys, monkeypatch):
    def unreachable(self, channel="Stable"):
        raise BrowserDownloadError("Could not reach Google's list of Chrome versions: offline")

    monkeypatch.setattr(BrowserService, "latest", unreachable)
    assert main(["browser", "download"]) == 1
    assert "Could not reach Google" in capsys.readouterr().err


def test_the_group_is_reachable_from_the_command_line(cli_env, capsys):
    assert main(["browser", "status"]) == 0
    assert "BROWSER" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["browser", "download", "--channel", "Nightly"])


def test_path_prints_only_the_path_and_fails_when_there_is_no_browser(container, capsys):
    with pytest.raises(ValueError, match="antidetect browser download"):
        bc.cmd_path(container, _args())
    bc.cmd_download(container, _args())
    capsys.readouterr()
    bc.cmd_path(container, _args())
    printed = capsys.readouterr().out.strip()
    assert printed == str(container.browsers.status().path) and "\n" not in printed
