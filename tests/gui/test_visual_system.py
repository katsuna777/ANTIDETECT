"""Flags, icons, tag colours, popovers, quick search, the menu bar and the other pieces of the visual system."""

from __future__ import annotations

import json
import sqlite3

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest

from antidetect.application.cookie_service import count_cookies
from antidetect.gui import platform as native
from antidetect.gui import theme
from antidetect.gui.components.bulk_bar import BulkBar
from antidetect.gui.components.filter_popover import FilterPopover, FilterState
from antidetect.gui.components.palette import CommandPalette, Entry, rank
from antidetect.gui.components.proxy_info import ProxyInfoPopover
from antidetect.gui.countries import country_name, known_codes
from antidetect.gui.models.profiles import COL_NAME, COL_PROXY
from antidetect.gui.models.roles import ROW_ROLE
from antidetect.gui.sidebar import SECTION_PROFILES, SECTION_PROXIES, SECTION_SETTINGS
from antidetect.gui.theme import flags
from antidetect.gui.theme import icons as ic
from antidetect.gui.theme import tags as tag_colors
from tests.gui.test_gui_models import _row
from tests.support.gui import hover, make_profile, settle, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


# ------------------------------------------------------------------------- flags
def test_every_flag_renders_a_disc_and_unknown_codes_have_none():
    assert len(flags.known()) >= 70
    for code in flags.known():
        pixmap = flags.pixmap(code, 24, 1.0)
        assert pixmap is not None and not pixmap.isNull() and pixmap.width() == 24, code
        assert pixmap.toImage().pixelColor(12, 12).alpha() == 255, code     # opaque in the middle...
        assert pixmap.toImage().pixelColor(0, 0).alpha() == 0, code         # ...and a disc, not a square
    assert flags.pixmap("XX", 24) is None and flags.pixmap(None, 24) is None
    assert flags.pixmap("de", 24, 2.0).width() == 48                         # case-insensitive, rendered at the screen's ratio
    assert flags.icon("FR").availableSizes() and flags.icon("XX").isNull()


def test_every_flag_has_a_localized_name():
    for code in flags.known():
        assert code in known_codes(), code
        assert country_name(code) != code, code


# ------------------------------------------------------------------------- icons
def test_icons_are_rendered_for_the_pixel_ratio_of_the_screen(qapp):
    before = ic.device_ratio()
    try:
        ic.set_device_ratio(1.0)
        assert ic.pixmap("play", "#000000", 16).width() == 16
        assert ic.set_device_ratio(2.0) is True and ic.set_device_ratio(2.0) is False
        pixmap = ic.pixmap("play", "#000000", 16)
        assert pixmap.width() == 32 and pixmap.devicePixelRatio() == 2.0
        assert ic.pixmap("play", "#000000", 16, dpr=1.5).width() == 24
    finally:
        ic.set_device_ratio(before)


def test_an_icon_follows_the_state_colours_at_any_size():
    icon = ic.icon("check", "#112233", hover="#445566", disabled="#778899", size=16)
    normal = icon.pixmap(QSize(32, 32), QIcon.Mode.Normal).toImage()
    disabled = icon.pixmap(QSize(32, 32), QIcon.Mode.Disabled).toImage()
    assert normal.size() == QSize(32, 32)
    colours = {(normal.pixelColor(x, y).red(), disabled.pixelColor(x, y).red())
               for x in range(32) for y in range(32) if normal.pixelColor(x, y).alpha() > 250}
    assert (0x11, 0x77) in colours
    assert icon.pixmap(QSize(64, 64)).width() == 64 and not icon.isNull()


# ------------------------------------------------------------------------- tags
def test_tag_colours_come_from_the_registry_slots_and_fall_back_to_the_name():
    tag_colors.register([("Work", 3), ("Dev", 4)])
    try:
        assert tag_colors.tag_color("Work") == tag_colors.slot_color(3)
        assert tag_colors.tag_color("  work ") == tag_colors.tag_color("WORK")          # case-insensitive
        assert tag_colors.tag_color("Dev") == tag_colors.slot_color(4)
        unknown = tag_colors.tag_color("never-registered")
        assert unknown.startswith("#") and unknown == tag_colors.tag_color("Never-Registered")
        assert len(set(tag_colors.colors())) == 12 and tag_colors.slot_color(13) == tag_colors.slot_color(1)
        tag_colors.register([("x", 99)])                                                  # a bad slot wraps, never crashes
        assert tag_colors.tag_color("x").startswith("#")
    finally:
        tag_colors.register([])


