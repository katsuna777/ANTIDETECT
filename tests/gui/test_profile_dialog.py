"""Profile dialog (tabs, validation, spec) and the proxy import dialog."""

from __future__ import annotations

import pytest

from antidetect.application.fingerprint import data as fd
from antidetect.gui.catalog import Catalog
from antidetect.gui.dialogs.profile import TAB_FINGERPRINT, TAB_GENERAL, TAB_PROXY, ProfileDialog, next_profile_name
from antidetect.gui.dialogs.proxy_import import ProxyImportDialog
from antidetect.gui.workers import TaskRunner, tasks
from tests.support.gui import make_profile

pytestmark = pytest.mark.usefixtures("qapp")


def _dialog(container, **kw):
    kw.setdefault("profile", None)
    kw.setdefault("proxies", [])
    kw.setdefault("existing_names", set())
    runner = TaskRunner()
    kw.setdefault("catalog", Catalog(container, runner))
    return ProfileDialog(container, runner, **kw)


def test_new_profile_dialog_defaults_and_validation(gui_container):
    dlg = _dialog(gui_container, existing_names={"Profile 1", "Taken"})
    assert dlg._name.text() == "Profile 2" == next_profile_name({"Profile 1"})
    assert next_profile_name(set()) == "Profile 1"
    assert dlg._platform == fd.host_platform() and dlg._os_buttons[fd.host_platform()].isChecked()
    assert dlg._create_start.isEnabled()
    dlg._name.setText("")
    assert not dlg._create.isEnabled() and not dlg._name_error.isHidden()
    assert dlg._tabs.bar.button(TAB_GENERAL).property("invalid") is True  # the tab itself is flagged
    dlg._name.setText("taken")  # case-insensitive duplicate
    assert not dlg._create_start.isEnabled() and "already exists" in dlg._name_error.text()
    dlg._name.setText("Fresh")
    assert dlg._create.isEnabled() and dlg._name_error.isHidden()
    assert dlg._tabs.bar.button(TAB_GENERAL).property("invalid") is False


def test_a_new_profile_has_no_fingerprint_tab_but_an_edited_one_does(gui_container):
    assert TAB_FINGERPRINT not in _dialog(gui_container)._tabs.bar.buttons()
    make_profile(gui_container, "Existing")
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=data["proxies"], existing_names=data["names"],
                  configuration=data["configuration"])
    assert TAB_FINGERPRINT in dlg._tabs.bar.buttons()


def test_os_hint_distinguishes_native_from_other(gui_container):
    dlg = _dialog(gui_container)
    host = fd.host_platform()
    other = next(p for p in fd.PLATFORMS if p != host)
    assert "most natural" in dlg._os_hint._text.text() and dlg._os_hint.property("tone") == "accent"
    dlg._os_buttons[other].click()
    assert "strict checkers" in dlg._os_hint._text.text() and dlg._os_hint.property("tone") == "warning"
    dlg._os_buttons[host].click()
    assert dlg._os_hint.property("tone") == "accent"


def test_proxy_mode_reveals_the_paste_area_and_validates_it(gui_container):
    dlg = _dialog(gui_container)
    assert dlg._proxy_new.isHidden()
    dlg._proxy_combo.setCurrentIndex(dlg._proxy_combo.findData("new"))
    assert not dlg._proxy_new.isHidden()
    dlg._proxy_text.setPlainText("garbage")
    assert not dlg._create_start.isEnabled()
    assert dlg._tabs.bar.button(TAB_PROXY).property("invalid") is True
    dlg._proxy_text.setPlainText("203.0.113.9:8080:user:pw")
    assert dlg._create_start.isEnabled()
    assert dlg._tabs.bar.button(TAB_PROXY).property("invalid") is False
    spec = dlg.spec()
    assert spec.proxy_text == "203.0.113.9:8080:user:pw" and spec.proxy_id is None and spec.proxy_protocol == "HTTP"
    dlg._protocol.button("SOCKS5").click()
    assert dlg.spec().proxy_protocol == "SOCKS5"


def _proxy_row(proxy_id, source):
    from antidetect.gui.models import ProxyRow

    return ProxyRow(id=proxy_id, protocol="HTTP", host=f"203.0.113.{proxy_id}", port=80, username=None,
                    country_code="DE", country="Germany", latency_ms=90, status="WORKING", anonymity="ELITE",
                    source=source, used_by=(), checked_at=None)


