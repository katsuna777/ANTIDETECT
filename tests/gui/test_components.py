"""Reusable widgets: segmented control, tabs, switch, select, callout, empty state, dialogs."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from antidetect.gui.components import (
    Callout,
    ConfirmDialog,
    EmptyState,
    Segmented,
    Select,
    StyledMenu,
    Switch,
    TabView,
    confirm,
)
from antidetect.gui.components.avatar import initial, tint_for
from antidetect.gui.components.basics import PageHeader, button

pytestmark = pytest.mark.usefixtures("qapp")


def test_segmented_is_exclusive_keyed_and_only_emits_on_user_changes():
    seg = Segmented([("a", "A"), ("b", "B"), ("c", "C")], "b")
    seen = []
    seg.changed.connect(seen.append)
    assert seg.value() == "b" and seg.button("b").isChecked()
    seg.set_value("c")
    assert seg.value() == "c" and seg.button("c").isChecked() and not seg.button("b").isChecked() and seen == []
    seg.button("a").click()
    seg.button("a").click()  # clicking the active segment again is not a change
    assert seen == ["a"] and seg.value() == "a"
    seg.set_text("a", "Alpha")
    assert seg.button("a").text() == "Alpha"
    seg.set_value("zzz")  # unknown keys are ignored
    assert seg.value() == "a"


def test_tab_view_switches_pages():
    from PySide6.QtWidgets import QLabel

    tabs = TabView()
    first, second = QLabel("1"), QLabel("2")
    tabs.add_tab("one", "One", first)
    tabs.add_tab("two", "Two", second)
    changed = []
    tabs.currentChanged.connect(changed.append)
    assert tabs.current() == "one" and tabs.stack.currentWidget() is first
    tabs.bar.button("two").click()
    assert tabs.stack.currentWidget() is second and changed == ["two"]
    tabs.set_current("one")
    assert tabs.stack.currentWidget() is first


def test_switch_toggles_by_click_and_keyboard_state():
    switch = Switch(False)
    states = []
    switch.toggled.connect(states.append)
    switch.show()
    switch.click()
    switch.click()
    assert states == [True, False] and not switch.isChecked()
    switch.setChecked(True)
    assert switch.isChecked() and switch.sizeHint().width() > switch.sizeHint().height()


def test_select_picks_by_data_and_ignores_the_wheel():
    select = Select()
    select.addItem("A", 1)
    select.addItem("B", 2)
    assert select.select_data(2) and select.currentText() == "B"
    assert not select.select_data(99) and select.currentText() == "B"


def test_callout_changes_tone_and_hides_a_missing_action():
    callout = Callout("accent", "info")
    callout.set_content("hello")
    callout.show()
    assert not callout._button.isVisible() and callout._text.text() == "hello"
    callout.set_content("hello", "Do it")
    assert callout._button.isVisible()
    callout.set_tone("warning", "alert")
    assert callout.property("tone") == "warning"
    fired = []
    callout.activated.connect(lambda: fired.append(1))
    callout._button.click()
    assert fired == [1]


def test_callout_title_is_optional_and_prominent_is_opt_in():
    callout = Callout("warning", "alert", prominent=True)
    callout.set_content("body")
    callout.show()
    assert not callout._title.isVisible() and callout.property("prominent") is True
    callout.set_content("body", title="Head")
    assert callout._title.isVisible() and callout._title.text() == "Head" and callout._text.text() == "body"
    assert Callout("accent", "info").property("prominent") is None


def test_free_proxy_notice_is_a_yellow_warning_in_both_languages():
    from antidetect.gui.components import FreeProxyNotice
    from antidetect.i18n import set_language

    notice = FreeProxyNotice()
    notice.show()
    assert notice.property("tone") == "warning" and notice.property("prominent") is True
    assert "testing only" in notice._title.text() and "captchas" in notice._text.text()
    set_language("ru")
    notice.retranslate()
    assert "только для тестов" in notice._title.text() and "капчу" in notice._text.text()


def test_empty_state_hides_what_it_was_not_given():
    state = EmptyState("user")
    state.show()
    state.set_content("Title")
    assert not state.action.isVisible() and not state.text.isVisible() and not state.steps.isVisible()
    state.set_content("Title", "text", "Go", ["1  a", "2  b"])
    assert state.action.isVisible() and state.text.isVisible() and state.steps.isVisible()
    assert [row.isVisible() for row in state._step_labels] == [True, True, False]


def test_confirm_dialog_returns_the_users_answer(monkeypatch):
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    assert confirm(None, "Title", "Text", "Delete", danger=True) is True
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert confirm(None, "Title", "Text", "Delete") is False
    dialog = ConfirmDialog(None, "Title", "Text", "Delete", danger=True)
    assert dialog.confirm_button.property("variant") == "danger-solid"


def test_styled_menu_items_run_their_callbacks_and_can_be_disabled():
    menu = StyledMenu()
    hits = []
    action = menu.item("Run", lambda: hits.append(1), icon="play")
    menu.item("Nope", enabled=False)
    sub = menu.submenu("More", "folder")
    sub.item("Inner", lambda: hits.append(2))
    action.trigger()
    sub.actions()[0].trigger()
    assert hits == [1, 2]
    assert [a.isEnabled() for a in menu.actions() if a.text() in ("Run", "Nope")] == [True, False]


def test_avatars_are_stable_per_name_and_have_an_initial():
    assert tint_for("Shop", False) == tint_for("shop", False)
    assert tint_for("Shop", True) != tint_for("Shop", False)
    assert initial("  ?!x") == "X" and initial("") == "?" and initial("Ярослав") == "Я"


def test_page_header_and_button_helpers():
    header = PageHeader("T", "S")
    header.set_texts("T2")
    assert header.title.text() == "T2" and header.subtitle.isHidden()
    btn = button("Go", "primary", icon="plus", size="sm")
    assert btn.property("variant") == "primary" and btn.property("compact") is True and not btn.icon().isNull()
    btn.set_icon_name(None)
    assert btn.icon().isNull()