# ------------------------------------------------------------------------- cookies
def _cookie_db(path, count):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("create table cookies(x)")
    con.executemany("insert into cookies values(?)", [(i,) for i in range(count)])
    con.commit()
    con.close()


def test_cookie_count_reads_the_newest_database_and_follows_changes(tmp_path):
    import os

    assert count_cookies(tmp_path) is None                                    # never ran
    _cookie_db(tmp_path / "Default" / "Cookies", 3)
    assert count_cookies(tmp_path) == 3
    _cookie_db(tmp_path / "Default" / "Network" / "Cookies", 7)
    newer = (tmp_path / "Default" / "Cookies").stat().st_mtime_ns + 5_000_000_000
    os.utime(tmp_path / "Default" / "Network" / "Cookies", ns=(newer, newer))
    assert count_cookies(tmp_path) == 7                                       # modern Chrome keeps them under Network/
    con = sqlite3.connect(tmp_path / "Default" / "Network" / "Cookies")
    con.execute("insert into cookies values(1)")
    con.commit()
    con.close()
    later = newer + 5_000_000_000
    os.utime(tmp_path / "Default" / "Network" / "Cookies", ns=(later, later))
    assert count_cookies(tmp_path) == 8                                       # the cache notices a new file version
    (tmp_path / "Default" / "Network" / "Cookies").write_bytes(b"not sqlite")
    assert count_cookies(tmp_path) is None                                    # unreadable = unknown, never an error


def test_the_profile_table_shows_the_cookie_count_and_creation_date(window, gui_container):
    profile = make_profile(gui_container, "Jar")
    _cookie_db(__import__("pathlib").Path(profile.profile_path) / "Default" / "Cookies", 42)
    page = settle(window, 1)
    page.reload()
    assert spin_wait(lambda: page._model.rows()[0].cookie_count == 42)
    assert page._model.rows()[0].created_at is not None


# ------------------------------------------------------------------------- platform
def test_native_title_bar_calls_are_no_ops_off_macos_windows():
    assert native.expands_into_titlebar() is False        # the tests run on the offscreen platform
    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    assert native.expand_into_titlebar(widget) == 0
    native.finish_titlebar(widget)                         # must not touch the native window API


# ------------------------------------------------------------------------- quick search
def _entries():
    return [
        Entry("page", "Profiles"), Entry("action", "New profile", keywords="create"),
        Entry("profile", "Facebook Ads #1", "1.1.1.1:80 · Chrome 154", keywords="ads us"),
        Entry("profile", "Amazon seller", keywords="shop"), Entry("tag", "ads", "Tag"),
    ]


def test_quick_search_matches_every_word_and_ranks_titles_first():
    entries = _entries()
    assert [e.title for e in rank(entries, "")] == [e.title for e in entries]
    assert [e.title for e in rank(entries, "ads")] == ["ads", "Facebook Ads #1"]          # title start > word > keyword
    assert [e.title for e in rank(entries, "facebook 1.1")] == ["Facebook Ads #1"]         # every word must match
    assert [e.title for e in rank(entries, "create")] == ["New profile"]                   # keywords count
    assert rank(entries, "zzz") == []


def test_quick_search_keyboard_flow(qapp):
    ran = []
    entries = [Entry("action", "Alpha", run=lambda: ran.append("a")), Entry("action", "Beta", run=lambda: ran.append("b"))]
    palette = CommandPalette(entries)
    palette.show()
    assert [e.title for e in palette.results()] == ["Alpha", "Beta"]
    QTest.keyClick(palette._input, Qt.Key.Key_Down)
    QTest.keyClick(palette._input, Qt.Key.Key_Return)
    assert ran == ["b"] and not palette.isVisible()                                       # the arrow moved, Enter ran it
    palette = CommandPalette(entries)
    palette.show()
    palette.set_query("zzz")
    assert palette.results() == [] and palette._empty.isVisibleTo(palette)
    QTest.keyClick(palette._input, Qt.Key.Key_Return)                                     # nothing selected: nothing runs
    palette.close()
    assert ran == ["b"]


