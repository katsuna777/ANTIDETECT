"""Audit log: every state-changing operation leaves a session-log row.

Sources covered: profiles CRUD, configurations CRUD, cookies backup/restore,
GUI preference changes, worker failures (central TaskRunner sink).
"""

from __future__ import annotations

import sqlite3

import pytest

from antidetect.gui.workers import TaskRunner
from tests.support.gui import spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def _messages(gui_container, source):
    return [
        entry.message
        for entry in gui_container.logs.all_logs()
        if entry.source == source
    ]


def _levels(gui_container, source):
    return [
        (entry.level, entry.message)
        for entry in gui_container.logs.all_logs()
        if entry.source == source
    ]


# ------------------------------------------------------------ profiles


def test_profile_crud_is_logged(gui_container):
    profile = gui_container.profiles.create_profile("audited")
    gui_container.profiles.update_profile(profile.id, name="audited-2")
    dup = gui_container.profiles.duplicate_profile(profile.id)
    gui_container.profiles.delete_profile(dup.id)
    gui_container.profiles.delete_profile(profile.id)

    messages = _messages(gui_container, "profiles")
    assert any("created" in message for message in messages)
    assert any("updated" in message for message in messages)
    assert any("duplicated" in message for message in messages)
    assert sum("deleted" in message for message in messages) >= 2


def test_profile_proxy_assignment_is_logged(gui_container):
    profile = gui_container.profiles.create_profile("proxy-log")
    gui_container.profiles.assign_proxy(profile.id, None)
    messages = _messages(gui_container, "profiles")
    assert any("detached" in message for message in messages)


# ------------------------------------------------------------ configurations


def test_configuration_crud_is_logged(gui_container):
    cfg = gui_container.configurations.create_configuration(
        "log-me", timezone="Europe/Berlin"
    )
    gui_container.configurations.update_configuration(
        cfg.id, timezone="Europe/Paris"
    )
    dup = gui_container.configurations.duplicate_configuration(cfg.id)
    gui_container.configurations.delete_configuration(dup.id)
    gui_container.configurations.delete_configuration(cfg.id)

    messages = _messages(gui_container, "configurations")
    assert any("created" in message for message in messages)
    assert any("updated" in message for message in messages)
    assert any("duplicated" in message for message in messages)
    assert sum("deleted" in message for message in messages) >= 2


def test_configuration_generate_is_logged(gui_container):
    gui_container.configurations.generate_configuration(name="gen-log", platform="windows")

    messages = _messages(gui_container, "configurations")
    assert any("generated" in message for message in messages)


# ------------------------------------------------------------ cookies


def _seed_cookies_db(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE cookies (key TEXT, value TEXT)")
        conn.execute("INSERT INTO cookies VALUES ('k', 'v')")
        conn.commit()
    finally:
        conn.close()


def test_cookie_backup_and_restore_are_logged(gui_container, tmp_path):
    from pathlib import Path

    profile = gui_container.profiles.create_profile("cookie-log")
    cookies_db = Path(profile.profile_path) / "Default" / "Cookies"
    _seed_cookies_db(cookies_db)

    exported = gui_container.cookies.export(profile.id)
    gui_container.cookies.import_(profile.id, Path(exported))

    messages = _messages(gui_container, "cookies")
    assert any("exported" in message for message in messages)
    assert any("imported" in message for message in messages)


# ------------------------------------------------------------ worker errors


def _run_failing_task(error_sink):
    from antidetect.domain.errors import ProfileNotFoundError

    runner = TaskRunner(error_sink=error_sink)
    seen: dict = {}

    def boom(progress):
        raise ProfileNotFoundError(4242)

    runner.submit(
        boom,
        on_error=lambda exc: seen.update(error=exc),
        on_finished=lambda: seen.update(finished=True),
    )
    assert spin_wait(lambda: seen.get("finished", False), timeout_ms=6000)
    runner.shutdown()
    return seen


def test_worker_failures_reach_the_log_and_the_handler():
    records: list = []

    class Sink:
        def error(self, source, message, extra=None):
            records.append((source, message))

    seen = _run_failing_task(Sink())
    assert seen["error"] is not None
    assert records and records[0][0] == "gui"
    assert "4242" in records[0][1]


def test_successful_tasks_do_not_log_errors():
    records: list = []

    class Sink:
        def error(self, source, message, extra=None):
            records.append((source, message))

    runner = TaskRunner(error_sink=Sink())
    seen: dict = {}
    runner.submit(
        lambda progress: "ok",
        on_result=lambda value: seen.update(result=value),
        on_finished=lambda: seen.update(finished=True),
    )
    assert spin_wait(lambda: seen.get("finished", False), timeout_ms=6000)
    runner.shutdown()
    assert seen["result"] == "ok"
    assert records == []


# ------------------------------------------------------------ GUI preferences


def test_theme_and_language_changes_are_logged(gui_container):
    from antidetect.gui.main_window import MainWindow

    window = MainWindow(gui_container)
    window.set_theme("dark")
    window.set_language("ru")
    window.close()

    messages = _messages(gui_container, "gui")
    assert any("Theme switched to dark" in message for message in messages)
    assert any("Language switched to ru" in message for message in messages)


def test_logs_page_clear_leaves_an_audit_row(gui_container, qapp):
    from PySide6.QtWidgets import QWidget

    from antidetect.gui.components import ToastHost
    from antidetect.gui.pages.logs import LogsPage
    from antidetect.gui.workers import TaskRunner as Runner

    host = QWidget()
    page = LogsPage(gui_container, Runner(), ToastHost(host))
    page._cleared()
    assert any("Log cleared" in message for message in _messages(gui_container, "gui"))
    page.shutdown()
    page.close()