def test_choosing_a_free_proxy_shows_the_warning_and_tags_it(gui_container):
    dlg = _dialog(gui_container, proxies=[_proxy_row(1, "manual"), _proxy_row(2, "free-list")])
    combo = dlg._proxy_combo
    assert dlg._free_notice.isHidden()
    assert combo.itemText(combo.findData(1)).endswith("Germany")
    assert combo.itemText(combo.findData(2)).endswith("free")  # tagged right in the list
    combo.setCurrentIndex(combo.findData(2))
    assert not dlg._free_notice.isHidden()
    combo.setCurrentIndex(combo.findData(1))  # the user's own proxy: no warning
    assert dlg._free_notice.isHidden()
    combo.setCurrentIndex(combo.findData("new"))
    assert dlg._free_notice.isHidden()


def test_editing_a_profile_that_already_uses_a_free_proxy_warns_at_once(gui_container):
    from antidetect.domain.enums.proxy_status import ProxyProtocol
    from antidetect.domain.models.proxy_entry import ProxyEntry

    gui_container.proxies._proxies.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host="203.0.113.50", port=80, source="free-list")]
    )
    free_id = tasks.list_proxies(gui_container).rows[0].id
    make_profile(gui_container, "Uses free", proxy_id=free_id)
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=data["proxies"], existing_names=data["names"],
                  configuration=data["configuration"])
    assert not dlg._free_notice.isHidden()


def test_dialog_spec_collects_everything(gui_container):
    dlg = _dialog(gui_container)
    other = next(p for p in fd.PLATFORMS if p != fd.host_platform())
    dlg._name.setText("  My profile ")
    dlg._os_buttons[other].click()
    dlg._geo.setChecked(False)
    dlg._tags.set_tags(["a", "b"])
    dlg._notes.setPlainText("hello")
    dlg._start_url.setText("https://x.test/")
    spec = dlg.spec()
    assert (spec.name, spec.platform, spec.geo_auto) == ("My profile", other, False)
    assert spec.tags == ["a", "b"] and spec.notes == "hello" and spec.start_url == "https://x.test/"
    assert spec.regenerate is False and spec.fingerprint == {}


def test_saved_proxy_choice_and_create_vs_start_buttons(gui_container):
    tasks.import_proxies(gui_container, "198.51.100.1:80", "HTTP", False)(lambda *a: None)
    proxies = tasks.build_proxy_rows(gui_container)
    dlg = _dialog(gui_container, proxies=proxies)
    index = dlg._proxy_combo.findData(proxies[0].id)
    assert index >= 2
    dlg._proxy_combo.setCurrentIndex(index)
    assert dlg.spec().proxy_id == proxies[0].id
    dlg._create_start.click()
    assert dlg.start_after is True and dlg.result() == dlg.DialogCode.Accepted
    other = _dialog(gui_container)
    other._create.click()
    assert other.start_after is False


def test_edit_dialog_prefills_and_reports_changes(gui_container):
    make_profile(gui_container, "Existing", notes="old note", tags=["t1"])
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=data["proxies"], existing_names=data["names"],
                  configuration=data["configuration"])
    assert dlg._name.text() == "Existing" and dlg._notes.toPlainText() == "old note"
    assert dlg._tags.tags() == ["t1"] and dlg._platform == "windows"
    assert dlg._save.isEnabled()  # its own name is not a duplicate
    dlg._geo.setChecked(False)
    region = dlg._fp_widgets["region"]
    region.setCurrentIndex(region.findData("DE"))
    dlg._fp_widgets["cores"].setCurrentIndex(dlg._fp_widgets["cores"].findData(12))
    changes = dlg.spec().fingerprint
    assert changes["timezone"] == "Europe/Berlin" and changes["locale"] == "de-DE"
    assert changes["hardware_settings"]["cores"] == 12
    dlg._regen_btn.click()
    assert dlg.spec().regenerate is True and dlg.spec().fingerprint == {}
    assert not dlg._regen_note.isHidden()


def test_edit_dialog_system_change_requests_a_new_fingerprint(gui_container):
    make_profile(gui_container, "Sys")
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=[], existing_names=data["names"],
                  configuration=data["configuration"])
    dlg._os_buttons["linux"].click()
    assert dlg.spec().platform == "linux" and dlg.spec().regenerate is True


def test_proxy_import_dialog_counts_and_enables_add(qapp):
    dlg = ProxyImportDialog()
    assert not dlg._add.isEnabled()
    dlg._text.setPlainText("1.1.1.1:80\n2.2.2.2:80:u:p\nnonsense\n# comment")
    assert "2 ready" in dlg._preview.text() and "1 can't be read" in dlg._preview.text()
    assert dlg._add.isEnabled() and dlg.check_after() is True and dlg.protocol() == "HTTP"
    dlg._protocol.button("SOCKS5").click()
    dlg._check.setChecked(False)
    assert dlg.protocol() == "SOCKS5" and dlg.check_after() is False
    dlg._text.setPlainText("nonsense")
    assert not dlg._add.isEnabled()