def test_the_window_offers_profiles_pages_actions_and_tags_in_quick_search(window, gui_container, monkeypatch):
    make_profile(gui_container, "Shop one", tags=["eu"])
    page = settle(window, 1)
    assert spin_wait(lambda: "eu" in window._sidebar._tag_rows)
    palette = window.open_palette()
    kinds = {e.kind for e in palette.results()}
    assert kinds == {"profile", "action", "page", "tag"}
    started = []
    monkeypatch.setattr(page, "toggle_profile", lambda row: started.append(row.name))
    palette.set_query("shop")
    assert [e.kind for e in palette.results()][0] == "profile"
    QTest.keyClick(palette._input, Qt.Key.Key_Return)
    assert started == ["Shop one"]
    window.open_palette().set_query("eu")
    window._palette.results()[0].run()                                                   # the tag entry narrows the list
    assert page.tag() == "eu"
    window._palette.close()


def test_the_menu_bar_owns_the_shortcuts_and_reaches_every_page(window):
    shortcuts = {a.shortcut().toString() for a in window.actions() if not a.shortcut().isEmpty()}
    assert {"Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6", "Ctrl+K", "Ctrl+N", "Ctrl+,"} <= shortcuts
    assert not window.menuBar().isVisibleTo(window)       # off macOS no menu bar is drawn; the shortcuts still work
    by_shortcut = {a.shortcut().toString(): a for a in window.actions()}
    by_shortcut["Ctrl+2"].trigger()
    assert window.current_section() == SECTION_PROXIES
    by_shortcut["Ctrl+,"].trigger()
    assert window.current_section() == SECTION_SETTINGS
    by_shortcut["Ctrl+K"].trigger()
    assert window._palette.isVisible()
    window._palette.close()


def test_menu_texts_follow_the_language(window):
    from antidetect.i18n import tr

    window.set_language("ru")
    assert window.menuBar().actions()[0].text() == tr("menu.file", "ru") == "Файл"


# ------------------------------------------------------------------------- popovers
def test_filter_popover_reports_every_choice_and_resets(qapp):
    seen = []
    pop = FilterPopover(None, current=FilterState(), tags={"eu": 2, "us": 1})
    pop.changed.connect(seen.append)
    pop._state.button("running").click()
    assert seen[-1] == FilterState(state="running")
    pop._platforms._buttons["macos"].click()
    pop._proxy.button("without").click()
    pop._cookies.button("with").click()
    pop._created.button("week").click()
    pop._tags._buttons["eu"].click()
    assert seen[-1] == FilterState("running", frozenset({"macos"}), "without", "with", "week", "eu")
    pop._tags._buttons["us"].click()                                                    # tags are a single choice
    assert seen[-1].tag == "us" and not pop._tags._buttons["eu"].isChecked()
    pop._reset.click()
    assert seen[-1] == FilterState()
    shown = FilterPopover(None, current=FilterState("stopped", frozenset({"linux"}), "with", "without", "month", "eu"),
                          tags={"eu": 1})
    assert shown._state.value() == "stopped" and shown._platforms.value() == frozenset({"linux"})
    assert shown._proxy.value() == "with" and shown._tags.value() == frozenset({"eu"})
    assert shown._cookies.value() == "without" and shown._created.value() == "month"


def test_filter_popover_wraps_many_tags_instead_of_squeezing_them(qapp):
    tags = {f"a-rather-long-tag-{i}": 1 for i in range(10)}
    pop = FilterPopover(None, current=FilterState(), tags=tags)
    pop.show()
    chips = list(pop._tags._buttons.values())
    assert all(chip.width() >= chip.sizeHint().width() - 1 for chip in chips)
    assert len({chip.y() for chip in chips}) > 1


def test_proxy_popover_describes_the_proxy_and_asks_for_a_check(qapp):
    row = _row(proxy_id=3, proxy_endpoint="9.9.9.9:80", proxy_protocol="SOCKS5", proxy_country_code="DE",
               proxy_country="Germany", proxy_latency=88, proxy_status="WORKING", proxy_username="neo", proxy_free=True)
    pop = ProxyInfoPopover(row)
    texts = {label.text() for label in pop.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)}
    assert {"9.9.9.9:80", "neo", "88 ms", "socks5", "Europe/Berlin"} <= texts
    assert any("Germany" in t for t in texts)
    asked = []
    pop.checkRequested.connect(lambda: asked.append(1))
    pop.show()
    next(b for b in pop.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
         if b.text() == "Check now").click()
    assert asked == [1] and not pop.isVisible()


def test_bulk_bar_signals_and_text(qapp):
    bar = BulkBar()
    got = []
    for name in ("startRequested", "stopRequested", "deleteRequested", "clearRequested"):
        getattr(bar, name).connect(lambda n=name: got.append(n))
    bar.set_count(3)
    assert bar._count.text() == "3 selected"
    bar._start.click(); bar._stop.click(); bar._delete.click(); bar._clear.click()
    assert got == ["startRequested", "stopRequested", "deleteRequested", "clearRequested"]


