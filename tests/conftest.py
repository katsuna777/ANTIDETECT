from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from antidetect.application.profile_path_resolver import ProfilePathResolver
from antidetect.application.profile_service import ProfileService
from antidetect.config import AppConfig
from antidetect.domain.enums.profile_status import ProfileStatus
from antidetect.infrastructure.chromium.chromium_manager import ChromiumManager
from antidetect.infrastructure.database.connection import Database
from antidetect.infrastructure.database.migrations import run_migrations
from antidetect.infrastructure.database.repositories.browser_configuration_repository import (
    SqliteBrowserConfigurationRepository,
)
from antidetect.infrastructure.database.repositories.profile_repository import (
    SqliteProfileRepository,
)
from antidetect.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from antidetect.infrastructure.database.repositories.settings_repository import (
    SqliteSettingsRepository,
)


#: Tests that run a stub browser written as a POSIX script (or read ``ps``), which Windows cannot execute
#: ("[WinError 193] %1 is not a valid Win32 application"), plus one that assumes no Chrome is installed (a
#: Windows runner has one). They exercise logic that is the same on every OS; what only Windows can show -
#: a real Chrome starting and being fingerprinted - is the job of the "Live browser checks" workflow
#: (live.yml), which runs the Chrome the app downloads.
_NEEDS_A_POSIX_STUB_BROWSER = frozenset({
    "tests/application/test_browser_service.py::test_a_downloaded_chrome_is_used_when_nothing_was_chosen",
    "tests/application/test_browser_service.py::test_a_failed_install_does_not_change_what_runs",
    "tests/application/test_browser_service.py::test_a_profile_really_starts_on_the_downloaded_chrome",
    "tests/application/test_browser_service.py::test_asking_again_for_a_version_already_here_downloads_nothing",
    "tests/application/test_browser_service.py::test_installing_the_latest_downloads_unpacks_and_makes_it_the_active_browser",
    "tests/application/test_browser_service.py::test_only_the_newest_versions_are_kept",
    "tests/application/test_browser_service.py::test_status_names_the_browser_its_version_and_the_downloaded_ones",
    "tests/cli/test_cli_api.py::test_serve_runs_headless_answers_requests_and_stops_cleanly",
    "tests/cli/test_cli_browser.py::test_a_path_the_user_had_chosen_is_cleared_so_the_downloaded_chrome_is_used",
    "tests/cli/test_cli_browser.py::test_check_update_reports_each_situation",
    "tests/cli/test_cli_browser.py::test_download_installs_chrome_and_reports_it",
    "tests/cli/test_cli_browser.py::test_downloading_again_is_a_quiet_no_op",
    "tests/cli/test_cli_browser.py::test_path_prints_only_the_path_and_fails_when_there_is_no_browser",
    "tests/cli/test_cli_browser.py::test_the_environment_variable_still_wins_and_the_command_says_so",
    "tests/cli/test_cli_stage3.py::test_cli_end_to_end_flow",
    "tests/cli/test_cli_stage3.py::test_cookies_import_rejects_running_profile",
    "tests/gui/test_browser_download.py::test_a_failure_is_explained_and_can_be_retried",
    "tests/gui/test_browser_download.py::test_it_checks_downloads_installs_and_closes_by_itself",
    "tests/gui/test_browser_download.py::test_it_says_how_far_the_download_has_got",
    "tests/infrastructure/chromium/test_chromium_manager.py::test_discover_chromium_finds_patch_command",
    "tests/infrastructure/stealth/test_stealth_cdp.py::test_stealth_launches_without_a_startup_window",
    "tests/infrastructure/stealth/test_stealth_cdp.py::test_the_colour_profile_follows_the_claimed_display",
    "tests/integration/test_cli_integration.py::test_full_acceptance_flow",
})


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason="needs a POSIX stub browser / ps; real Chrome on Windows is covered by live.yml")
    for item in items:
        if item.nodeid in _NEEDS_A_POSIX_STUB_BROWSER:
            item.add_marker(skip)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture(autouse=True)
def _stub_proxy_probe(monkeypatch):
    """Integration tests never hit real proxies; the launch-time probes must
    always succeed so test flows are not blocked by real network checks."""
    monkeypatch.setattr(
        "antidetect.infrastructure.chromium.chromium_manager.probe_proxy",
        lambda _proxy, _timeout: True,
    )
    monkeypatch.setattr(
        "antidetect.infrastructure.proxy.transport.probe_google",
        lambda _proxy, _timeout=8.0: True,
    )