def test_editing_a_profile_that_has_a_proxy_opens_cleanly_and_preselects_it(gui_container):
    """Regression: preselecting the proxy fired a signal while the tabs were still being built
    (KeyError: 'proxy' in the console, dialog still opened)."""
    tasks.import_proxies(gui_container, "198.51.100.7:80", "HTTP", False)(lambda *a: None)
    proxy = tasks.build_proxy_rows(gui_container)[0]
    make_profile(gui_container, "WithProxy", proxy_id=proxy.id)
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=data["proxies"], existing_names=data["names"],
                  configuration=data["configuration"])
    assert dlg._proxy_combo.currentData() == proxy.id and dlg.spec().proxy_id == proxy.id
    assert dlg._save.isEnabled() and dlg._proxy_new.isHidden()
    assert dlg._tabs.bar.button(TAB_PROXY).property("invalid") in (None, False)


def test_a_signal_during_construction_is_harmless(gui_container):
    dlg = _dialog(gui_container)
    del dlg._primary          # the state the dialog is in while it is being assembled
    dlg._validate()           # must not raise
    dlg._flag_tab("no-such-tab", True)


def test_every_tab_scrolls_instead_of_squeezing_and_all_have_one_height(gui_container):
    from PySide6.QtWidgets import QScrollArea

    make_profile(gui_container, "Existing")
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=data["proxies"], existing_names=data["names"],
                  configuration=data["configuration"])
    pages = [dlg._tabs.stack.widget(i) for i in range(dlg._tabs.stack.count())]
    assert len(pages) == 4 and all(isinstance(p, QScrollArea) for p in pages)
    assert dlg._tabs.minimumHeight() == dlg._tabs.maximumHeight()                # the dialog does not jump between tabs
    dlg.show()
    for key in (TAB_GENERAL, TAB_PROXY, TAB_FINGERPRINT, "notes"):
        dlg._tabs.set_current(key)
        page = dlg._tabs.stack.currentWidget().widget()
        assert page.height() >= page.minimumSizeHint().height()                  # never squeezed below what it needs


def test_the_header_shows_the_profile_and_follows_the_name(gui_container):
    make_profile(gui_container, "Existing")
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=[], existing_names=data["names"],
                  configuration=data["configuration"])
    assert "Chrome" in dlg.subtitle_label.text() and dlg._badge._name == "Existing"
    dlg._name.setText("Zed")
    assert dlg._badge._name == "Zed"


def test_the_gap_before_the_proxy_notice_exists_only_while_it_is_shown(gui_container):
    dlg = _dialog(gui_container, proxies=[_proxy_row(1, "manual"), _proxy_row(2, "free-list")])
    combo = dlg._proxy_combo
    assert dlg._free_gap.isHidden() and dlg._new_gap.isHidden()
    combo.setCurrentIndex(combo.findData(2))
    assert not dlg._free_gap.isHidden() and not dlg._free_notice.isHidden()
    combo.setCurrentIndex(combo.findData("new"))
    assert dlg._free_gap.isHidden() and not dlg._new_gap.isHidden()


def test_a_proxy_that_is_not_in_the_list_is_kept_when_editing(gui_container):
    """A profile's proxy may be missing from the list (it stopped working): choosing "no proxy" silently would drop it."""
    tasks.import_proxies(gui_container, "198.51.100.7:80", "HTTP", False)(lambda *a: None)
    proxy = tasks.build_proxy_rows(gui_container)[0]
    make_profile(gui_container, "WithProxy", proxy_id=proxy.id)
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    dlg = _dialog(gui_container, profile=row, proxies=[], existing_names=data["names"],
                  configuration=data["configuration"])
    assert dlg._proxy_combo.currentData() == proxy.id and dlg.spec().proxy_id == proxy.id


# ------------------------------------------------------------ protection switches

def _edit_dialog(gui_container, name="Protect"):
    make_profile(gui_container, name)
    row = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row.id)(lambda *a: None)
    return row, _dialog(gui_container, profile=row, proxies=[], existing_names=data["names"],
                        configuration=data["configuration"])


def test_a_new_profile_offers_webrtc_but_not_the_noise_switches(gui_container):
    dlg = _dialog(gui_container)
    assert dlg._webrtc.currentData() == "auto"
    assert dlg._noise_canvas is None and dlg._noise_audio is None      # they live on the edit-only fingerprint tab
    assert dlg.spec().privacy is None                                  # nothing chosen: nothing to store
    assert "proxy" in dlg._webrtc_hint.text().lower()


