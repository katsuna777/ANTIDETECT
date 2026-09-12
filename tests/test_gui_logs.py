"""Log page: registration, live polling and the export/clear task round-trips."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.gui.main_window import MainWindow
from app.gui.widgets.pages.logs_page import LogsPage
from app.gui.widgets.sidebar import SECTION_LOGS
from app.gui.workers import tasks
from tests.gui_helpers import spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def test_logs_page_is_registered_in_window(gui_container):
    window = MainWindow(gui_container)
    page = window.page(SECTION_LOGS)
    assert isinstance(page, LogsPage)
    window.show_section(SECTION_LOGS)
    assert window.current_section() == SECTION_LOGS
    assert window._sidebar._buttons[SECTION_LOGS].isChecked()
    window.close()


def test_poll_appends_existing_entries(gui_container):
    gui_container.logs.info("app", "hello-from-test")

    window = MainWindow(gui_container)
    page = window.page(SECTION_LOGS)
    page._poll()

    assert spin_wait(lambda: page._list.count() >= 1)
    combined = [page._list.item(i).text() for i in range(page._list.count())]
    assert any("hello-from-test" in text for text in combined)
    window.close()


def test_poll_is_incremental(gui_container):
    container_logs = gui_container.logs
    window = MainWindow(gui_container)
    page = window.page(SECTION_LOGS)

    page._poll()
    assert spin_wait(lambda: page._last_id > 0)
    before = page._last_id

    container_logs.info("proxy", "incremental-entry")
    page._poll()
    assert spin_wait(lambda: page._last_id > before)
    combined = [page._list.item(i).text() for i in range(page._list.count())]
    assert any("incremental-entry" in text for text in combined)
    window.close()


def test_export_task_writes_file(gui_container, tmp_path: Path):
    gui_container.logs.info("app", "export me")
    from app.gui.workers.worker import TaskFunction

    task: TaskFunction = tasks.export_logs(gui_container, tmp_path / "out" / "log.txt")
    result = task(lambda done, total: None)
    assert result == tmp_path / "out" / "log.txt"
    text = (tmp_path / "out" / "log.txt").read_text(encoding="utf-8")
    assert "export me" in text


def test_list_logs_task_is_incremental(gui_container):
    gui_container.logs.info("app", "first")
    after = gui_container.logs.latest_id()
    gui_container.logs.info("app", "second")

    entries = tasks.list_logs(gui_container, after_id=after)(lambda d, t: None)
    assert [e.message for e in entries] == ["second"]


def test_clear_logs_task_wipes_session(gui_container):
    gui_container.logs.info("app", "to be cleared")
    cleared = tasks.clear_logs(gui_container)(lambda d, t: None)
    assert cleared >= 1
    assert gui_container.logs.count() == 0