"""The Trash page, the Activity page and the Settings tabs that now hold the fingerprint check and the log."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from antidetect import i18n
from antidetect.domain.models.activity_entry import ActivityEntry
from antidetect.gui.components import ConfirmDialog, StyledMenu
from antidetect.gui.models.activity import ActivityModel, day_label, describe, style_of
from antidetect.gui.models.trash import COL_LEFT, COL_NAME, TrashModel, days_left
from antidetect.gui.preferences import Preferences
from antidetect.gui.sidebar import SECTION_ACTIVITY, SECTION_PROFILES, SECTION_SETTINGS, SECTION_TRASH
from tests.support.gui import check_page, logs_page, make_profile, settle, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def _trash(window, gui_container, *names):
    for name in names:
        make_profile(gui_container, name)
    for profile in gui_container.profiles.list_profiles():
        if profile.name in names:
            gui_container.profiles.trash_profile(profile.id)
    window.show_section(SECTION_TRASH)
    page = window.page(SECTION_TRASH)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == len(names))
    return page


# ----------------------------------------------------------------------------------- trash


def test_the_empty_trash_explains_itself_and_the_sidebar_counts_what_is_in_it(window, gui_container):
    window.show_section(SECTION_TRASH)
    page = window.page(SECTION_TRASH)
    assert spin_wait(lambda: page._stack.currentWidget() is page._empty)
    assert page._empty.title.text() == "The trash is empty" and "30 days" in page._empty.text.text()
    assert not page._empty_button.isEnabled()
    page = _trash(window, gui_container, "Doomed", "Gone")
    assert page._stack.currentWidget() is page._view and page._count.text() == "2"
    assert spin_wait(lambda: window._sidebar._buttons[SECTION_TRASH]._count == "2")
    assert page._empty_button.isEnabled()


def test_restoring_from_the_trash_brings_the_profile_back(window, gui_container):
    page = _trash(window, gui_container, "Back")
    page.restore(page._model.rows())
    assert spin_wait(lambda: [p.name for p in gui_container.profiles.list_profiles()] == ["Back"])
    assert spin_wait(lambda: page._model.rowCount() == 0 and window._catalog.trash == 0)
    profiles = window.page(SECTION_PROFILES)
    window.show_section(SECTION_PROFILES)
    assert spin_wait(lambda: profiles._model.rowCount() == 1)                     # the list followed too


def test_deleting_for_good_asks_unless_the_preference_is_off(window, gui_container, monkeypatch):
    page = _trash(window, gui_container, "Keep", "Burn")
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    page.purge(page._model.rows())
    spin_wait(lambda: False, 200)
    assert len(gui_container.profiles.list_trashed_profiles()) == 2
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    burn = next(r for r in page._model.rows() if r.name == "Burn")
    page.purge([burn])
    assert spin_wait(lambda: [p.name for p in gui_container.profiles.list_trashed_profiles()] == ["Keep"])
    assert spin_wait(lambda: page._model.rowCount() == 1)
    Preferences(gui_container.settings).set_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, False)
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: pytest.fail("no question expected"))
    page.purge(page._model.rows())
    assert spin_wait(lambda: not gui_container.profiles.list_trashed_profiles())


def test_emptying_the_trash(window, gui_container, monkeypatch):
    page = _trash(window, gui_container, "A", "B", "C")
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    page.empty_trash()
    spin_wait(lambda: False, 150)
    assert len(gui_container.profiles.list_trashed_profiles()) == 3
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    page.empty_trash()
    assert spin_wait(lambda: not gui_container.profiles.list_trashed_profiles())
    assert spin_wait(lambda: page._stack.currentWidget() is page._empty)


def test_the_row_buttons_and_the_menu_restore_and_delete(window, gui_container, monkeypatch):
    page = _trash(window, gui_container, "One", "Two")
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    page._delegate.restoreClicked.emit(page._model.index(0, COL_NAME))
    assert spin_wait(lambda: len(gui_container.profiles.list_profiles()) == 1 and page._model.rowCount() == 1)
    page._delegate.purgeClicked.emit(page._model.index(0, COL_NAME))
    assert spin_wait(lambda: not gui_container.profiles.list_trashed_profiles())


def test_trash_search_and_bulk_bar(window, gui_container):
    page = _trash(window, gui_container, "Apple", "Banana")
    page._search.setText("ban")
    assert [r.name for r in page._model.visible_rows()] == ["Banana"]
    page._search.setText("zzz")
    assert page._stack.currentWidget() is page._empty
    page._search.setText("")
    assert not page._bulk.isVisibleTo(page)
    page._view.selectAll()
    assert page._bulk.isVisibleTo(page) and page._bulk._count.text() == "2 selected"
    page._view.clearSelection()
    assert not page._bulk.isVisibleTo(page)


def test_trash_context_menu(window, gui_container, monkeypatch):
    page = _trash(window, gui_container, "One")
    shown = []
    monkeypatch.setattr(StyledMenu, "exec", lambda self, pos=None: shown.append([a.text() for a in self.actions() if a.text()]))
    cell = page._view.visualRect(page._model.index(0, COL_NAME))
    page._context_menu(cell.center())
    assert shown == [["Restore", "Delete for good"]]


def test_the_retention_is_chosen_on_the_page_and_remembered(window, gui_container):
    page = _trash(window, gui_container, "One")
    assert spin_wait(lambda: page._keep.currentData() == 30)
    page._keep.setCurrentIndex(page._keep.findData(7))
    assert spin_wait(lambda: gui_container.profiles.trash_retention_days() == 7 and page._model.retention_days == 7)
    page._keep.setCurrentIndex(page._keep.findData(0))
    assert spin_wait(lambda: gui_container.profiles.trash_retention_days() == 0 and page._model.retention_days == 0)
    assert page._model.index(0, COL_LEFT).data() == "Kept"


def test_days_left_counts_down_and_stops_when_retention_is_off(window, gui_container):
    page = _trash(window, gui_container, "One")
    row = page._model.rows()[0]
    now = row.deleted_at + timedelta(days=12)
    assert days_left(row, 30, now) == 18 and days_left(row, 10, now) == 0 and days_left(row, 0, now) is None
    model = TrashModel()
    model.set_rows([row])
    assert model.index(0, COL_LEFT).data() == "30 d" and model.sort_key(row, COL_NAME) == "one"


def test_the_trash_page_retranslates(window, gui_container):
    page = _trash(window, gui_container, "One")
    window.set_language("ru")
    assert page._title.text() == "Корзина" and page._empty_button.text() == "Очистить корзину"
    assert window._sidebar._buttons[SECTION_TRASH].text() == "Корзина"


def test_expired_profiles_are_removed_at_start(gui_container):
    from antidetect.gui.main_window import MainWindow

    profile = gui_container.profiles.create_profile("Old", geo_auto=False)
    gui_container.profiles.trash_profile(profile.id)
    when = (datetime.now(timezone.utc) - timedelta(days=45)).replace(tzinfo=None).isoformat(timespec="microseconds")
    gui_container.db.execute("UPDATE profiles SET deleted_at = ? WHERE id = ?", (when, profile.id))
    gui_container.db.commit()
    window = MainWindow(gui_container)
    window.show()
    window._housekeeping()
    assert spin_wait(lambda: not gui_container.profiles.list_trashed_profiles())
    window.close()


# --------------------------------------------------------------------------------- activity

KINDS = {
    "act.profile.created": {}, "act.profile.updated": {"fields": ["notes", "tags"]},
    "act.profile.started": {}, "act.profile.stopped": {}, "act.profile.start_failed": {"error": "boom"},
    "act.profile.trashed": {}, "act.profile.restored": {}, "act.profile.purged": {},
    "act.profile.duplicated": {"source": "Orig"}, "act.profile.tagged": {"count": 2, "added": ["a"], "removed": ["b"]},
    "act.profile.moved": {"count": 3, "names": ["x", "y"]}, "act.tag.created": {}, "act.tag.renamed": {"old": "o"},
    "act.tag.deleted": {"profiles": 2}, "act.workspace.created": {}, "act.workspace.renamed": {"old": "o"},
    "act.workspace.deleted": {"profiles": 1}, "act.proxy.imported": {"added": 2, "existing": 1, "invalid": 1},
    "act.proxy.checked": {"checked": 9, "working": 4}, "act.proxy.refreshed": {"added": 3, "working": 2},
    "act.proxy.deleted": {"count": 4}, "act.trash.emptied": {"count": 5}, "act.trash.expired": {"count": 2, "days": 30},
}


@pytest.mark.parametrize("language", ["en", "ru"])
def test_every_kind_reads_as_a_sentence_in_both_languages(language):
    i18n.set_language(language)
    for kind, data in KINDS.items():
        entry = ActivityEntry(1, datetime.now(timezone.utc), kind, "Name", data)
        title, detail = describe(entry)
        assert title and "{" not in title and title != kind, (kind, title)
        icon, tone = style_of(kind)
        assert icon and tone
    renamed, _ = describe(ActivityEntry(1, datetime.now(timezone.utc), "act.profile.updated", "New", {"fields": ["name"], "old": "Old"}))
    closed, _ = describe(ActivityEntry(1, datetime.now(timezone.utc), "act.profile.stopped", "P", {"closed": True}))
    unmoved, _ = describe(ActivityEntry(1, datetime.now(timezone.utc), "act.profile.moved", "", {"count": 2}))
    assert "Old" in renamed and "New" in renamed and closed != describe(
        ActivityEntry(1, datetime.now(timezone.utc), "act.profile.stopped", "P"))[0] and "2" in unmoved
    assert style_of("act.unknown.thing") == ("activity", "muted")
    assert describe(ActivityEntry(1, datetime.now(timezone.utc), "act.profile.updated", "P", {"fields": ["tags"]}))[1]


def test_the_model_groups_entries_by_day_and_filters_by_text():
    now = datetime.now(timezone.utc)
    entries = [ActivityEntry(3, now, "act.profile.started", "Alpha"), ActivityEntry(2, now, "act.profile.stopped", "Beta"),
               ActivityEntry(1, now - timedelta(days=1, hours=2), "act.profile.created", "Alpha")]
    model = ActivityModel()
    model.set_entries(entries)
    items = [model.index(i).data(Qt.ItemDataRole.UserRole + 1) for i in range(model.rowCount())]
    assert [i.entry is None for i in items] == [True, False, False, True, False]            # header, 2 today, header, 1 older
    assert day_label(items[0].day) == "Today" and day_label(items[3].day) == "Yesterday"
    model.set_text("beta")
    assert model.rowCount() == 2
    model.set_text("")
    model.prepend([ActivityEntry(4, now, "act.profile.trashed", "Alpha"), entries[0]])      # a known entry is not duplicated
    assert model.newest_id() == 4 and len(model.entries()) == 4
    model.append([ActivityEntry(0, now - timedelta(days=9), "act.tag.created", "t")])
    assert model.oldest_id() == 0 and len(model.entries()) == 5


def test_the_activity_page_shows_what_happened_and_follows_new_events(window, gui_container):
    gui_container.activity.record("act.tag.created", "first")
    window.show_section(SECTION_ACTIVITY)
    page = window.page(SECTION_ACTIVITY)
    assert spin_wait(lambda: page._model.entries() and page._stack.currentWidget() is page._list)
    gui_container.activity.record("act.tag.created", "second")
    page._poll()
    assert spin_wait(lambda: {e.subject for e in page._model.entries()} >= {"first", "second"})
    assert page._model.newest_id() == gui_container.activity.latest_id()


def test_activity_filters_search_and_clear(window, gui_container, monkeypatch):
    gui_container.activity.record("act.proxy.deleted", count=1)
    gui_container.activity.record("act.tag.created", "x")
    gui_container.activity.record("act.profile.start_failed", "Bad", level="ERROR", error="e")
    window.show_section(SECTION_ACTIVITY)
    page = window.page(SECTION_ACTIVITY)
    assert spin_wait(lambda: len(page._model.entries()) == 3)
    for key, expected in (("proxies", {"act.proxy.deleted"}), ("organize", {"act.tag.created"}),
                          ("errors", {"act.profile.start_failed"}), ("profiles", {"act.profile.start_failed"})):
        page._segmented.button(key).click()
        assert spin_wait(lambda: {e.kind for e in page._model.entries()} == expected), key
    page._segmented.button("all").click()
    assert spin_wait(lambda: len(page._model.entries()) == 3)
    page._search.setText("zzzz")
    assert page._stack.currentWidget() is page._empty and page._empty.title.text() == "No profiles match your search"
    page._search.setText("")
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    page._clear.click()
    assert spin_wait(lambda: not page._model.entries() and page._stack.currentWidget() is page._empty)
    assert not page._clear.isEnabled() and page._empty.title.text() == "Nothing has happened yet"


def test_older_entries_load_when_scrolled_to_the_end(window, gui_container, monkeypatch):
    from antidetect.gui.pages import activity

    monkeypatch.setattr(activity, "PAGE", 20)
    for i in range(45):
        gui_container.activity.record("act.proxy.deleted", count=i)
    window.show_section(SECTION_ACTIVITY)
    page = window.page(SECTION_ACTIVITY)
    page._load()
    assert spin_wait(lambda: len(page._model.entries()) == 20 and page._more)
    bar = page._list.verticalScrollBar()
    first_end = bar.maximum()
    bar.setValue(first_end)
    # Wait for the page to be fully settled before scrolling again: the loading flag drops a moment after
    # the entries arrive and the bar grows only once the new rows are laid out; a scroll before that is
    # ignored (and setting the same value again would send no signal), which only a slow machine shows.
    assert spin_wait(lambda: len(page._model.entries()) == 40 and not page._loading and bar.maximum() > first_end)
    bar.setValue(bar.maximum())
    assert spin_wait(lambda: len(page._model.entries()) == 45 and not page._more)


def test_the_badge_is_a_quiet_number_and_turns_red_for_a_failure(window, gui_container):
    button = window._sidebar._buttons[SECTION_ACTIVITY]
    gui_container.activity.record("act.tag.created", "t")
    window.catalog.refresh()
    assert spin_wait(lambda: button._count == "1" and button._badge == "")
    gui_container.activity.record("act.profile.start_failed", "P", level="ERROR", error="e")
    window.catalog.refresh()
    assert spin_wait(lambda: button._badge == "1")
    window.show_section(SECTION_ACTIVITY)                              # looking at it reads everything
    assert button._count == "" and button._badge == ""
    assert spin_wait(lambda: window.catalog.unseen == 0)
    window.show_section(SECTION_PROFILES)
    window.catalog.refresh()
    spin_wait(lambda: False, 200)
    assert button._count == "" and button._badge == ""                 # still read after a refresh from the database


def test_real_actions_land_in_the_feed_in_order(window, gui_container):
    make_profile(gui_container, "Feed")
    page = settle(window, 1)
    page.trash_profiles(page._model.rows())
    assert spin_wait(lambda: not gui_container.profiles.list_profiles())
    kinds = [e.kind for e in gui_container.activity.list()]
    assert kinds[0] == "act.profile.trashed" and "act.profile.created" in kinds


def test_the_activity_page_retranslates(window, gui_container):
    window.show_section(SECTION_ACTIVITY)
    page = window.page(SECTION_ACTIVITY)
    window.set_language("ru")
    assert page._header.title.text() == "Активность" and page._segmented.button("errors").text() == "Ошибки"


# ----------------------------------------------------------------------- the settings tabs


def test_settings_has_tabs_and_builds_the_check_and_the_log_only_when_opened(window, gui_container):
    window.show_section(SECTION_SETTINGS)
    settings = window.page(SECTION_SETTINGS)
    assert set(settings._subpages) == {"general"}
    assert [b.text() for b in settings._tabs.buttons().values()] == ["General", "Fingerprint check", "Log"]
    check = check_page(window)
    assert set(settings._subpages) == {"general", "check"} and settings._stack.currentWidget() is check
    assert check._header.top.isHidden()                                  # the tabs are its title
    logs = logs_page(window)
    assert settings._stack.currentWidget() is logs and logs._header.top.isHidden()
    settings.show_tab("general")
    assert settings._stack.currentWidget() is settings._subpages["general"]


def test_the_check_inside_settings_still_opens_a_site_in_a_profile_and_refreshes_the_list(window, gui_container):
    make_profile(gui_container, "Zed")
    check = check_page(window)
    assert spin_wait(lambda: check._profiles.count() == 1)
    reloaded = []
    window.page(SECTION_PROFILES).reload = lambda: reloaded.append(1)
    check._cards[0].button.click()
    assert spin_wait(lambda: gui_container.profiles.list_profiles()[0].status.value == "RUNNING")
    assert spin_wait(lambda: bool(reloaded))
    gui_container.profiles.stop_profile(1)


def test_quick_search_opens_the_check_and_the_log_tabs_of_settings(window, gui_container):
    entries = {e.title: e for e in window.palette_entries() if e.kind == "page"}
    assert "Fingerprint check" in entries and "Log" in entries
    entries["Fingerprint check"].run()
    assert window.current_section() == SECTION_SETTINGS
    assert window.page(SECTION_SETTINGS)._stack.currentWidget() is window.page(SECTION_SETTINGS)._subpages["check"]
    entries["Log"].run()
    assert window.page(SECTION_SETTINGS)._stack.currentWidget() is window.page(SECTION_SETTINGS)._subpages["logs"]
    assert window.page(SECTION_SETTINGS)._tabs.value() == "logs"
