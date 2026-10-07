"""Profiles page: table, filters, row actions, bulk actions, menus, polling."""

from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QDialog, QPushButton

from antidetect.gui.components import ConfirmDialog
from antidetect.gui.models.profiles import COL_ACTION, COL_NAME, COL_STATUS
from antidetect.gui.models.roles import ROW_ROLE
from antidetect.gui.preferences import Preferences
from antidetect.gui.views.delegates import PROFILE_ROW_HEIGHT
from antidetect.gui.sidebar import SECTION_PROFILES
from antidetect.gui.components.filter_popover import FilterState
from tests.support.gui import hover, make_profile, settle, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def test_empty_state_then_rows(window, gui_container):
    page = window.page(SECTION_PROFILES)
    assert spin_wait(lambda: page._stack.currentWidget() is page._empty)
    assert page._empty.title.text() == "Create your first profile"
    assert not page._search.isEnabled() and not page._count.isVisibleTo(page)
    make_profile(gui_container)
    page = settle(window, 1)
    assert spin_wait(lambda: page._stack.currentWidget() is page._view)
    assert page._count.text() == "1" and page._search.isEnabled()


def test_search_state_and_tag_filters(window, gui_container):
    make_profile(gui_container, "Shop", tags=["eu"])
    make_profile(gui_container, "Ads", tags=["us"], notes="campaign")
    page = settle(window, 2)
    page._search.setText("camp")
    assert page._filter.rowCount() == 1 and page._count.text() == "1 / 2"
    page._search.setText("zzz")
    assert page._filter.rowCount() == 0 and page._stack.currentWidget() is page._empty
    assert page._empty.title.text() == "No profiles match your search"
    page._search.setText("")
    assert page._stack.currentWidget() is page._view
    page.set_tag("eu")
    assert page._filter.rowCount() == 1 and page._tag_pill.isVisibleTo(page)
    page.set_tag(None)
    assert not page._tag_pill.isVisibleTo(page) and page._filter.rowCount() == 2
    page._on_filter_popover(FilterState(state="running"))
    assert page._filter.rowCount() == 0 and page._filter_button.property("active")
    page._on_filter_popover(FilterState(state="stopped"))
    assert page._filter.rowCount() == 2
    page._on_filter_popover(FilterState(platforms=frozenset({"linux"})))
    assert page._filter.rowCount() == 0
    page._on_filter_popover(FilterState(proxy="without"))
    assert page._filter.rowCount() == 2
    page._on_filter_popover(FilterState(cookies="with"))                  # nobody has run yet: no cookies anywhere
    assert page._filter.rowCount() == 0
    page._on_filter_popover(FilterState(cookies="without", created="today"))
    assert page._filter.rowCount() == 2 and page._model.active_filters() == 2
    page._on_filter_popover(FilterState())
    assert page._filter.rowCount() == 2 and not page._filter_button.property("active")


def test_tag_counts_reach_the_sidebar_and_a_tag_click_narrows_the_list(window, gui_container):
    make_profile(gui_container, "Shop", tags=["eu", "shop"])
    make_profile(gui_container, "Ads", tags=["eu"])
    page = settle(window, 2)
    assert spin_wait(lambda: set(window._sidebar._tag_rows) == {"eu", "shop"} and window._sidebar._tag_rows["eu"].count == 2)
    assert window._sidebar._tag_rows["eu"].count == 2
    window._sidebar._tag_rows["shop"].click()
    assert spin_wait(lambda: page.tag() == "shop") and page._filter.rowCount() == 1
    assert window._sidebar._tag_rows["shop"].isChecked()
    window._sidebar._buttons[SECTION_PROFILES].click()        # "Profiles" always means all of them
    assert page.tag() is None and page._filter.rowCount() == 2
    assert not window._sidebar._tag_rows["shop"].isChecked()


