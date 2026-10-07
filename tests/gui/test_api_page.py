"""The API page: switch, port, keys, the instruction; and a window that follows what scripts do."""

from __future__ import annotations

import socket

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLineEdit

from antidetect.api import ApiSettings
from antidetect.api import reference as ref
from antidetect.gui.main_window import MainWindow
from antidetect.gui.pages.api import KeyNameDialog
from antidetect.gui.sidebar import SECTION_API, SECTION_PROFILES, SECTION_SETTINGS
from tests.api.conftest import Client, free_port
from tests.gui.conftest import release
from tests.support.gui import spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture()
def page(window, gui_container):
    gui_container.profiles._geo_lookup = lambda: None
    ApiSettings(gui_container.settings).set_port(free_port())
    window.show_section(SECTION_API)
    return window.page(SECTION_API)


def _client(window, key=None) -> Client:
    return Client(window.api.port, (key or window.api.settings.keys()[0]).token)


def _answer_dialog(monkeypatch, name: str, accept: bool = True):
    """Fill in and confirm the key-name dialog the way a user would."""
    seen: list[KeyNameDialog] = []

    def run(self) -> int:
        seen.append(self)
        self.set_name(name)
        self._accept()
        return 1 if accept and not self._error.isVisibleTo(self) else 0

    monkeypatch.setattr(KeyNameDialog, "exec", run)
    return seen


# ---------------------------------------------------------------------------- the section

def test_api_is_a_section_of_its_own_with_a_key_counter(window, page):
    assert SECTION_API in window._sidebar._buttons
    assert window._sidebar._buttons[SECTION_API].text() == "API"
    assert window._sidebar._buttons[SECTION_API]._count == "1"           # one key from the start
    assert window.current_section() == SECTION_API
    assert window._api is None                                           # off: nothing was loaded or started
    assert page._title.text() == "API" and page._card.state.text() == "Off"


def test_the_settings_page_no_longer_carries_an_api_block(window):
    window.show_section(SECTION_SETTINGS)
    settings = window.page(SECTION_SETTINGS)
    assert not hasattr(settings, "_api_switch") and not hasattr(settings, "_token")


def test_the_counter_follows_the_number_of_keys(window, page, monkeypatch):
    _answer_dialog(monkeypatch, "Parser")
    page.new_key()
    assert window._sidebar._buttons[SECTION_API]._count == "2"


# ------------------------------------------------------------------------ switch and port

def test_switching_it_on_starts_the_server_and_shows_the_address(page, window):
    page._card.switch.setChecked(True)
    assert window.api.running
    assert page._card.state.text() == "Running" and page._card.state.property("role") == "success"
    assert page._card.dot._state == "on"
    assert _client(window).get("/v1/status")[0] == 200
    page._card.switch.setChecked(False)
    assert not window.api.running
    assert page._card.state.text() == "Off" and page._card.dot._state == "off"
    assert ApiSettings(window._container.settings).enabled is False


def test_a_busy_port_turns_the_switch_back_off_and_says_why(page, window):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        page._card.port.setText(str(port))
        page._card.port.editingFinished.emit()
        page._card.switch.setChecked(True)
        assert page._card.switch.isChecked() is False and not window.api.running
        assert page._card.state.text() == f"Port {port} is busy"
        assert page._card.state.property("role") == "danger" and page._card.dot._state == "error"
        assert ApiSettings(window._container.settings).enabled is False


def test_the_port_can_be_changed_live_and_bad_ports_are_refused(page, window):
    page._card.switch.setChecked(True)
    old, new = window.api.port, free_port()
    page._card.port.setText(str(new))
    page._card.port.editingFinished.emit()
    assert window.api.port == new != old and window.api.running
    assert Client(new, window.api.settings.keys()[0].token).get("/v1/status")[0] == 200
    for bad in ("22", "99999", "0"):
        page._card.port.setText(bad)
        page._card.port.editingFinished.emit()
        assert page._card.port.text() == str(new) and window.api.port == new
        assert page._card.state.text() == "Port: 1024–65535"


