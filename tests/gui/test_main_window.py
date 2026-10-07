"""Main window: navigation, lazy pages, theme, language, quitting with running profiles."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog, QLabel

from antidetect.gui.components import ConfirmDialog
from antidetect.gui.preferences import Preferences
from antidetect.gui.sidebar import (
    SECTION_ACTIVITY,
    SECTION_API,
    SECTION_PROFILES,
    SECTION_PROXIES,
    SECTION_SETTINGS,
    SECTION_TRASH,
    SECTIONS,
)
from tests.support.gui import make_profile, settle, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def test_sidebar_lists_the_six_sections(window):
    assert SECTIONS == (SECTION_PROFILES, SECTION_PROXIES, SECTION_ACTIVITY, SECTION_API, SECTION_TRASH, SECTION_SETTINGS)
    assert [b.text() for b in window._sidebar._buttons.values()] == [
        "Profiles", "Proxies", "Activity", "API", "Trash", "Settings"]


def test_navigation_shortcuts_and_unknown_sections(window):
    assert window.current_section() == SECTION_PROFILES
    for key in (SECTION_PROXIES, SECTION_ACTIVITY, SECTION_API, SECTION_TRASH, SECTION_SETTINGS, SECTION_PROFILES):
        window.show_section(key)
        assert window.current_section() == key
        assert window._sidebar._buttons[key].isChecked()
    assert len(window.actions()) >= len(SECTIONS)  # Ctrl+1..6
    window.show_section("nope")  # unknown section is ignored
    assert window.current_section() == SECTION_PROFILES
    assert window.page("nope") is None


def test_pages_are_built_on_first_use_only(window):
    assert set(window._pages) == {SECTION_PROFILES}
    window.show_section(SECTION_TRASH)
    assert set(window._pages) == {SECTION_PROFILES, SECTION_TRASH}
    assert window.page(SECTION_TRASH) is window.page(SECTION_TRASH)


def test_theme_toggle_persists_and_flips_the_sidebar_icon_tooltip(window, gui_container):
    first = window.toggle_theme()
    assert first in ("light", "dark") and Preferences(gui_container.settings).get_theme() == first
    assert window.current_theme() == first
    tooltip = window._sidebar._theme_button.toolTip()
    second = window.toggle_theme()
    assert second != first and window._sidebar._theme_button.toolTip() != tooltip


def test_language_switch_retranslates_everything_built_and_persists(window, gui_container):
    window.show_section(SECTION_SETTINGS)  # a page built *before* the switch...
    window.set_language("ru")
    assert window._sidebar._buttons[SECTION_PROFILES].text() == "Профили"
    assert window.page(SECTION_PROFILES)._new.text() == "Новый профиль"
    assert window.page(SECTION_SETTINGS)._header.title.text() == "Настройки"
    assert Preferences(gui_container.settings).get_language() == "ru"
    window.show_section(SECTION_TRASH)  # ...and one built *after* it
    assert window.page(SECTION_TRASH)._title.text() == "Корзина"
    assert window.page(SECTION_SETTINGS)._tabs.button("logs").text() == "Журнал"
    window.set_language("en")
    assert window._sidebar._buttons[SECTION_PROFILES].text() == "Profiles"


def test_sidebar_shows_the_chrome_version_and_a_running_badge(window, gui_container):
    assert spin_wait(lambda: window._sidebar._browser_text.text().startswith("Chrome"))
    make_profile(gui_container)
    page = settle(window, 1)
    page._start(page._model.rows()[0])
    assert spin_wait(lambda: window._sidebar._buttons[SECTION_PROFILES]._running == 1)
    gui_container.profiles.stop_profile(1)


def test_closing_with_running_profiles_asks_and_can_be_cancelled(window, gui_container, monkeypatch):
    make_profile(gui_container)
    page = settle(window, 1)
    page._start(page._model.rows()[0])
    assert spin_wait(lambda: gui_container.profiles.list_profiles()[0].status.value == "RUNNING")

    asked = {}

    def cancel(dialog):
        asked["text"] = " ".join(label.text() for label in dialog.findChildren(QLabel))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ConfirmDialog, "exec", cancel)
    window.close()
    assert "stopped first" in asked["text"] and window.isVisible()
    gui_container.profiles.stop_profile(1)


def test_opening_a_page_does_not_leave_the_cursor_in_its_search_box(window):
    from PySide6.QtWidgets import QApplication, QLineEdit

    for key in ("proxies", "activity", "profiles", "proxies"):
        window.show_section(key)
        focus = QApplication.focusWidget()
        assert not isinstance(focus, QLineEdit), f"{key}: the search box grabbed the focus"
