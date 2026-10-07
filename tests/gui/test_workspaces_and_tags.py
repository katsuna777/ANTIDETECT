"""Workspaces and tags in the window: the catalog, the sidebar lists, pickers, dialogs and the table scope."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton

from antidetect.gui.catalog import Catalog
from antidetect.gui.components import ConfirmDialog, StyledMenu
from antidetect.gui.components.tags import ALL, NONE, SOME, SwatchRow, TagField, TagPicker, tag_states
from antidetect.gui.dialogs.name_color import NameColorDialog
from antidetect.gui.dialogs.tags import TagManagerDialog
from antidetect.gui.models.rows import NO_WORKSPACE
from antidetect.gui.sidebar import SECTION_PROFILES
from antidetect.gui.theme import tags as tag_colors
from antidetect.gui.workers import TaskRunner
from tests.support.gui import make_profile, settle, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture()
def catalog(gui_container):
    runner = TaskRunner()
    cat = Catalog(gui_container, runner)
    cat.refresh()
    assert spin_wait(lambda: cat.loaded)
    yield cat
    runner.shutdown()


def _wait_catalog(cat, predicate):
    assert spin_wait(lambda: predicate(cat))


# ------------------------------------------------------------------------------ catalog


def test_the_catalog_loads_tags_workspaces_and_counters(gui_container, catalog):
    gui_container.tags.create_tag("Work", 3)
    ws = gui_container.workspaces.create_workspace("Clients", 5)
    profile = gui_container.profiles.create_profile("A", geo_auto=False, tags=["Work"], workspace_id=ws.id)
    gui_container.profiles.trash_profile(gui_container.profiles.create_profile("B", geo_auto=False).id)
    catalog.refresh()
    _wait_catalog(catalog, lambda c: c.tags and c.workspaces and c.trash == 1)
    assert [(t.name, t.color, t.count) for t in catalog.tags] == [("Work", 3, 1)]
    assert [(w.name, w.color, w.count) for w in catalog.workspaces] == [("Clients", 5, 1)]
    assert catalog.tag("work").name == "Work" and catalog.workspace(ws.id).name == "Clients"
    assert catalog.workspace(None) is None and catalog.workspace_named("clients").id == ws.id
    assert tag_colors.tag_color("Work") == tag_colors.slot_color(3)             # the table paints from the registry
    assert profile.id and catalog.unassigned == 0


def test_catalog_mutations_refresh_and_report_failures(gui_container, catalog):
    done, failed, rows = [], [], []
    catalog.profilesAffected.connect(lambda: rows.append(1))
    catalog.create_tag("one", 2, on_result=lambda t: done.append(t.name))
    assert spin_wait(lambda: done == ["one"] and [t.name for t in catalog.tags] == ["one"])
    catalog.create_tag("ONE", on_error=lambda exc: failed.append(type(exc).__name__))      # a duplicate
    assert spin_wait(lambda: failed == ["TagAlreadyExistsError"])
    catalog.recolor_tag(catalog.tags[0].id, 7)
    assert catalog.tags[0].color == 7                                                       # shown before the worker answers
    assert tag_colors.tag_color("one") == tag_colors.slot_color(7)
    catalog.rename_tag(catalog.tags[0].id, "uno")
    assert spin_wait(lambda: [t.name for t in catalog.tags] == ["uno"] and rows)           # profiles were rewritten
    catalog.delete_tag(catalog.tags[0].id)
    assert spin_wait(lambda: catalog.tags == [])


def test_workspace_mutations(gui_container, catalog):
    catalog.create_workspace("Home")
    assert spin_wait(lambda: [w.name for w in catalog.workspaces] == ["Home"])
    ws = catalog.workspaces[0]
    profile = gui_container.profiles.create_profile("P", geo_auto=False)
    catalog.move_profiles([profile.id], ws.id)
    assert spin_wait(lambda: catalog.workspaces and catalog.workspaces[0].count == 1)
    catalog.recolor_workspace(ws.id, 9)
    assert catalog.workspace(ws.id).color == 9
    catalog.rename_workspace(ws.id, "House")
    assert spin_wait(lambda: catalog.workspaces[0].name == "House")
    catalog.delete_workspace(ws.id)
    assert spin_wait(lambda: catalog.workspaces == [] and catalog.unassigned == 1)
    assert gui_container.profiles.get_profile(profile.id).workspace_id is None


# ----------------------------------------------------------------------------- sidebar


def test_the_sidebar_lists_workspaces_with_counts_and_a_row_for_the_unassigned(window, gui_container):
    ws = gui_container.workspaces.create_workspace("Clients")
    gui_container.profiles.create_profile("In", geo_auto=False, workspace_id=ws.id)
    gui_container.profiles.create_profile("Out", geo_auto=False)
    window.catalog.refresh()
    sidebar = window._sidebar
    assert spin_wait(lambda: set(sidebar._ws_rows) == {ws.id, NO_WORKSPACE})
    assert sidebar._ws_rows[ws.id].count == 1 and sidebar._ws_rows[NO_WORKSPACE].count == 1
    assert sidebar._ws_rows[ws.id].name == "Clients"


def test_clicking_a_workspace_narrows_the_table_and_clicking_profiles_leaves_it(window, gui_container):
    ws = gui_container.workspaces.create_workspace("Clients")
    make_profile(gui_container, "In")
    make_profile(gui_container, "Out")
    gui_container.workspaces.move_profiles([gui_container.profiles.list_profiles()[0].id], ws.id)
    page = settle(window, 2)
    assert spin_wait(lambda: ws.id in window._sidebar._ws_rows)
    window._sidebar._ws_rows[ws.id].click()
    assert page.workspace() == ws.id and page._filter.rowCount() == 1
    assert page._workspace_pill.isVisibleTo(page) and window._sidebar._ws_rows[ws.id].isChecked()
    window._sidebar._ws_rows[ws.id].click()                                           # again = leave
    assert page.workspace() is None and page._filter.rowCount() == 2
    page.set_workspace(NO_WORKSPACE)
    assert [r.name for r in page._model.visible_rows()] == ["Out"]
    assert page._workspace_pill._name == "No workspace"
    window._sidebar._buttons[SECTION_PROFILES].click()
    assert page.workspace() is None and not page._workspace_pill.isVisibleTo(page)


def test_a_deleted_workspace_or_tag_is_left_by_the_table(window, gui_container):
    ws = gui_container.workspaces.create_workspace("Temp")
    gui_container.tags.create_tag("temp")
    make_profile(gui_container, "P")
    page = settle(window, 1)
    assert spin_wait(lambda: window.catalog.loaded and window.catalog.workspace(ws.id) and window.catalog.tag("temp"))
    page.set_workspace(ws.id)
    page.set_tag("temp")
    window.catalog.delete_workspace(ws.id)
    window.catalog.delete_tag(window.catalog.tag("temp").id)
    assert spin_wait(lambda: page.workspace() is None and page.tag() is None)


def test_the_sections_fold_and_remember_it(window, gui_container):
    from antidetect.gui.preferences import Preferences

    sidebar = window._sidebar
    sidebar._ws_header.click()
    assert sidebar._ws_folded and not sidebar._ws_box.isVisibleTo(sidebar)
    assert Preferences(gui_container.settings).get_bool(Preferences.KEY_WORKSPACES_COLLAPSED)
    sidebar._ws_header.click()
    assert not sidebar._ws_folded


def test_a_context_menu_on_a_workspace_row_offers_edit_and_delete(window, gui_container, monkeypatch):
    ws = gui_container.workspaces.create_workspace("W")
    window.catalog.refresh()
    assert spin_wait(lambda: ws.id in window._sidebar._ws_rows)
    shown = []
    monkeypatch.setattr(StyledMenu, "exec", lambda self, pos=None: shown.append([a.text() for a in self.actions() if a.text()]))
    row = window._sidebar._ws_rows[ws.id]
    row.customContextMenuRequested.emit(QPoint(5, 5))
    assert shown == [["Edit…", "Delete workspace"]]


def test_creating_editing_and_deleting_a_workspace_through_the_dialogs(window, gui_container, monkeypatch):
    names = iter(["Clients"])

    def accept(dialog):
        if isinstance(dialog, NameColorDialog):
            dialog._name.setText(next(names, dialog._name.text()))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NameColorDialog, "exec", accept)
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window.new_workspace()
    assert spin_wait(lambda: [w.name for w in window.catalog.workspaces] == ["Clients"])
    assert window.page(SECTION_PROFILES).workspace() == window.catalog.workspaces[0].id    # it opens right away
    ws = window.catalog.workspaces[0]
    names2 = iter(["Customers"])
    monkeypatch.setattr(NameColorDialog, "exec", lambda d: (d._name.setText(next(names2)), d._swatches.set_value(8),
                                                           QDialog.DialogCode.Accepted)[2])
    window.edit_workspace(ws.id)
    assert spin_wait(lambda: window.catalog.workspaces[0].name == "Customers" and window.catalog.workspaces[0].color == 8)
    window.delete_workspace(ws.id)
    assert spin_wait(lambda: window.catalog.workspaces == [] and window.page(SECTION_PROFILES).workspace() is None)


def test_new_profiles_go_to_the_open_workspace_and_the_dialog_can_move_them(gui_container, catalog):
    from antidetect.gui.dialogs.profile import ProfileDialog

    ws = gui_container.workspaces.create_workspace("Clients")
    catalog.refresh()
    assert spin_wait(lambda: catalog.workspaces)
    dialog = ProfileDialog(gui_container, TaskRunner(), profile=None, proxies=[], existing_names=set(),
                           catalog=catalog, default_workspace=ws.id)
    assert dialog._workspace.currentData() == ws.id and dialog.spec().workspace_id == ws.id
    dialog._workspace.setCurrentIndex(0)
    assert dialog.spec().workspace_id is None
    bare = ProfileDialog(gui_container, TaskRunner(), profile=None, proxies=[], existing_names=set(),
                         catalog=Catalog(gui_container, TaskRunner()))
    assert bare._workspace is None and bare.spec().workspace_id is None                # nothing to choose from


# ------------------------------------------------------------------------------- tags UI


def test_swatches_pick_a_colour_and_say_so(qapp):
    row = SwatchRow(2, per_row=6, size=28, gap=14)
    seen = []
    row.changed.connect(seen.append)
    from PySide6.QtTest import QTest

    QTest.mouseClick(row, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row._rect(7).center().toPoint())
    assert seen == [7] and row.value() == 7
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row._rect(7).center().toPoint())
    assert seen == [7]                                                                     # the same colour: nothing new
    assert row.width() >= 6 * 28 and row.height() >= 2 * 28


def test_tag_states_say_which_tags_all_or_some_of_the_profiles_carry():
    from tests.gui.test_visual_system import _row

    a, b = _row(tags=("x", "y")), _row(tags=("x",))
    assert tag_states([a, b]) == {"x": ALL, "y": SOME}
    assert tag_states([]) == {}
    assert NONE == 0


def test_the_picker_lists_every_tag_and_reports_ticks(gui_container, catalog):
    for name in ("alpha", "beta"):
        gui_container.tags.create_tag(name)
    catalog.refresh()
    assert spin_wait(lambda: len(catalog.tags) == 2)
    picker = TagPicker(catalog, {"alpha": ALL, "beta": SOME})
    seen = []
    picker.toggled.connect(lambda name, add: seen.append((name, add)))
    assert [i[0] for i in picker.model.items] == ["alpha", "beta"]
    picker._clicked(picker.model.index(0))                      # ticked -> untick
    picker._clicked(picker.model.index(1))                      # some -> everyone
    assert seen == [("alpha", False), ("beta", True)] and picker.states == {"alpha": NONE, "beta": ALL}
    picker._search.setText("bet")
    assert [i[0] for i in picker.model.items] == ["beta"]
    picker._search.setText("zzz")
    assert picker.model.rowCount() == 0 and picker._empty.isVisibleTo(picker)
    assert "zzz" in picker._new_row.text()                      # "Create “zzz”"


def test_the_picker_creates_a_tag_with_a_colour_and_ticks_it(gui_container, catalog):
    picker = TagPicker(catalog, {})
    seen = []
    picker.toggled.connect(lambda name, add: seen.append((name, add)))
    picker._search.setText("fresh")
    picker._show_form()
    assert picker._name.text() == "fresh" and picker._form.isVisibleTo(picker)
    picker._swatches.set_value(6)
    picker._create()
    assert spin_wait(lambda: seen == [("fresh", True)] and catalog.tag("fresh"))
    assert catalog.tag("fresh").color == 6 and picker.states == {"fresh": ALL}
    picker._show_form()
    picker._name.setText("FRESH")                               # exists already: it is just ticked, no error
    picker.states["fresh"] = NONE
    picker._create()
    assert picker.states["fresh"] == ALL


def test_the_picker_shows_a_failure_inline(gui_container, catalog):
    picker = TagPicker(catalog, {})
    picker._show_form()
    picker._name.setText("   ")
    picker._create()                                            # empty: nothing happens
    assert not picker._error.isVisibleTo(picker)
    picker._failed(ValueError("nope"))
    assert picker._error.isVisibleTo(picker) and picker._create_button.isEnabled()


def test_the_tag_field_edits_a_list_with_chips(gui_container, catalog):
    gui_container.tags.create_tag("one")
    gui_container.tags.create_tag("two")
    catalog.refresh()
    assert spin_wait(lambda: len(catalog.tags) == 2)
    field = TagField(catalog)
    changes = []
    field.changed.connect(lambda: changes.append(field.tags()))
    field.set_tags(["one"])
    assert field.tags() == ["one"] and changes == []              # setting is not editing
    field._toggled("two", True)
    field._toggled("two", True)                                    # twice is once
    assert field.tags() == ["one", "two"]
    field._remove("one")
    assert field.tags() == ["two"] and changes[-1] == ["two"]
    chips = [w for w in field.findChildren(QPushButton) if w is not field._add]
    assert chips == [] or all(c.parent() is field for c in chips)


def test_the_manager_creates_renames_recolours_and_deletes(window, gui_container, monkeypatch):
    gui_container.profiles.create_profile("P", geo_auto=False, tags=["old"])
    window.catalog.refresh()
    assert spin_wait(lambda: window.catalog.tag("old"))
    dialog = TagManagerDialog(window.catalog, window)
    rows = dialog._rows
    assert spin_wait(lambda: rows.count() >= 1)
    dialog._new.setText("new")
    dialog._create()
    assert spin_wait(lambda: window.catalog.tag("new") and dialog._new.text() == "")
    dialog._create()                                               # empty again: ignored
    dialog._new.setText("NEW")
    dialog._create()
    assert spin_wait(lambda: dialog._error.isVisibleTo(dialog))   # a duplicate says so
    old = window.catalog.tag("old")
    edit = QLineEdit()
    dialog.rename(old, "older", edit)
    assert spin_wait(lambda: window.catalog.tag("older"))
    assert gui_container.profiles.list_profiles()[0].tags == ["older"]
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    dialog.remove(window.catalog.tag("older"))                     # cancelled: kept
    spin_wait(lambda: False, 150)
    assert window.catalog.tag("older")
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    dialog.remove(window.catalog.tag("older"))
    assert spin_wait(lambda: window.catalog.tag("older") is None)
    assert gui_container.profiles.list_profiles()[0].tags == []
    dialog.close()


def test_name_colour_dialog_validates_the_name(qapp):
    dialog = NameColorDialog("t", name="Keep", taken={"Keep", "Other"}, confirm="Go")
    assert dialog._ok.isEnabled() and dialog.name() == "Keep"                # its own name is not "taken"
    dialog._name.setText("other")
    assert not dialog._ok.isEnabled() and dialog._error.isVisibleTo(dialog)
    dialog._name.setText("")
    assert not dialog._ok.isEnabled() and not dialog._error.isVisibleTo(dialog)
    dialog._name.setText("  a,  b ")
    assert dialog._ok.isEnabled() and dialog.name() == "a b"
    assert NameColorDialog("t", used_colors=[0, 0, 1]).color() == 2             # the least used colour is suggested


# ---------------------------------------------------------------- tags on several profiles


def test_ticking_a_tag_for_selected_profiles_adds_it_and_unticking_removes_it(window, gui_container):
    gui_container.tags.create_tag("vip")
    make_profile(gui_container, "A")
    make_profile(gui_container, "B")
    page = settle(window, 2)
    assert spin_wait(lambda: window.catalog.tag("vip"))
    page.pick_tags(page._model.rows(), QRect(0, 0, 10, 10))
    page._picker._clicked(page._picker.model.index(0))
    assert spin_wait(lambda: all(p.tags == ["vip"] for p in gui_container.profiles.list_profiles()))
    assert spin_wait(lambda: all(r.tags == ("vip",) for r in page._model.rows()))      # the table followed
    page.pick_tags(page._model.rows(), QPoint(5, 5))
    assert page._picker.states == {"vip": ALL}
    page._picker._clicked(page._picker.model.index(0))
    assert spin_wait(lambda: all(p.tags == [] for p in gui_container.profiles.list_profiles()))


def test_moving_profiles_to_a_workspace_from_the_menu(window, gui_container):
    ws = gui_container.workspaces.create_workspace("Clients")
    make_profile(gui_container, "A")
    page = settle(window, 1)
    assert spin_wait(lambda: window.catalog.workspace(ws.id))
    menu = page.build_menu(page._model.rows())
    submenu = next(a.menu() for a in menu.actions() if a.menu() and a.text() == "Move to workspace")
    items = [a.text() for a in submenu.actions()]
    assert items == ["No workspace", "Clients"]
    assert not submenu.actions()[0].isEnabled()                      # it is in none already
    page.move_to_workspace(page._model.rows(), ws.id)
    assert spin_wait(lambda: gui_container.profiles.list_profiles()[0].workspace_id == ws.id)
    assert spin_wait(lambda: page._model.rows()[0].workspace_id == ws.id)


def test_quick_search_finds_workspaces_and_tags(window, gui_container):
    ws = gui_container.workspaces.create_workspace("Clients")
    gui_container.tags.create_tag("vip")
    window.catalog.refresh()
    assert spin_wait(lambda: window.catalog.workspace(ws.id) and window.catalog.tag("vip"))
    entries = {(e.kind, e.title) for e in window.palette_entries()}
    assert ("workspace", "Clients") in entries and ("tag", "vip") in entries
    next(e for e in window.palette_entries() if e.kind == "workspace").run()
    assert window.page(SECTION_PROFILES).workspace() == ws.id


def test_the_plus_in_a_section_header_adds_and_does_not_fold(window, qapp, monkeypatch):
    monkeypatch.setattr(NameColorDialog, "exec", lambda self: QDialog.DialogCode.Rejected)   # the window opens it
    sidebar = window._sidebar
    asked = []
    sidebar.newWorkspaceRequested.connect(lambda: asked.append("workspace"))
    sidebar.newTagRequested.connect(lambda: asked.append("tag"))
    from PySide6.QtTest import QTest

    for header, expected in ((sidebar._ws_header, "workspace"), (sidebar._tags_header, "tag")):
        rect = header._action_rect()
        QTest.mouseClick(header, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center().toPoint())
        assert asked[-1] == expected and header.expanded
    QTest.mouseClick(sidebar._ws_header, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 12))
    assert not sidebar._ws_header.expanded                                  # a click elsewhere on it folds the list
    sidebar._ws_header.click()