def test_copying_the_address(page, window):
    page._card.copy.click()
    assert QGuiApplication.clipboard().text() == ApiSettings(window._container.settings).url
    assert window.toasts.count() == 1


# ------------------------------------------------------------------------------- keys

def test_the_first_key_is_listed_hidden_and_can_be_shown_and_copied(page, window):
    (row,) = page.key_rows()
    key = row.key
    assert row._name.text() == "Main" and row._secret.text() == key.masked() and key.token not in row._secret.text()
    assert row._last.text() == "Not used yet" and "Requests since start: 0" in row.toolTip()
    row._toggle.click()
    assert row._secret.text() == key.token and row.secret_shown
    row._toggle.click()
    assert row._secret.text() == key.masked()
    row._copy.click()
    assert QGuiApplication.clipboard().text() == key.token
    assert window.toasts.count() == 1


def test_a_new_key_is_made_through_the_dialog_and_works_at_once(page, window, monkeypatch):
    page._card.switch.setChecked(True)
    _answer_dialog(monkeypatch, "Parser")
    page.new_key()
    assert [r.key.name for r in page.key_rows()] == ["Main", "Parser"]
    assert window._sidebar._buttons[SECTION_API]._count == "2"
    assert window.toasts.count() == 1
    parser = page.key_rows()[1].key
    assert Client(window.api.port, parser.token).get("/v1/status")[0] == 200


def test_the_dialog_refuses_empty_and_duplicate_names_and_says_why(page, window, monkeypatch):
    seen = _answer_dialog(monkeypatch, "main")                       # "Main" exists: case does not matter
    page.new_key()
    assert len(page.key_rows()) == 1
    assert seen[0]._error.text() == "A key with this name already exists." and not seen[0]._error.isHidden()
    dialog = KeyNameDialog(None, "t", "ok", lambda name: None)
    assert not dialog.ok.isEnabled()
    dialog.set_name("  ")
    assert not dialog.ok.isEnabled()
    dialog.set_name("x")
    assert dialog.ok.isEnabled()


def test_renaming_a_key(page, window, monkeypatch):
    seen = _answer_dialog(monkeypatch, "Scraper")
    page.rename_key(page.key_rows()[0].key.id)
    assert page.key_rows()[0]._name.text() == "Scraper"
    assert seen[0]._edit.text() == "Scraper"


def test_a_new_secret_needs_confirming_and_locks_out_the_old_one(page, window, monkeypatch):
    page._card.switch.setChecked(True)
    key = page.key_rows()[0].key
    monkeypatch.setattr("antidetect.gui.pages.api.confirm", lambda *a, **k: False)
    page.regenerate_key(key.id)
    assert window.api.settings.keys()[0].token == key.token
    asked: list[str] = []
    monkeypatch.setattr("antidetect.gui.pages.api.confirm", lambda parent, title, *a, **k: asked.append(title) or True)
    page.regenerate_key(key.id)
    assert asked == ["Make a new secret for “Main”?"]
    fresh = window.api.settings.keys()[0]
    assert fresh.token != key.token and fresh.id == key.id
    assert Client(window.api.port, key.token).get("/v1/status")[0] == 401
    assert Client(window.api.port, fresh.token).get("/v1/status")[0] == 200
    assert page.key_rows()[0].key.token == fresh.token


def test_deleting_a_key_needs_confirming_and_the_last_one_has_no_delete_item(page, window, monkeypatch):
    page._card.switch.setChecked(True)
    _answer_dialog(monkeypatch, "Second")
    page.new_key()
    second = page.key_rows()[1].key
    monkeypatch.setattr("antidetect.gui.pages.api.confirm", lambda *a, **k: False)
    page.delete_key(second.id)
    assert len(page.key_rows()) == 2
    monkeypatch.setattr("antidetect.gui.pages.api.confirm", lambda *a, **k: True)
    page.delete_key(second.id)
    assert [r.key.name for r in page.key_rows()] == ["Main"]
    assert window._sidebar._buttons[SECTION_API]._count == "1"
    assert Client(window.api.port, second.token).get("/v1/status")[0] == 401
    shown: list[list[str]] = []
    from antidetect.gui.components import StyledMenu

    monkeypatch.setattr(StyledMenu, "exec", lambda self, *a: shown.append([x.text() for x in self.actions() if x.text()]))
    page._key_menu(page.key_rows()[0].key.id, None)
    assert shown == [["Rename…", "Make a new secret…"]]               # nothing to delete: it is the last key