@pytest.fixture(autouse=True)
def _no_stealth_for_stub_browsers(monkeypatch):
    """Stub browser binaries expose no DevTools endpoint, so the CDP stealth
    layer is off for every test except those that opt in (they delenv this)."""
    monkeypatch.setenv("ANTIDETECT_DISABLE_STEALTH", "1")


@pytest.fixture()
def config(data_dir: Path) -> AppConfig:
    return AppConfig(data_dir=data_dir)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    run_migrations(database)
    yield database
    database.close()


@pytest.fixture()
def profile_repo(db: Database) -> SqliteProfileRepository:
    return SqliteProfileRepository(db)


@pytest.fixture()
def configuration_repo(db: Database) -> SqliteBrowserConfigurationRepository:
    return SqliteBrowserConfigurationRepository(db)


@pytest.fixture()
def settings_repo(db: Database) -> SqliteSettingsRepository:
    return SqliteSettingsRepository(db)


@pytest.fixture()
def fake_chromium(tmp_path: Path) -> Path:
    """A Python script that mimics a long-running Chromium process (any OS)."""
    marker = tmp_path / "fake_chromium.args"
    script = tmp_path / "fake_chromium.py"
    script.write_text(
        "import sys, time, signal\n"
        "if '--version' in sys.argv:\n"
        '    print("FakeChromium 152.0.0.0")\n'
        "    sys.exit(0)\n"
        f"open({str(marker)!r}, 'w').write(' '.join(sys.argv[1:]))\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "try:\n"
        "    signal.signal(signal.SIGBREAK, lambda *_: sys.exit(0))\n"
        "except (AttributeError, OSError, ValueError):\n"
        "    pass\n"
        "while True:\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        wrapper = tmp_path / "fake_chromium.cmd"
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
        return wrapper
    shim = tmp_path / "fake_chromium.sh"
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def build_service(
    config: AppConfig,
    chromium: Path,
    database: Database | None = None,
    proxies: SqliteProxyRepository | None = None,
    geo_lookup=None,
):
    from antidetect.application.fingerprint.generator import ConfigurationGenerator

    db = database or Database(config.database_path)
    run_migrations(db)
    manager = ChromiumManager(
        chromium_path=chromium, logs_dir=config.logs_dir, enable_stealth=False
    )
    proxies = proxies or SqliteProxyRepository(db)
    service = ProfileService(
        profiles=SqliteProfileRepository(db),
        configurations=SqliteBrowserConfigurationRepository(db),
        settings=SqliteSettingsRepository(db),
        browsers=manager,
        path_resolver=ProfilePathResolver(config.profiles_dir),
        proxies=proxies,
        generator=ConfigurationGenerator(),
        geo_lookup=geo_lookup,
    )
    return service, db


@pytest.fixture()
def live_service(config: AppConfig, fake_chromium: Path):
    test_config = AppConfig(
        data_dir=config.data_dir,
        chromium_path=fake_chromium,
        logs_dir=config.data_dir / "logs",
    )
    service, db = build_service(test_config, fake_chromium)
    yield service, db
    try:
        for profile in service.list_profiles():
            if profile.status is ProfileStatus.RUNNING:
                service.stop_profile(profile.id)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# GUI ("offscreen" platform, no pytest-qt dependency)
# --------------------------------------------------------------------------- #


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def qapp():
    """A single headless QApplication shared by every GUI test session."""
    app = _qapp()
    yield app


@pytest.fixture()
def gui_container(tmp_path: Path):
    """A real bootstrapped Container pointing at a throwaway data dir."""
    from antidetect.config import AppConfig
    from antidetect.container import bootstrap

    container = bootstrap(AppConfig(data_dir=tmp_path / "data"))
    yield container
    # Drain every GUI worker pool first: closing SQLite while a worker thread
    # is mid-query would segfault the test process.
    from antidetect.gui.workers import TaskRunner

    TaskRunner.drain_all()
    container.close()


@pytest.fixture(autouse=True)
def _tests_never_download_chrome(monkeypatch):
    """No test may reach Google: a test that opens the real "Download Chrome" flow would fetch ~150 MB.

    Tests that need a download give the service their own pretend server. Anything that falls through to
    the real network is recorded here and fails the test, instead of quietly downloading a browser.
    """
    from antidetect.infrastructure.chromium import downloader

    attempts: list[str] = []

    def refuse(url, timeout=30.0):
        attempts.append(url)
        raise OSError("the network is switched off in tests")

    monkeypatch.setattr(downloader, "_open", refuse)
    yield
    assert not attempts, f"a test tried to reach the network for Chrome: {attempts}"