def test_the_webrtc_hint_explains_the_chosen_mode(gui_container):
    dlg = _dialog(gui_container)
    hints = set()
    for mode in ("auto", "block", "allow"):
        dlg._webrtc.select_data(mode)
        hints.add(dlg._webrtc_hint.text())
    assert len(hints) == 3
    assert "calls work" in dlg._webrtc_hint.text().lower() and "real address" in dlg._webrtc_hint.text()


def test_a_new_profile_remembers_the_webrtc_mode_chosen_before_creating_it(gui_container):
    dlg = _dialog(gui_container)
    dlg._webrtc.select_data("block")
    spec = dlg.spec()
    assert spec.privacy == {"webrtc": "block"}

    created = tasks.create_profile(gui_container, spec)(lambda *a: None)
    config = gui_container.configurations.get_configuration(created.configuration_id)
    assert config.privacy_settings == {"webrtc": "block"}


def test_the_edit_dialog_shows_what_is_stored_and_reports_only_a_difference(gui_container):
    row, dlg = _edit_dialog(gui_container)
    assert dlg._webrtc.currentData() == "auto"
    assert dlg._noise_canvas.isChecked() and dlg._noise_audio.isChecked()
    assert dlg.spec().privacy is None                                  # untouched: no needless rewrite

    dlg._noise_audio.setChecked(False)
    dlg._webrtc.select_data("allow")
    assert dlg.spec().privacy == {"webrtc": "allow", "noise_audio": False}


def test_saving_the_switches_changes_the_stored_configuration_and_putting_them_back_clears_it(gui_container):
    row, dlg = _edit_dialog(gui_container)
    dlg._noise_canvas.setChecked(False)
    spec = dlg.spec()
    tasks.update_profile(gui_container, row.id, spec, row)(lambda *a: None)
    profile = gui_container.profiles.get_profile(row.id)
    config = gui_container.configurations.get_configuration(profile.configuration_id)
    assert config.privacy_settings == {"noise_canvas": False}

    row2 = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row2.id)(lambda *a: None)
    again = _dialog(gui_container, profile=row2, proxies=[], existing_names=data["names"], configuration=data["configuration"])
    assert not again._noise_canvas.isChecked()                         # what was saved is what is shown
    again._noise_canvas.setChecked(True)
    assert again.spec().privacy == {}                                  # back to the defaults: stored as nothing
    tasks.update_profile(gui_container, row2.id, again.spec(), row2)(lambda *a: None)
    config = gui_container.configurations.get_configuration(profile.configuration_id)
    assert config.privacy_settings is None


def test_a_new_fingerprint_keeps_the_switches_and_they_can_change_in_the_same_save(gui_container):
    row, dlg = _edit_dialog(gui_container)
    dlg._noise_audio.setChecked(False)
    dlg._regen_btn.click()
    spec = dlg.spec()
    assert spec.regenerate is True and spec.privacy == {"noise_audio": False}
    tasks.update_profile(gui_container, row.id, spec, row)(lambda *a: None)
    config = gui_container.configurations.get_configuration(gui_container.profiles.get_profile(row.id).configuration_id)
    assert config.privacy_settings == {"noise_audio": False}



def test_the_edit_dialog_offers_the_colour_scheme_and_a_profile_made_before_follows_the_system(gui_container):
    row, dlg = _edit_dialog(gui_container)
    assert [dlg._theme.itemData(i) for i in range(dlg._theme.count())] == ["light", "dark", "auto"]
    assert dlg._theme.currentData() == "light" and dlg.spec().privacy is None      # a new profile: the default, nothing to save
    dlg._theme.select_data("dark")
    assert dlg.spec().privacy == {"theme": "dark"}


def test_saving_the_colour_scheme_and_reopening_shows_it(gui_container):
    row, dlg = _edit_dialog(gui_container)
    dlg._theme.select_data("auto")
    tasks.update_profile(gui_container, row.id, dlg.spec(), row)(lambda *a: None)
    row2 = tasks.build_profile_rows(gui_container)[0]
    data = tasks.load_dialog_data(gui_container, row2.id)(lambda *a: None)
    again = _dialog(gui_container, profile=row2, proxies=[], existing_names=data["names"], configuration=data["configuration"])
    assert again._theme.currentData() == "auto" and again.spec().privacy is None
    again._theme.select_data("light")
    assert again.spec().privacy == {}                                               # back to the default: stored as nothing