def test_the_page_shows_what_each_key_has_done(page, window):
    page._card.switch.setChecked(True)
    for _ in range(3):
        _client(window).get("/v1/status")
    page._tick()
    row = page.key_rows()[0]
    assert row._last.text() == "Just now"
    assert "Requests since start: 3" in row.toolTip() and "Created" in row.toolTip()


def test_a_key_that_is_shown_stays_shown_when_another_is_added(page, window, monkeypatch):
    page.key_rows()[0]._toggle.click()
    _answer_dialog(monkeypatch, "Other")
    page.new_key()
    assert page.key_rows()[0].secret_shown and not page.key_rows()[1].secret_shown


# ------------------------------------------------------------------------ instruction

def test_the_instruction_opens_from_the_header_and_goes_back(page, window):
    assert not page.docs_open()
    page._instruction.click()
    assert page.docs_open() and page._docs._title.text() == "API instruction"
    page._docs._back.click()
    assert not page.docs_open()


def test_the_instruction_describes_every_method_and_unfolds_on_click(page, window):
    page.open_docs()
    rows = page._docs.endpoint_rows()
    assert [(r.endpoint.method, r.endpoint.path) for r in rows] == [(e.method, e.path) for e in ref.all_endpoints()]
    assert not any(r.is_open for r in rows)
    start = next(r for r in rows if r.endpoint.path == "/v1/profiles/{id}/start")
    start._head.mousePressEvent(None)
    assert start.is_open
    start._head.mousePressEvent(None)
    assert not start.is_open


def test_the_instruction_has_ready_scripts_with_the_real_address_and_key(page, window):
    page.open_docs()
    docs = page._docs
    token = ApiSettings(window._container.settings).keys()[0].token
    assert list(docs._sample) == ["playwright", "puppeteer", "selenium", "curl"]
    for item in docs._sample.values():
        assert token in item.code and "http://127.0.0.1:" in item.code and "%(" not in item.code
    docs._tabs.set_current("selenium")
    docs._copy.click()
    assert QGuiApplication.clipboard().text() == docs._sample["selenium"].code
    assert docs._copy.text() == "Script copied"


def test_the_instruction_warns_when_the_api_is_off_and_not_when_it_is_on(page, window):
    page.open_docs()
    warning = page._docs._off_warning
    assert not warning.isHidden() and "switched off" in warning._text.text()
    page._card.switch.setChecked(True)
    page.open_docs()
    assert warning.isHidden()
    page._card.switch.setChecked(False)
    page.open_docs()
    assert not warning.isHidden()


def test_the_instruction_follows_language_and_theme_and_keeps_what_is_open(page, window):
    page.open_docs()
    row = next(r for r in page._docs.endpoint_rows() if r.endpoint.path == "/v1/proxies")
    row.set_open(True)
    window.set_language("ru")
    assert page._docs._title.text() == "Инструкция по API" and page._title.text() == "API"
    assert page._instruction.text() == "Инструкция" and page.docs_open()
    reopened = next(r for r in page._docs.endpoint_rows() if r.endpoint.path == "/v1/proxies" and r.endpoint.method == "GET")
    assert reopened.is_open                                              # still unfolded after the rebuild
    assert "Список прокси" in [l.text() for l in reopened._head.findChildren(type(page._title))]
    window.set_theme("dark")
    assert page.docs_open() and page._docs.endpoint_rows()
    window.set_language("en")
    assert page._docs._title.text() == "API instruction"


