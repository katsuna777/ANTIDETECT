"""Creating several profiles at once, and exporting / importing a profile, through the interface."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QLabel

from antidetect.application.fingerprint import data as fd
from antidetect.gui.catalog import Catalog
from antidetect.gui.dialogs.bulk import BulkDialog, proxy_lines
from antidetect.gui.dialogs.export import ExportDialog
from antidetect.gui.sidebar import SECTION_PROFILES
from antidetect.gui.workers import TaskRunner
from tests.support.gui import make_profile, settle, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")

THREE = "203.0.113.1:8080:u:p\n203.0.113.2:8080:u:p\n203.0.113.3:8080:u:p"


def _bulk_dialog(container, taken=frozenset()):
    return BulkDialog(set(taken), Catalog(container, TaskRunner()))


def _toast_text(window) -> str:
    return " | ".join(label.text() for toast in window.toasts._toasts for label in toast.findChildren(QLabel))


# ------------------------------------------------------------------ the bulk dialog

def test_the_dialog_starts_with_sensible_defaults(gui_container):
    dlg = _bulk_dialog(gui_container)
    request = dlg.request()
    assert request.name == "Profile" and request.count == 10
    assert request.platform == fd.host_platform() and request.geo_auto is True
    assert request.proxy_text == "" and request.tags == () and request.workspace_id is None
    assert dlg._create.isEnabled() and dlg._create.text() == "Create (10)"


def test_the_preview_shows_the_names_that_will_be_made_skipping_taken_ones(gui_container):
    dlg = _bulk_dialog(gui_container, taken={"Shop 1", "Shop 2"})
    dlg._name.setText("Shop")
    dlg._count.setText("2")
    assert dlg._preview.text() == "Shop 3, Shop 4"
    dlg._count.setText("20")
    assert dlg._preview.text() == "Shop 3, Shop 4 … Shop 22"
    dlg._name.setText("Acc #{n}")
    assert dlg._preview.text().startswith("Acc #1, Acc #2")


@pytest.mark.parametrize("count", ["", "0", "201"])
def test_a_bad_count_or_an_empty_name_disables_creating(gui_container, count):
    dlg = _bulk_dialog(gui_container)
    dlg._count.setText(count)
    assert not dlg._create.isEnabled() and dlg._create.text() == "Create"
    dlg._count.setText("5")
    assert dlg._create.isEnabled()
    dlg._name.setText("  ")
    assert not dlg._create.isEnabled()


def test_the_count_field_takes_only_digits_and_a_number_above_the_limit_blocks_creating(gui_container):
    from PySide6.QtTest import QTest

    dlg = _bulk_dialog(gui_container)
    dlg._count.clear()
    QTest.keyClicks(dlg._count, "1ab2")
    assert dlg._count.text() == "12" and dlg._create.isEnabled()          # letters never get in
    dlg._count.clear()
    QTest.keyClicks(dlg._count, "9x99")
    assert dlg._count.text() == "999"
    assert not dlg._create.isEnabled() and "From 1 to 200" in dlg._preview.text()
    dlg._count.setText("200")
    assert dlg._create.isEnabled()


def test_the_proxy_note_explains_what_each_profile_will_get(gui_container):
    dlg = _bulk_dialog(gui_container)
    dlg._count.setText("5")
    assert "connect the way you do" in dlg._proxy_note.text()                     # no proxies: say so

    dlg._proxies.setPlainText(THREE)
    assert "3 of 5" in dlg._proxy_note.text() and "other 2" in dlg._proxy_note.text()

    dlg._count.setText("3")
    assert "Every profile gets a proxy of its own." == dlg._proxy_note.text()

    dlg._count.setText("2")
    assert "1 spare" in dlg._proxy_note.text()


def test_a_proxy_line_that_cannot_be_read_is_reported_and_blocks_creating(gui_container):
    dlg = _bulk_dialog(gui_container)
    dlg._proxies.setPlainText("203.0.113.1:8080\nnot a proxy")
    assert "Can't read 1 line" in dlg._proxy_note.text() and not dlg._create.isEnabled()
    dlg._proxies.setPlainText("203.0.113.1:8080\n# a comment\n\n203.0.113.2:8080")
    assert dlg._create.isEnabled() and dlg.proxy_summary() == (2, 0)


def test_duplicate_proxy_lines_count_once(gui_container):
    dlg = _bulk_dialog(gui_container)
    dlg._proxies.setPlainText("203.0.113.1:8080\n203.0.113.1:8080")
    assert dlg.proxy_summary() == (1, 0)


def test_the_chosen_protocol_decides_how_bare_lines_are_read(gui_container):
    dlg = _bulk_dialog(gui_container)
    dlg._proxies.setPlainText("203.0.113.1:1080")
    dlg._protocol.button("SOCKS5").click()
    assert dlg.request().proxy_protocol == "SOCKS5"


def test_the_request_carries_everything_that_was_chosen(gui_container):
    workspace = gui_container.workspaces.create_workspace("Clients")
    cat = Catalog(gui_container, TaskRunner())
    cat.refresh()
    assert spin_wait(lambda: bool(cat.workspaces))
    dlg = BulkDialog(set(), cat, default_workspace=workspace.id)
    other = next(p for p in fd.PLATFORMS if p != fd.host_platform())
    dlg._os.buttons()[other].click()
    dlg._name.setText("  Shop   EU ")
    dlg._count.setText("7")
    dlg._proxies.setPlainText("\n" + THREE + "\n")
    dlg._geo.setChecked(False)
    request = dlg.request()
    assert (request.name, request.count, request.platform) == ("Shop EU", 7, other)
    assert request.workspace_id == workspace.id and request.geo_auto is False
    assert request.proxy_text == THREE


def test_proxy_lines_ignores_blanks_and_comments():
    assert proxy_lines("a\n\n  # c\n b \n") == ["a", "b"]


# --------------------------------------------------------------- the export dialog

def test_the_export_dialog_offers_the_proxy_only_when_there_is_one_and_never_by_default(qapp):
    without = ExportDialog("Shop", has_proxy=False)
    assert not without._proxy.isVisibleTo(without) and without.include_proxy is False

    with_proxy = ExportDialog("Shop", has_proxy=True)
    assert with_proxy._proxy.isVisibleTo(with_proxy) and with_proxy.include_proxy is False
    with_proxy._proxy.setChecked(True)
    assert with_proxy.include_proxy is True


def test_the_export_dialog_is_honest_about_cookies(qapp):
    dialog = ExportDialog("Shop", True)
    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Cookies" in text and "this computer" in text and "plain text" in text


# ---------------------------------------------------------------- on the page

def _accept(monkeypatch, cls, **fields):
    """Make a dialog run as if the user filled it in and pressed the main button."""
    def fake_exec(self):
        for name, value in fields.items():
            getattr(self, name)(value) if callable(getattr(self, name, None)) else None
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(cls, "exec", fake_exec)


def test_creating_several_profiles_from_the_page(window, gui_container, monkeypatch):
    gui_container.profiles._geo_lookup = lambda: "DE"
    page = window.page(SECTION_PROFILES)

    def fill(self):
        self._name.setText("Acc")
        self._count.setText("3")
        self._proxies.setPlainText(THREE)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkDialog, "exec", fill)
    page.bulk_create()

    assert spin_wait(lambda: len(gui_container.profiles.list_profiles()) == 3)
    settle(window, 3)
    assert [p.name for p in gui_container.profiles.list_profiles()] == ["Acc 1", "Acc 2", "Acc 3"]
    assert len({p.proxy_id for p in gui_container.profiles.list_profiles()}) == 3
    assert spin_wait(lambda: "Created 3 profiles" in _toast_text(window))
    assert spin_wait(lambda: not page._settling)                       # "Preparing…" is cleared once everything is aligned


def test_cancelling_the_bulk_dialog_creates_nothing(window, gui_container, monkeypatch):
    monkeypatch.setattr(BulkDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    window.page(SECTION_PROFILES).bulk_create()
    assert gui_container.profiles.list_profiles() == []


def test_a_partly_failed_bulk_creation_says_so(window, gui_container, monkeypatch):
    real = gui_container.profiles.create_profile

    def flaky(name, *a, **k):
        if name == "Acc 2":
            raise RuntimeError("disk full")
        return real(name, *a, **k)

    monkeypatch.setattr(gui_container.profiles, "create_profile", flaky)
    monkeypatch.setattr(BulkDialog, "exec", lambda self: (self._name.setText("Acc"), self._count.setText("3"),
                                                          self._geo.setChecked(False), QDialog.DialogCode.Accepted)[-1])
    window.page(SECTION_PROFILES).bulk_create()
    assert spin_wait(lambda: "Created 2 of 3" in _toast_text(window))
    assert "Acc 2: disk full" in _toast_text(window)


def test_exporting_then_importing_from_the_page(window, gui_container, monkeypatch, tmp_path):
    make_profile(gui_container, "Shop", notes="keep me")
    page = settle(window, 1)
    row = page._model.rows()[0]
    target = tmp_path / "out" / "shop-backup"

    monkeypatch.setattr(ExportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    page.export_profile(row)
    archive = target.with_suffix(".zip")                                 # the extension is added when it is missing
    assert spin_wait(archive.exists)
    assert spin_wait(lambda: "Exported:" in _toast_text(window))
    with zipfile.ZipFile(archive) as z:
        assert "manifest.json" in z.namelist()

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(archive), ""))
    page.import_profile()
    assert spin_wait(lambda: len(gui_container.profiles.list_profiles()) == 2)
    names = sorted(p.name for p in gui_container.profiles.list_profiles())
    assert names == ["Shop", "Shop (imported)"]
    assert spin_wait(lambda: "Imported" in _toast_text(window))


def test_cancelling_the_file_choice_does_nothing(window, gui_container, monkeypatch):
    make_profile(gui_container, "Shop")
    page = settle(window, 1)
    monkeypatch.setattr(ExportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    page.export_profile(page._model.rows()[0])
    page.import_profile()
    assert len(gui_container.profiles.list_profiles()) == 1


def test_a_file_that_is_not_an_archive_gives_a_readable_error_toast(window, gui_container, monkeypatch, tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    page = window.page(SECTION_PROFILES)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(junk), ""))
    page.import_profile()
    assert spin_wait(lambda: window.toasts.count() >= 1)
    assert "not a valid archive" in _toast_text(window)
    assert gui_container.profiles.list_profiles() == []


def test_export_is_in_the_row_menu_and_unavailable_while_the_profile_runs(window, gui_container, fake_chromium):
    gui_container.browser.set_chromium_path(fake_chromium)
    make_profile(gui_container, "Shop")
    page = settle(window, 1)

    def export_action(menu):
        return next(a for a in menu.actions() if a.text() == "Export…")

    assert export_action(page.build_menu(page._model.rows())).isEnabled()
    gui_container.profiles.start_profile(page._model.rows()[0].id)
    try:
        page.reload()
        assert spin_wait(lambda: page._model.rows()[0].running)
        assert not export_action(page.build_menu(page._model.rows())).isEnabled()
    finally:
        gui_container.profiles.stop_profile(page._model.rows()[0].id)


def test_the_more_button_and_the_palette_reach_the_new_actions(window, monkeypatch):
    page = window.page(SECTION_PROFILES)
    assert page._more.toolTip() == "More" and page._more.property("iconOnly")
    titles = {entry.title for entry in window.palette_entries()}
    assert {"Create several…", "Import a profile…"} <= titles

    called = []
    monkeypatch.setattr(type(page), "bulk_create", lambda self: called.append("bulk"))
    monkeypatch.setattr(type(page), "import_profile", lambda self: called.append("import"))
    window.bulk_create()
    window.import_profile()
    assert called == ["bulk", "import"]
