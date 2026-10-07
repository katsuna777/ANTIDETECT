"""Proxies page: listing, search, deleting, empty state, progress strip."""

from __future__ import annotations

import pytest

from antidetect.gui.sidebar import SECTION_PROXIES
from antidetect.gui.workers import tasks
from antidetect.gui.workers import tasks as workers_tasks
from tests.support.gui import make_profile, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def test_proxies_page_lists_filters_and_deletes(window, gui_container):
    tasks.import_proxies(gui_container, "10.0.0.1:80\n10.0.0.2:80", "HTTP", False)(lambda *a: None)
    make_profile(gui_container, "User", proxy_text="10.0.0.1:80")
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 2)
    assert page._count.text() == "2" and page._working.text() == "1 working"  # the one pasted with the profile was checked
    used = {r.address: r.used_by for r in page._model.rows()}
    assert used["10.0.0.1:80"] == ("User",)
    page._search.setText("10.0.0.2")
    assert page._filter.rowCount() == 1
    page._search.setText("zzz")
    assert page._stack.currentWidget() is page._empty and page._empty.title.text() == "No profiles match your search"
    page._search.setText("")
    assert page._stack.currentWidget() is page._view
    page.delete_rows([r for r in page._model.rows() if r.address == "10.0.0.2:80"])
    assert spin_wait(lambda: page._model.rowCount() == 1)


def _add_free_proxy(container) -> None:
    from antidetect.domain.enums.proxy_status import ProxyProtocol
    from antidetect.domain.models.proxy_entry import ProxyEntry

    container.proxies._proxies.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host="203.0.113.77", port=80, source="free-list")]
    )


def test_free_proxy_warning_shows_only_while_free_proxies_are_around(window, gui_container):
    tasks.import_proxies(gui_container, "10.0.0.1:80", "HTTP", False)(lambda *a: None)
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 1)
    assert not page._free_notice.isVisibleTo(page)  # the user's own proxies need no warning
    _add_free_proxy(gui_container)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 2)
    assert page._free_notice.isVisibleTo(page) and "testing only" in page._free_notice._title.text()
    page.delete_rows([r for r in page._model.rows() if not r.is_manual])
    assert spin_wait(lambda: page._model.rowCount() == 1)
    assert not page._free_notice.isVisibleTo(page)


def test_free_proxy_warning_appears_as_soon_as_collecting_starts(window, gui_container):
    tasks.import_proxies(gui_container, "10.0.0.1:80", "HTTP", False)(lambda *a: None)
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 1)
    page._live = True
    page._sync_free_notice()
    assert page._free_notice.isVisibleTo(page)


def test_proxies_empty_state(window):
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._stack.currentWidget() is page._empty)
    assert page._empty.title.text() == "No proxies yet" and not page._search.isEnabled()


def test_check_all_runs_with_progress_and_restores_the_buttons(window, gui_container):
    tasks.import_proxies(gui_container, "10.0.0.1:80\n10.0.0.2:80", "HTTP", False)(lambda *a: None)
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 2)
    page.check_all()
    assert not page._check_all.isEnabled() and page._status_bar.isVisibleTo(page)
    assert spin_wait(lambda: page._check_all.isEnabled())
    assert not page._status_bar.isVisibleTo(page)


def test_context_menu_offers_check_copy_and_delete(window, gui_container):
    tasks.import_proxies(gui_container, "10.0.0.1:80", "HTTP", False)(lambda *a: None)
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 1)
    page._view.selectRow(0)
    from antidetect.gui.components import StyledMenu

    captured = {}
    monkey = StyledMenu.exec
    StyledMenu.exec = lambda self, *a, **k: captured.setdefault("texts", [x.text() for x in self.actions() if x.text()])
    try:
        page._context_menu(page._view.visualRect(page._filter.index(0, 0)).center())
    finally:
        StyledMenu.exec = monkey
    assert captured["texts"] == ["Check", "Copy address", "Delete"]


def test_check_all_checks_what_is_listed_in_one_batch(window, gui_container, monkeypatch):
    tasks.import_proxies(gui_container, "10.0.0.1:80\n10.0.0.2:80\n10.0.0.3:80", "HTTP", False)(lambda *a: None)
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 3)
    asked = []
    monkeypatch.setattr(workers_tasks, "check_proxies", lambda container, ids=None, **_: (asked.append(ids), lambda progress: None)[1])
    page.check_all()
    assert len(asked) == 1 and sorted(asked[0]) == sorted(r.id for r in page._model.rows())
    assert spin_wait(lambda: page._check_all.isEnabled())


def test_the_proxies_page_has_no_unchecked_free_list_filter(window):
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    assert not hasattr(page, "_scope")


def test_reloads_requested_while_one_is_in_flight_are_coalesced(window, gui_container):
    tasks.import_proxies(gui_container, "10.0.0.1:80", "HTTP", False)(lambda *a: None)
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    spin_wait(lambda: not page._reloading)
    page.reload()
    page.reload()
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 1 and not page._reloading and not page._reload_again)


def test_stop_answers_at_once_and_the_status_is_not_overwritten_while_winding_down(window, gui_container):
    import threading

    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page._stop_event = threading.Event()
    page._begin("Collecting…", can_stop=True)
    assert page._stop.isVisibleTo(page) and page._stop.isEnabled()
    page._request_stop()
    assert page._stop_event.is_set() and not page._stop.isEnabled()
    assert page._status.text() == "Stopping…" and page._progress.maximum() == 0
    page._progress_update(5, 100)                                     # a late report from the worker
    assert page._status.text() == "Stopping…"
    page._end()
    assert page._stop_event is None and not page._stopping and not page._stop.isVisibleTo(page)


def test_check_all_can_be_stopped_too(window, gui_container, monkeypatch):
    seen: dict = {}

    def fake_check(container, ids=None, *, stop_event=None):
        seen["stop_event"] = stop_event
        return lambda progress: None

    monkeypatch.setattr(workers_tasks, "check_proxies", fake_check)
    tasks.import_proxies(gui_container, "10.0.0.1:80", "HTTP", False)(lambda *a: None)
    window.show_section(SECTION_PROXIES)
    page = window.page(SECTION_PROXIES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == 1)
    page.check_all()
    assert spin_wait(lambda: "stop_event" in seen)
    assert seen["stop_event"] is not None
    assert spin_wait(lambda: not page._busy)