def test_the_instruction_opens_with_five_steps_and_chips_that_scroll_to_sections(page, window):
    window.resize(1280, 800)
    page.open_docs()
    docs = page._docs
    assert docs._chips.count() >= 6 and docs._chips.itemAt(0).widget().text() == "Quick start"
    assert set(docs._anchors) >= {"quickstart", "connect", "methods", "types", "errors", "tips"}
    bar = docs._scroll.verticalScrollBar()
    assert bar.value() == 0
    docs._chips.itemAt(4).widget().click()                              # "Errors"
    assert bar.value() > 0
    docs.scroll_to("quickstart")
    assert bar.value() < 100


def test_escape_leaves_the_instruction(page):
    from PySide6.QtGui import QShortcut

    page.open_docs()
    (escape,) = page._docs.findChildren(QShortcut)
    assert escape.key().toString() == "Esc"
    escape.activated.emit()
    assert not page.docs_open()


def test_opening_the_instruction_again_does_not_rebuild_it(page, window):
    page.open_docs()
    first = page._docs.endpoint_rows()
    page.show_main()
    page.open_docs()
    assert page._docs.endpoint_rows() == first                           # the same widgets: nothing was rebuilt
    page._card.switch.setChecked(True)
    page.open_docs()
    assert page._docs.endpoint_rows() == first and page._docs._off_warning.isHidden()


def test_a_theme_or_language_change_lets_go_of_it_and_it_is_rebuilt_when_next_needed(page, window):
    page.open_docs()
    page._docs.endpoint_rows()[0].set_open(True)
    page.show_main()
    window.set_language("ru")                                            # not on screen: no stale copy is kept (or restyled)
    assert not page._docs._built and page._docs.endpoint_rows() == []
    page.open_docs()
    assert page._docs._built and page._docs._title.text() == "Инструкция по API"
    assert page._docs.endpoint_rows()[0].is_open                         # what was unfolded is unfolded again
    page.show_main()
    window.set_theme("dark")
    assert not page._docs._built
    page.open_docs()
    assert page._docs._built


def test_a_theme_switch_with_the_instruction_open_keeps_what_was_unfolded_and_the_scroll_position(page, window):
    window.resize(1280, 800)
    page.open_docs()
    docs = page._docs
    docs.endpoint_rows()[3].set_open(True)
    docs._models[1].set_open(True)
    docs.scroll_to("methods")
    before = docs._scroll.verticalScrollBar().value()
    assert before > 0
    window.set_theme("dark")
    spin_wait(lambda: False, 50)
    assert page.docs_open() and docs._built
    assert docs.endpoint_rows()[3].is_open and docs._models[1].is_open
    assert abs(docs._scroll.verticalScrollBar().value() - before) < 5