def test_sorting_survives_a_reload_and_is_remembered(window, gui_container):
    from antidetect.gui.models.profiles import COL_NAME

    make_profile(gui_container, "Bravo")
    make_profile(gui_container, "alpha")
    page = settle(window, 2)
    assert [r.name for r in page._model.visible_rows()] == ["alpha", "Bravo"]        # case-insensitive
    page._sort_by(COL_NAME, Qt.SortOrder.DescendingOrder)
    assert [r.name for r in page._model.visible_rows()] == ["Bravo", "alpha"]
    page.reload()
    spin_wait(lambda: False, 300)
    assert [r.name for r in page._model.visible_rows()] == ["Bravo", "alpha"]
    assert Preferences(gui_container.settings).get_sort(Preferences.KEY_PROFILES_SORT, (0, False)) == (COL_NAME, True)


def test_start_and_stop_from_the_row_button(window, gui_container):
    make_profile(gui_container)
    page = settle(window, 1)
    row = page._model.rows()[0]
    page._start(row)
    assert page._model.busy(row.id) == "starting"
    assert spin_wait(lambda: page._model.rows() and page._model.rows()[0].running)
    assert spin_wait(lambda: page._model.busy(row.id) is None)
    assert page._model.rows()[0].last_started_at is not None
    page._stop(page._model.rows()[0])
    assert spin_wait(lambda: not page._model.rows()[0].running)
    assert page._model.rows()[0].last_started_at is not None  # still remembered after stopping


def test_clicking_the_action_cell_button_starts_the_profile(window, gui_container):
    make_profile(gui_container)
    page = settle(window, 1)
    index = page._filter.index(0, COL_ACTION)
    page._delegate.actionClicked.emit(index)
    assert spin_wait(lambda: page._model.rows()[0].running)
    gui_container.profiles.stop_profile(1)


def test_start_failure_shows_an_error_toast_and_the_browser_banner(window, gui_container, monkeypatch):
    from antidetect.domain.errors import ChromiumNotFoundError
    from antidetect.infrastructure.chromium import chromium_manager

    def nothing_installed():
        raise ChromiumNotFoundError()

    assert spin_wait(lambda: window._sidebar._browser_text.text().startswith("Chrome"))  # start-up refresh done
    monkeypatch.setattr(chromium_manager, "discover_chromium", nothing_installed)
    gui_container.browser.set_chromium_path(None)
    make_profile(gui_container)
    page = settle(window, 1)
    page._start(page._model.rows()[0])
    assert spin_wait(lambda: window.toasts.count() >= 1)
    assert spin_wait(lambda: page._model.busy(1) is None)
    assert page._banner.isVisibleTo(page)


def test_missing_browser_shows_the_banner_and_the_sidebar_warning(window, gui_container):
    gui_container.browser.set_chromium_path(None)
    gui_container.browser.resolved_binary = lambda: None  # type: ignore[assignment]
    window.refresh_browser()
    page = window.page(SECTION_PROFILES)
    assert spin_wait(lambda: page._banner.isVisibleTo(page))
    assert window._sidebar._browser_text.text() == "Chrome not found"