# ------------------------------------------------------------------------- the table
def test_clicking_an_avatar_checks_the_row_and_the_proxy_buttons_work(window, gui_container):
    make_profile(gui_container, "One", proxy_text="10.0.0.1:80")
    make_profile(gui_container, "Two")
    page = settle(window, 2)
    window.resize(1360, 800)
    window.show_section(SECTION_PROFILES)
    spin_wait(lambda: False, 200)
    view, delegate = page._view, page._delegate
    cell = view.visualRect(view.model().index(0, COL_NAME))
    avatar = delegate.avatar_rect(cell).center()
    assert not delegate.hotspot(view.model().index(0, COL_NAME), avatar, view)         # a plain avatar is not a button...
    hover(view.viewport(), avatar)
    assert delegate.hotspot(view.model().index(0, COL_NAME), avatar, view)             # ...until the pointer is over the row
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=avatar)
    assert [r.name for r in page.selected_rows()] == ["One"]
    other = delegate.avatar_rect(view.visualRect(view.model().index(1, COL_NAME))).center()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=other)           # a second click adds, not replaces
    assert sorted(r.name for r in page.selected_rows()) == ["One", "Two"]
    assert page._bulk.isVisibleTo(page)
    view.clearSelection()

    row = next(r for r in page._model.rows() if r.name == "One")
    page.check_proxy(row)
    assert page._model.checking(row.id)
    assert spin_wait(lambda: not page._model.checking(row.id))
    assert spin_wait(lambda: next(r for r in page._model.rows() if r.name == "One").proxy_checked_at is not None)
    no_proxy = next(r for r in page._model.rows() if r.name == "Two")
    page.check_proxy(no_proxy)                                                         # nothing to check: quietly ignored
    assert not page._model.checking(no_proxy.id)


def test_the_proxy_info_button_opens_the_popover(window, gui_container):
    make_profile(gui_container, "One", proxy_text="10.0.0.1:80")
    page = settle(window, 1)
    window.show_section(SECTION_PROFILES)
    index = page._view.model().index(0, COL_PROXY)
    assert index.data(ROW_ROLE).proxy_endpoint == "10.0.0.1:80"
    from PySide6.QtCore import QRect

    page._on_proxy_info(index, QRect(QPoint(100, 100), QSize(26, 26)))
    assert page._info_popover is not None and page._info_popover.isVisible()
    page._info_popover.close()


def test_proxies_page_collapses_its_buttons_to_icons_when_narrow(window):
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    window.resize(1040, 700)
    spin_wait(lambda: False, 100)
    page._apply_compact()
    assert page._check_all.text() == "" and page._free.text() == "" and page._free.toolTip()
    window.resize(1500, 700)
    spin_wait(lambda: False, 100)
    page._apply_compact()
    assert page._check_all.text() == "Check all"


def test_sidebar_counters_and_tag_list(window, gui_container):
    for index in range(10):
        make_profile(gui_container, f"P{index}", tags=[f"tag{index}"])
    page = settle(window, 10)
    sidebar = window._sidebar
    assert spin_wait(lambda: len(sidebar._tag_rows) == 8)                              # eight shown, the rest behind "more"
    assert sidebar._buttons[SECTION_PROFILES]._count == "10"
    sidebar._show_more()
    assert len(sidebar._tag_rows) == 10
    sidebar.fold_tags(True)
    assert not sidebar._tag_box.isVisibleTo(sidebar)
    sidebar.fold_tags(False)
    assert sidebar._tag_box.isVisibleTo(sidebar)
    window.show_tag("tag9")
    assert sidebar._tag_rows["tag9"].isChecked() and page.tag() == "tag9"


def test_new_palette_tokens_stay_readable():
    def lum(c):
        r, g, b = (int(c[i:i + 2], 16) / 255 for i in (1, 3, 5))
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in (r, g, b)]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def ratio(a, b):
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    for p in (theme.LIGHT, theme.DARK):
        assert ratio(p.muted, p.window) >= 4.5, p.name                  # sidebar labels
        assert ratio(p.text, p.nav_selected) >= 7, p.name               # the active sidebar row
        assert ratio(p.muted, p.nav_selected) >= 4, p.name
        assert ratio(p.text, p.pill) >= 7, p.name                       # dates inside the little cards
        assert ratio(p.muted, p.accent_soft) >= 4, p.name               # selected table row