def test_coming_back_to_the_instruction_after_a_theme_change_shows_it_in_the_new_theme(page, window):
    """The API page keeps showing the instruction when you leave it; a theme change while away used to
    leave a light table on a dark page (and an empty page once the stale copy was let go of)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    from antidetect.gui.theme import DARK, LIGHT

    page.open_docs()
    window.show_section(SECTION_SETTINGS)
    window.set_theme("dark")
    window.show_section(SECTION_API)
    spin_wait(lambda: False, 30)
    docs = page._docs
    assert page.docs_open() and docs._built and docs._scroll.widget() is not None
    docs._models[0].set_open(True)
    table = next(l for l in docs.findChildren(QLabel) if l.textFormat() == Qt.TextFormat.RichText and "<table" in l.text())
    assert DARK.subtle in table.text() and LIGHT.subtle not in table.text()


def test_the_costly_tables_are_only_built_when_a_row_is_opened(page, window):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    def tables(docs) -> int:
        return sum(1 for l in docs.findChildren(QLabel) if l.textFormat() == Qt.TextFormat.RichText and "<table" in l.text())

    page.open_docs()
    docs = page._docs
    start = tables(docs)
    assert start <= 2                                                    # the error table and the access-key header only
    docs.endpoint_rows()[0].set_open(True)
    docs._models[0].set_open(True)
    assert tables(docs) == start + 2
    docs._models[0].set_open(False)
    assert docs._models[0].is_open is False and tables(docs) == start + 2     # folding keeps the built table


def test_the_script_tabs_are_laid_out_when_first_opened(page, window):
    from PySide6.QtWidgets import QPlainTextEdit

    page.open_docs()
    docs = page._docs
    assert len(docs.findChildren(QPlainTextEdit)) == 1                   # only the first tab
    docs._tabs.set_current("curl")
    assert len(docs.findChildren(QPlainTextEdit)) == 2
    assert docs._editors["curl"].toPlainText() == docs._sample["curl"].code


def test_the_page_follows_the_language(page, window):
    window.set_language("ru")
    assert page._instruction.text() == "Инструкция" and page._new_key.text() == "Новый ключ"
    assert page._card.state.text() == "Выключено" and page._g_keys.caption.text() == "КЛЮЧИ"
    assert page.key_rows()[0]._last.text() == "Не использовался"
    window.set_language("en")
    assert page._new_key.text() == "New key"


# --------------------------------------------------------------- the window and the server

def test_profiles_made_by_scripts_appear_in_the_table_and_follow_start_and_stop(page, window):
    page._card.switch.setChecked(True)
    window.show_section(SECTION_PROFILES)
    profiles = window.page(SECTION_PROFILES)
    client = _client(window)
    status, profile, _ = client.post("/v1/profiles", {"name": "From script", "geo_auto": False})
    assert status == 201
    assert spin_wait(lambda: profiles._model.rowCount() == 1)
    assert profiles._model.rows()[0].name == "From script"
    client.post(f"/v1/profiles/{profile['id']}/start")
    assert spin_wait(lambda: profiles._model.rows()[0].running)
    client.post(f"/v1/profiles/{profile['id']}/stop")
    assert spin_wait(lambda: not profiles._model.rows()[0].running)
    client.delete(f"/v1/profiles/{profile['id']}")
    assert spin_wait(lambda: profiles._model.rowCount() == 0)


def test_closing_the_window_stops_the_api(gui_container, fake_chromium):
    gui_container.browser.set_chromium_path(fake_chromium)
    ApiSettings(gui_container.settings).set_port(free_port())
    win = MainWindow(gui_container)
    win.show()
    win.show_section(SECTION_API)
    win.page(SECTION_API)._card.switch.setChecked(True)
    port = win.api.port
    manager = win.api
    win.close()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))                                   # free again
    assert not manager.running
    release(win)


def test_it_starts_again_on_launch_when_it_was_switched_on(gui_container, fake_chromium):
    gui_container.browser.set_chromium_path(fake_chromium)
    settings = ApiSettings(gui_container.settings)
    settings.set_port(free_port())
    settings.set_enabled(True)
    win = MainWindow(gui_container)
    win.show()
    try:
        assert spin_wait(lambda: win._api is not None and win.api.running)
        assert Client(win.api.port, settings.token).get("/v1/status")[0] == 200
        win.show_section(SECTION_API)
        page = win.page(SECTION_API)
        assert page._card.switch.isChecked() and page._card.state.text() == "Running"
    finally:
        release(win)


def test_a_port_taken_at_launch_is_reported_not_swallowed(gui_container, fake_chromium):
    gui_container.browser.set_chromium_path(fake_chromium)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        settings = ApiSettings(gui_container.settings)
        settings.set_port(taken.getsockname()[1])
        settings.set_enabled(True)
        win = MainWindow(gui_container)
        win.show()
        try:
            assert spin_wait(lambda: win._api is not None and win.api.error is not None)
            assert win.toasts.count() == 1                               # the user is told, once
            win.show_section(SECTION_API)
            page = win.page(SECTION_API)
            assert page._card.switch.isChecked()                              # still "on": it will try again next launch
            assert "is busy" in page._card.state.text()
            assert page._card.state.property("role") == "danger"
        finally:
            release(win)
