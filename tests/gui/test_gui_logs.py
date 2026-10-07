"""Log page: registration, live polling, filtering and the clear/export tasks."""

from __future__ import annotations

import pytest

from antidetect.gui.main_window import MainWindow
from antidetect.gui.models.logs import LINE_ROLE
from antidetect.gui.pages.logs import LogsPage
from tests.support.gui import logs_page, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def _visible_messages(page: LogsPage) -> list[str]:
    return [page._filter.index(i, 0).data(LINE_ROLE).message for i in range(page._filter.rowCount())]


@pytest.fixture()
def logs_window(gui_container):
    window = MainWindow(gui_container)
    window.show()
    logs_page(window)
    yield window
    window.close()


def test_logs_page_lives_in_the_settings_tabs(logs_window):
    assert isinstance(logs_page(logs_window), LogsPage)
    assert logs_window.current_section() == "settings"


def test_poll_shows_existing_entries_and_is_incremental(gui_container):
    gui_container.logs.info("app", "hello-from-test")
    window = MainWindow(gui_container)
    window.show()
    page = logs_page(window)
    page.poll()
    assert spin_wait(lambda: "hello-from-test" in _visible_messages(page))
    before = page._model.last_id
    gui_container.logs.info("proxy", "incremental-entry")
    page.poll()
    assert spin_wait(lambda: "incremental-entry" in _visible_messages(page))
    assert page._model.last_id > before
    window.close()


def test_level_and_text_filters(gui_container):
    gui_container.logs.error("app", "boom-error")
    gui_container.logs.info("app", "calm-info")
    window = MainWindow(gui_container)
    window.show()
    page = logs_page(window)
    page.poll()
    assert spin_wait(lambda: "boom-error" in _visible_messages(page))
    page._level.button("3").click()  # errors only
    assert "boom-error" in _visible_messages(page) and "calm-info" not in _visible_messages(page)
    page._level.button("0").click()
    page._search.setText("calm")
    assert _visible_messages(page) == ["calm-info"]
    window.close()


def test_clear_empties_the_view_and_leaves_an_audit_row(logs_window, gui_container):
    page = logs_page(logs_window)
    gui_container.logs.info("app", "to-be-cleared")
    page.poll()
    assert spin_wait(lambda: "to-be-cleared" in _visible_messages(page))
    page._clear.click()
    assert spin_wait(lambda: "to-be-cleared" not in _visible_messages(page))
    page.poll()
    assert spin_wait(lambda: "Log cleared" in _visible_messages(page))


def test_empty_state_shows_when_the_filter_matches_nothing(logs_window, gui_container):
    page = logs_page(logs_window)
    gui_container.logs.info("app", "something")
    page.poll()
    assert spin_wait(lambda: page._filter.rowCount() > 0 and page._stack.currentWidget() is page._card)
    page._search.setText("zzz-no-such-line")
    assert page._stack.currentWidget() is page._empty