def test_context_menus_for_single_running_and_many(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    rows = page._model.rows()
    single = [a.text() for a in page.build_menu([rows[0]]).actions() if a.text()]
    assert single[0] == "Start" and "Edit…" in single and "Move to trash" in single
    assert "Move to workspace" in single and "Duplicate" in single and "Cookies" in single
    assert "Open profile folder" in single
    assert "Details" not in single and "Tags…" not in single      # a click on the row opens the drawer; tags live there
    assert any("Check fingerprint" in t for t in single)
    running = page.build_menu([dataclasses.replace(rows[0], running=True)])
    assert [a.text() for a in running.actions() if a.text()][:2] == ["Stop", "Restart"]
    many = [a.text() for a in page.build_menu(rows).actions() if a.text()]
    assert many[0] == "2 selected" and "Move to trash" in many and "Edit…" not in many and "Tags…" in many
    check = next(a for a in page.build_menu([rows[0]]).actions() if a.menu() and "fingerprint" in a.text())
    assert len(check.menu().actions()) == 5


def test_bulk_bar_appears_with_a_multi_selection(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    assert not page._bulk.isVisibleTo(page)
    page._view.selectAll()
    assert page._bulk.isVisibleTo(page) and len(page.selected_rows()) == 2
    assert page._bulk._count.text() == "2 selected"
    page._view.clearSelection()
    assert not page._bulk.isVisibleTo(page)


def test_delete_moves_to_the_trash_without_asking_and_offers_undo(window, gui_container):
    make_profile(gui_container, "Keep")
    page = settle(window, 1)
    page.trash_profiles(page._model.rows())
    assert spin_wait(lambda: not gui_container.profiles.list_profiles())
    assert [p.name for p in gui_container.profiles.list_trashed_profiles()] == ["Keep"]     # nothing was lost
    assert spin_wait(lambda: window._catalog.trash == 1 and window._sidebar._buttons["trash"]._count == "1")
    toast = window.toasts._toasts[-1]
    undo = next(b for b in toast.findChildren(QPushButton) if b.text() == "Undo")
    undo.click()
    assert spin_wait(lambda: [p.name for p in gui_container.profiles.list_profiles()] == ["Keep"])
    assert spin_wait(lambda: window._catalog.trash == 0)


def test_the_delete_key_and_the_menu_trash_too(window, gui_container):
    make_profile(gui_container, "A")
    make_profile(gui_container, "B")
    page = settle(window, 2)
    menu = page.build_menu(page._model.rows())
    assert "Move to trash" in [a.text() for a in menu.actions()]
    page.trash_profiles(page._model.rows()[:1])
    assert spin_wait(lambda: len(gui_container.profiles.list_profiles()) == 1)


def test_clicking_a_row_opens_its_drawer_and_clicking_again_closes_it(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    expander = page._expander
    assert not expander.is_open()
    _click(page, 0, "body")
    assert expander.is_open() and page._drawer.row().name == "One"
    assert spin_wait(lambda: page._view.rowHeight(0) > PROFILE_ROW_HEIGHT, 3000)
    assert spin_wait(lambda: page._view.rowHeight(0) == PROFILE_ROW_HEIGHT + page._drawer.height(), 3000)
    assert page._view.rowHeight(1) == PROFILE_ROW_HEIGHT                       # the others keep their size
    _click(page, 0, "body")
    assert not expander.is_open()
    assert spin_wait(lambda: page._view.rowHeight(0) == PROFILE_ROW_HEIGHT, 3000)


def test_opening_another_row_closes_the_first_and_buttons_do_not_open_a_drawer(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    _click(page, 0, "body")
    assert spin_wait(lambda: page._view.rowHeight(0) > PROFILE_ROW_HEIGHT, 3000)
    _click(page, 1, "body")
    assert page._expander.key == page._model.row_at(1).id
    assert spin_wait(lambda: page._view.rowHeight(0) == PROFILE_ROW_HEIGHT and page._view.rowHeight(1) > PROFILE_ROW_HEIGHT, 3000)
    page._expander.close(animated=False)
    cell = page._view.visualRect(page._filter.index(0, COL_ACTION))
    from PySide6.QtTest import QTest

    QTest.mouseClick(page._view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     page._delegate.play_rect(cell).center())            # the Start button: starts, does not open
    assert not page._expander.is_open()
    assert spin_wait(lambda: any(r.running for r in page._model.rows()))
    for p in gui_container.profiles.list_profiles():
        if p.status.value == "RUNNING":
            gui_container.profiles.stop_profile(p.id)


def test_the_drawer_follows_its_row_through_sorting_and_closes_when_the_row_goes(window, gui_container):
    from antidetect.gui.models.profiles import COL_NAME

    make_profile(gui_container, "Alpha")
    make_profile(gui_container, "Bravo")
    page = settle(window, 2)
    page.open_drawer(page._model.rows()[0].id)
    page._expander._finish_now()
    key = page._expander.key
    page._sort_by(COL_NAME, Qt.SortOrder.DescendingOrder)
    position = page._model.position_of(key)
    assert page._view.rowHeight(position) > PROFILE_ROW_HEIGHT
    assert all(page._view.rowHeight(r) == PROFILE_ROW_HEIGHT for r in range(2) if r != position)
    page.trash_profiles([next(r for r in page._model.rows() if r.id == key)])
    assert spin_wait(lambda: not page._expander.is_open())
    assert spin_wait(lambda: all(page._view.rowHeight(r) == PROFILE_ROW_HEIGHT for r in range(page._model.rowCount())))


def test_editing_in_the_drawer_saves_name_notes_tags_and_workspace(window, gui_container):
    ws = gui_container.workspaces.create_workspace("Clients")
    gui_container.tags.create_tag("vip")
    make_profile(gui_container, "Old name")
    page = settle(window, 1)
    page.open_drawer(page._model.rows()[0].id)
    drawer = page._drawer
    assert not drawer._save.isEnabled() and not drawer.is_dirty()
    drawer._name.setText("New name")
    drawer._notes.setPlainText("hello")
    drawer._tags.set_tags(["vip"]); drawer._tags.changed.emit()
    drawer._workspace.setCurrentIndex(drawer._workspace.findData(ws.id))
    assert drawer.is_dirty() and drawer._save.isEnabled() and drawer._revert.isVisibleTo(drawer)
    drawer._save.click()
    assert spin_wait(lambda: gui_container.profiles.list_profiles()[0].name == "New name")
    profile = gui_container.profiles.list_profiles()[0]
    assert (profile.notes, profile.tags, profile.workspace_id) == ("hello", ["vip"], ws.id)
    assert spin_wait(lambda: not drawer.is_dirty())                   # the fresh row is the new baseline


def test_the_drawer_rejects_a_taken_or_empty_name_and_keeps_typing_across_a_refresh(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    page.open_drawer(page._model.rows()[0].id)
    drawer = page._drawer
    drawer._name.setText("two")                                        # a name that is taken (case-insensitive)
    assert not drawer._save.isEnabled() and drawer._name.property("invalid") is True
    drawer._name.setText("")
    assert not drawer._save.isEnabled()
    drawer._name.setText("Three")
    assert drawer._save.isEnabled()
    page.reload()                                                      # the table refreshes behind the user's back
    spin_wait(lambda: False, 300)
    assert drawer._name.text() == "Three" and drawer.is_dirty()        # what was typed is not overwritten
    drawer._revert.click()
    assert drawer._name.text() == "One" and not drawer.is_dirty()


def test_escape_in_the_drawer_closes_it_and_return_in_a_field_does_not_start_anything(window, gui_container):
    from PySide6.QtTest import QTest

    make_profile(gui_container, "One")
    page = settle(window, 1)
    page._view.selectionModel().select(page._filter.index(0, 0), page._view.selectionModel().SelectionFlag.Select
                                       | page._view.selectionModel().SelectionFlag.Rows)
    page.open_drawer(page._model.rows()[0].id)
    page._expander._finish_now()
    drawer = page._drawer
    drawer._notes.setFocus()
    QTest.keyClick(drawer._name, Qt.Key.Key_Return)                    # Return belongs to the field, not to "start selected"
    spin_wait(lambda: False, 200)
    assert not any(r.running for r in page._model.rows())
    drawer._tags.setFocus()
    QTest.keyClick(drawer._tags, Qt.Key.Key_Escape)
    assert not page._expander.is_open()


def test_polling_is_idle_while_nothing_runs_and_notices_a_crash(window, gui_container, monkeypatch):
    make_profile(gui_container)
    page = settle(window, 1)
    submitted = []
    real_submit = page._runner.submit
    monkeypatch.setattr(page._runner, "submit", lambda fn, **kw: (submitted.append(fn), real_submit(fn, **kw))[1])
    monkeypatch.setattr(type(window), "isActiveWindow", lambda self: True)
    page._tick()
    assert submitted == []  # every profile is stopped: the database is not touched at all

    page._start(page._model.rows()[0])
    assert spin_wait(lambda: page._model.rows()[0].running and page._model.busy(1) is None)
    submitted.clear()
    page._tick()
    assert len(submitted) == 1  # something runs: one cheap "who is running" query
    # The browser dies behind our back: the poll notices and reloads the table.
    gui_container.browser._processes.clear()
    import os, signal

    pid = gui_container.profiles.list_profiles()[0].pid
    os.kill(pid, signal.SIGKILL)
    assert spin_wait(lambda: (page._tick(), not page._model.rows()[0].running)[1], timeout_ms=8000)


def test_narrow_tables_hide_the_least_important_columns(window, gui_container):
    from antidetect.gui.models.profiles import COL_COOKIES, COL_CREATED, COL_LAST, COL_PROXY

    make_profile(gui_container)
    page = settle(window, 1)
    page._fit_columns(1300)
    assert not any(page._view.isColumnHidden(c) for c in (COL_CREATED, COL_LAST, COL_COOKIES))
    page._fit_columns(1000)
    assert page._view.isColumnHidden(COL_CREATED) and not page._view.isColumnHidden(COL_LAST)
    page._fit_columns(700)
    assert all(page._view.isColumnHidden(c) for c in (COL_CREATED, COL_LAST, COL_COOKIES))
    assert not page._view.isColumnHidden(COL_PROXY)


def test_a_new_profile_is_on_screen_at_once_and_marked_while_it_is_being_set_up(window, gui_container):
    import threading

    from antidetect.gui.models.specs import ProfileSpec
    from antidetect.gui.sidebar import SECTION_PROFILES

    gate = threading.Event()
    gui_container.profiles._geo_lookup = lambda: (gate.wait(8), "DE")[1]  # the slow, network part
    page = window.page(SECTION_PROFILES)
    page._create(ProfileSpec(name="Slow geo", platform="windows", geo_auto=True), start=False)
    try:
        assert spin_wait(lambda: page._model.rowCount() == 1)           # visible while the lookup still waits
        (row,) = page._model.rows()
        assert page._model.busy(row.id) == "preparing"
        assert page._model.index(0, COL_STATUS).data() == "Setting up…"
        page._apply_rows([])                                            # a stale reload, read before the row existed...
        page._apply_rows([row])                                         # ...must not lose the marker
        assert page._model.busy(row.id) == "preparing"
    finally:
        gate.set()
    assert spin_wait(lambda: page._model.busy(row.id) is None and not page._settling)
    assert spin_wait(lambda: page._model.rows()[0].timezone == "Europe/Berlin")  # the geo landed afterwards


def test_create_and_start_shows_starting_and_ends_running(window, gui_container, fake_chromium):
    from antidetect.gui.models.specs import ProfileSpec
    from antidetect.gui.sidebar import SECTION_PROFILES

    gui_container.browser.set_chromium_path(fake_chromium)
    page = window.page(SECTION_PROFILES)
    page._create(ProfileSpec(name="Go now", platform="windows", geo_auto=False), start=True)
    try:
        assert spin_wait(lambda: page._model.rowCount() == 1 and page._model.rows()[0].running)
        assert spin_wait(lambda: page._model.busy(page._model.rows()[0].id) is None)
    finally:
        for profile in gui_container.profiles.list_profiles():
            gui_container.profiles.stop_profile(profile.id)


# ------------------------------------------------------------- selection: only the checkbox ticks a row

def _click(page, row: int, where: str, modifiers=Qt.KeyboardModifier.NoModifier, button=Qt.MouseButton.LeftButton):
    """A real mouse click on a part of a row: 'avatar' (the checkbox spot), 'body' (the name text), 'proxy'."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    view = page._view
    column = COL_NAME if where in ("avatar", "body") else page._model.columnCount() - 1 if where == "last" else 3
    index = page._filter.index(row, column)
    cell = page._delegate.band(view.visualRect(index), view, index)       # the row without the drawer it may have opened
    if where == "avatar":
        point = page._delegate.avatar_rect(cell).center()
    elif where == "body":
        point = QPoint(cell.left() + 120, cell.center().y())
    else:
        point = QPoint(cell.left() + 4, cell.center().y() - 20)
    hover(view.viewport(), point)
    QTest.mouseClick(view.viewport(), button, modifiers, point)
    page._expander._finish_now()      # a click on a row's body opens its drawer: the next target must not move under us


def test_clicking_a_row_does_not_tick_it(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    _click(page, 0, "body")
    _click(page, 1, "body")
    assert page.selected_rows() == [] and not page._bulk.isVisibleTo(page)
    assert not page._view.selectionModel().hasSelection()


def test_the_checkbox_ticks_and_unticks_just_its_row(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    _click(page, 0, "avatar")
    assert [r.name for r in page.selected_rows()] == ["One"]
    _click(page, 1, "body")                          # a click elsewhere does not move or clear the tick
    assert [r.name for r in page.selected_rows()] == ["One"]
    _click(page, 1, "avatar")
    assert {r.name for r in page.selected_rows()} == {"One", "Two"} and page._bulk.isVisibleTo(page)
    _click(page, 0, "avatar")
    assert [r.name for r in page.selected_rows()] == ["Two"]


def test_ctrl_and_shift_still_select_for_those_who_want_it(window, gui_container):
    for name in ("A", "B", "C"):
        make_profile(gui_container, name)
    page = settle(window, 3)
    _click(page, 0, "body", Qt.KeyboardModifier.ControlModifier)
    _click(page, 2, "body", Qt.KeyboardModifier.ControlModifier)
    assert {r.name for r in page.selected_rows()} == {"A", "C"}


def test_plain_arrow_keys_do_not_tick_rows(window, gui_container):
    from PySide6.QtTest import QTest

    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    page._view.setFocus()
    page._view.setCurrentIndex(page._filter.index(0, COL_NAME))
    QTest.keyClick(page._view, Qt.Key.Key_Down)
    assert page.selected_rows() == []
    QTest.keyClick(page._view, Qt.Key.Key_Space)      # space ticks the current row, like a checkbox
    assert len(page.selected_rows()) == 1


def test_a_menu_acts_on_the_clicked_row_without_ticking_it(window, gui_container):
    make_profile(gui_container, "One")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    clicked = page._filter.index(1, COL_NAME)
    rows = page._menu_rows(clicked)
    assert [r.name for r in rows] == [clicked.data(ROW_ROLE).name] and page.selected_rows() == []
    page._view.selectionModel().select(clicked, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    page._view.selectionModel().select(page._filter.index(0, COL_NAME), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert len(page._menu_rows(clicked)) == 2         # on a ticked row the menu acts on every ticked row


def test_the_header_chips_share_one_height_and_the_scope_name_gives_way(window, gui_container):
    """The counter, the workspace and the tag in the header are all COMPACT_HEIGHT tall; a long name is cut with an
    ellipsis (and shown whole in the tooltip) instead of being clipped."""
    from antidetect.gui.metrics import COMPACT_HEIGHT
    from antidetect.gui.models.rows import NO_WORKSPACE

    make_profile(gui_container, "One")
    page = settle(window, 1)
    page.set_workspace(NO_WORKSPACE)
    page.set_tag("a-very-long-tag-name@example.com")
    for chip in (page._count, page._workspace_pill, page._tag_pill):
        assert chip.height() == COMPACT_HEIGHT == chip.minimumHeight() == chip.maximumHeight()
    pill = page._tag_pill
    assert pill.minimumSizeHint().width() < pill.sizeHint().width()
    assert pill.toolTip() == "a-very-long-tag-name@example.com"
    assert page._new.sizePolicy().horizontalPolicy().name == "Fixed"           # the main button is never squeezed


def test_the_filter_button_stays_an_icon_in_a_narrow_window(window, gui_container):
    make_profile(gui_container, "One")
    page = settle(window, 1)
    window.resize(1040, 700)
    spin_wait(lambda: False, 150)
    assert page._compact() and page._filter_button.text() == "" and page._sort_button.text() == ""
    page._update_counts()                                                      # used to put the caption back
    assert page._filter_button.text() == ""
    window.resize(1360, 760)
    spin_wait(lambda: False, 150)
    assert page._filter_button.text() == "Filter"


def test_the_menu_marks_the_dangerous_item_and_the_main_one(window, gui_container):
    make_profile(gui_container, "One")
    page = settle(window, 1)
    menu = page.build_menu([page._model.rows()[0]])
    assert menu.defaultAction() is not None and menu.defaultAction().text() == "Move to trash"
    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts[-1] == "Move to trash"
