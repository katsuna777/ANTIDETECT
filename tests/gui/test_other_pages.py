"""Settings and Check pages, toasts."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from antidetect.gui.components import ToastHost
from antidetect.gui.preferences import Preferences
from antidetect.gui.sidebar import SECTION_SETTINGS
from tests.support.gui import check_page, make_profile, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def test_toasts_stack_and_dismiss(qapp):
    host_widget = QWidget()
    host_widget.resize(600, 400)
    host_widget.show()
    toasts = ToastHost(host_widget)
    toasts.show_message("one", timeout_ms=0)
    toasts.show_message("two", kind="error", action=("Details", lambda: None), timeout_ms=0)
    assert toasts.count() == 2
    for index in range(6):
        toasts.show_message(f"t{index}", timeout_ms=0)
    assert toasts.count() == ToastHost.MAX_VISIBLE
    host_widget.close()


def test_settings_page_shows_browser_and_toggles_confirm(window, gui_container, fake_chromium):
    window.show_section(SECTION_SETTINGS)
    page = window.page(SECTION_SETTINGS)
    assert spin_wait(lambda: str(fake_chromium) in page._r_browser.description.text())
    assert "Version 152" in page._r_browser.description.text()
    page._confirm.setChecked(False)
    assert Preferences(gui_container.settings).get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, True) is False
    page._auto_browser()
    assert gui_container.browser._chromium_path is None


def test_settings_theme_and_language_controls_emit_and_stay_in_sync(window):
    window.show_section(SECTION_SETTINGS)
    page = window.page(SECTION_SETTINGS)
    got = []
    page.themeChanged.connect(got.append)
    page._theme.button("dark").click()
    assert got == ["dark"] and window.current_theme() == "dark"
    window.toggle_theme()  # the sidebar switch moves the segmented control too
    assert page._theme.value() == "light"
    page._lang.button("ru").click()
    assert page._header.title.text() == "Настройки"
    page._lang.button("en").click()


def test_missing_browser_is_called_out_in_settings(window, gui_container):
    window.show_section(SECTION_SETTINGS)
    page = window.page(SECTION_SETTINGS)
    page.show_browser((None, None))
    assert page._r_browser.description.text() == "Not found"
    assert page._r_browser.description.property("role") == "danger"


def test_check_page_lists_profiles_and_opens_a_site_in_the_chosen_one(window, gui_container):
    page = check_page(window)
    assert spin_wait(lambda: page._stack.currentWidget() is page._empty)
    assert page._empty.title.text() == "Create a profile first"
    make_profile(gui_container, "Zed")
    make_profile(gui_container, "Alpha")
    page.reload()
    assert spin_wait(lambda: page._profiles.count() == 2)
    assert [page._profiles.itemText(i) for i in range(2)] == ["Alpha", "Zed"]  # sorted by name
    assert page._stack.currentWidget() is page._content
    assert [c.key for c in page._cards] == ["creepjs", "pixelscan", "iphey", "browserleaks", "sannysoft"]
    changed = []
    page.profilesChanged.connect(lambda: changed.append(1))
    page._profiles.select_data(page.selected_row().id)
    chosen = page.selected_row()
    page._cards[0].button.click()
    assert spin_wait(lambda: gui_container.profiles.get_profile(chosen.id).status.value == "RUNNING")
    assert spin_wait(lambda: bool(changed))
    gui_container.profiles.stop_profile(chosen.id)


def test_check_page_warns_when_the_chosen_profile_runs_on_a_free_proxy(window, gui_container):
    from antidetect.domain.enums.proxy_status import ProxyProtocol
    from antidetect.domain.models.proxy_entry import ProxyEntry
    from antidetect.gui.workers import tasks

    gui_container.proxies._proxies.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host="203.0.113.60", port=80, source="free-list")]
    )
    free_id = tasks.list_proxies(gui_container).rows[0].id
    make_profile(gui_container, "Alpha")
    make_profile(gui_container, "Free", proxy_id=free_id)
    make_profile(gui_container, "Own", proxy_text="10.0.0.9:80")
    page = check_page(window)
    page.reload()
    assert spin_wait(lambda: page._profiles.count() == 3)
    for name, warned in (("Alpha", False), ("Free", True), ("Own", False)):
        page._profiles.setCurrentIndex(page._profiles.findText(name))
        assert page._free_notice.isVisibleTo(page) is warned, name


def test_check_page_retranslates(window):
    page = check_page(window)
    window.set_language("ru")
    assert page._header.subtitle.text() and page._cards[0].button.text() == "Открыть"
    assert window.page(SECTION_SETTINGS)._tabs.button("check").text() == "Проверка отпечатка"
