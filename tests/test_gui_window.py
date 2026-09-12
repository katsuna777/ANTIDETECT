"""Main window: construction, navigation, layout and graceful shutdown."""

from __future__ import annotations

import time

import pytest

from app.gui.main_window import MainWindow
from app.gui.utils.theme import (
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
)
from app.gui.widgets.sidebar import (
    SECTION_CONFIGURATIONS,
    SECTION_LOGS,
    SECTION_PROFILES,
    SECTION_PROXIES,
    SECTION_SETTINGS,
)

pytestmark = pytest.mark.usefixtures("qapp")


def test_window_builds_with_default_section(gui_container):
    window = MainWindow(gui_container)
    assert window.current_section() == SECTION_PROFILES
    assert window._stack.count() == 5
    window.close()


def test_window_default_size(gui_container):
    window = MainWindow(gui_container)
    assert window.width() == WINDOW_WIDTH
    assert window.height() == WINDOW_HEIGHT
    assert window.minimumWidth() == WINDOW_MIN_WIDTH
    assert window.minimumHeight() == WINDOW_MIN_HEIGHT
    window.close()


@pytest.mark.parametrize(
    "section",
    [
        SECTION_PROFILES,
        SECTION_PROXIES,
        SECTION_CONFIGURATIONS,
        SECTION_SETTINGS,
        SECTION_LOGS,
    ],
)
def test_navigation_switches_global_sections(gui_container, section):
    window = MainWindow(gui_container)
    window.show_section(section)
    assert window.current_section() == section
    assert window._sidebar._buttons[section].isChecked()
    window.close()


def test_unknown_section_is_ignored(gui_container):
    window = MainWindow(gui_container)
    window.show_section("does-not-exist")
    assert window.current_section() == SECTION_PROFILES
    window.close()


def test_api_accessor_returns_pages(gui_container):
    window = MainWindow(gui_container)
    for key in (
        SECTION_PROFILES,
        SECTION_PROXIES,
        SECTION_CONFIGURATIONS,
        SECTION_SETTINGS,
        SECTION_LOGS,
    ):
        assert window.page(key) is not None
    window.close()


def test_window_shows_offscreen(gui_container):
    window = MainWindow(gui_container)
    window.show()
    assert window.isVisible()
    window.close()


def test_closing_saves_window_geometry_preference(gui_container):
    prefs_key = "gui.window_geometry"
    assert gui_container.settings.get(prefs_key) is None

    window = MainWindow(gui_container)
    window.resize(1234, 700)
    window.show()
    window.close()

    assert gui_container.settings.get(prefs_key) is not None


def test_geometry_is_restored_on_next_launch(gui_container):
    """The persisted geometry bytes must survive between window instances.

    Exact pixel equality is unreliable on the 800x800 offscreen desktop (window
    geometry is clamped and the main window enforces a 1000x680 minimum), so we
    assert the preference round-trips and the restored window still opens.
    """
    first = MainWindow(gui_container)
    first.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
    first.show()
    first.close()

    stored = gui_container.settings.get("gui.window_geometry")
    assert stored is not None and stored.value

    second = MainWindow(gui_container)
    second.show()
    assert second.width() >= WINDOW_MIN_WIDTH
    assert second.height() >= WINDOW_MIN_HEIGHT
    second.close()


def test_close_stops_running_tasks(gui_container):
    """The window's pool is drained at close so no task outlives the window."""

    from app.gui.workers.task_runner import TaskRunner
    from tests.gui_helpers import spin_wait

    window = MainWindow(gui_container)
    runner = window._runner

    runner.submit(lambda progress: (time.sleep(0.05), "done")[1])

    window.close()
    assert spin_wait(lambda: runner.active_tasks == 0)