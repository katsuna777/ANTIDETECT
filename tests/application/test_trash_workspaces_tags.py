"""Trash, workspaces, the tag registry and the activity feed (the application layer, over a real database)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from antidetect.config import AppConfig
from antidetect.container import bootstrap
from antidetect.domain.errors import (
    ProfileNotFoundError,
    TagAlreadyExistsError,
    WorkspaceAlreadyExistsError,
    WorkspaceNotFoundError,
)


@pytest.fixture()
def app(tmp_path: Path, fake_chromium: Path):
    container = bootstrap(AppConfig(data_dir=tmp_path / "data", chromium_path=fake_chromium))
    yield container
    for profile in container.profiles.list_profiles():
        if profile.status.value == "RUNNING":
            container.profiles.stop_profile(profile.id)
    container.close()


def _make(app, name="Alpha", **kw):
    return app.profiles.create_profile(name, geo_auto=False, **kw)


# ------------------------------------------------------------------------------ trash


def test_a_trashed_profile_leaves_every_list_but_keeps_its_folder(app):
    profile = _make(app)
    folder = Path(profile.profile_path)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Cookies").write_text("x")
    app.profiles.trash_profile(profile.id)
    assert app.profiles.list_profiles() == []
    assert [p.id for p in app.profiles.list_trashed_profiles()] == [profile.id]
    assert app.profiles.count_trashed() == 1
    assert (folder / "Cookies").exists()
    assert app.profiles.get_profile(profile.id, include_trashed=True).deleted_at is not None
    with pytest.raises(ProfileNotFoundError):
        app.profiles.get_profile(profile.id)
    with pytest.raises(ProfileNotFoundError):
        app.profiles.start_profile(profile.id)


def test_trashing_a_running_profile_stops_it_first(app):
    profile = _make(app)
    app.profiles.start_profile(profile.id)
    app.profiles.trash_profile(profile.id)
    stored = app.profiles.get_profile(profile.id, include_trashed=True)
    assert stored.status.value == "STOPPED" and stored.pid is None


def test_the_name_of_a_trashed_profile_can_be_used_again(app):
    first = _make(app, "Shop")
    app.profiles.trash_profile(first.id)
    second = _make(app, "Shop")
    assert second.id != first.id


def test_restore_gives_the_profile_back_and_renames_it_when_the_name_is_taken(app):
    first = _make(app, "Shop")
    app.profiles.trash_profile(first.id)
    assert app.profiles.restore_profile(first.id).name == "Shop"
    app.profiles.trash_profile(first.id)
    _make(app, "Shop")
    restored = app.profiles.restore_profile(first.id)
    assert restored.name == "Shop (2)" and restored.deleted_at is None
    assert {p.name for p in app.profiles.list_profiles()} == {"Shop", "Shop (2)"}


def test_delete_for_good_removes_folder_and_record_even_from_the_trash(app):
    profile = _make(app)
    folder = Path(profile.profile_path)
    folder.mkdir(parents=True, exist_ok=True)
    app.profiles.trash_profile(profile.id)
    app.profiles.delete_profile(profile.id)
    assert not folder.exists()
    assert app.profiles.list_trashed_profiles() == []


def test_the_fingerprint_of_a_trashed_profile_survives(app):
    profile = _make(app)
    configuration = profile.configuration_id
    app.profiles.trash_profile(profile.id)
    assert app.configurations.get_configuration(configuration) is not None


def test_empty_trash_and_retention(app):
    old, recent, alive = _make(app, "old"), _make(app, "recent"), _make(app, "alive")
    app.profiles.trash_profile(old.id)
    app.profiles.trash_profile(recent.id)
    when = (datetime.now(timezone.utc) - timedelta(days=40)).replace(tzinfo=None).isoformat(timespec="microseconds")
    app.db.execute("UPDATE profiles SET deleted_at = ? WHERE id = ?", (when, old.id))
    app.db.commit()
    assert app.profiles.trash_retention_days() == 30
    assert app.profiles.purge_expired() == 1
    assert [p.name for p in app.profiles.list_trashed_profiles()] == ["recent"]
    app.profiles.set_trash_retention_days(0)                       # 0 = keep forever
    assert app.profiles.purge_expired() == 0
    assert app.profiles.empty_trash() == 1
    assert [p.name for p in app.profiles.list_profiles()] == [alive.name]


# ------------------------------------------------------------------------------ tags


def test_tags_are_registered_with_a_colour_and_spelled_the_same_everywhere(app):
    created = app.tags.create_tag("  Work  ")
    assert created.name == "Work" and 0 <= created.color < 12
    with pytest.raises(TagAlreadyExistsError):
        app.tags.create_tag("work")
    with pytest.raises(ValueError):
        app.tags.create_tag("  , ")
    profile = _make(app, tags=["work", "Новый"])
    assert profile.tags == ["Work", "Новый"]                      # "work" became the registered "Work"
    assert [i.tag.name for i in app.tags.list_tags()] == ["Work", "Новый"]
    assert {i.tag.name: i.count for i in app.tags.list_tags()} == {"Work": 1, "Новый": 1}


def test_cyrillic_tag_names_are_unique_case_insensitively(app):
    app.tags.create_tag("Работа")
    with pytest.raises(TagAlreadyExistsError):
        app.tags.create_tag("работа")


def test_rename_rewrites_the_profiles_and_delete_strips_them(app):
    tag = app.tags.create_tag("Old")
    live, gone = _make(app, "live", tags=["Old", "keep"]), _make(app, "gone", tags=["Old"])
    app.profiles.trash_profile(gone.id)
    app.tags.rename_tag(tag.id, "New")
    assert app.profiles.get_profile(live.id).tags == ["New", "keep"]
    assert app.profiles.get_profile(gone.id, include_trashed=True).tags == ["New"]
    with pytest.raises(TagAlreadyExistsError):
        app.tags.rename_tag(tag.id, "KEEP")
    assert app.tags.delete_tag(tag.id) == 2
    assert app.profiles.get_profile(live.id).tags == ["keep"]
    assert app.profiles.get_profile(gone.id, include_trashed=True).tags == []


def test_assign_adds_and_removes_tags_on_many_profiles(app):
    a, b = _make(app, "a", tags=["x"]), _make(app, "b")
    assert app.tags.assign([a.id, b.id], add=["y", "x"], remove=[]) == 2
    assert app.profiles.get_profile(a.id).tags == ["x", "y"]
    assert app.profiles.get_profile(b.id).tags == ["y", "x"]
    assert app.tags.assign([a.id, b.id], add=[], remove=["X"]) == 2
    assert app.profiles.get_profile(a.id).tags == ["y"]
    assert app.tags.assign([a.id], add=["y"]) == 0                  # nothing to change


def test_tag_counts_ignore_the_trash(app):
    a = _make(app, "a", tags=["x"])
    _make(app, "b", tags=["x"])
    app.profiles.trash_profile(a.id)
    assert {i.tag.name: i.count for i in app.tags.list_tags()} == {"x": 1}


# ------------------------------------------------------------------------- workspaces


def test_workspaces_group_profiles(app):
    clients = app.workspaces.create_workspace("Clients")
    with pytest.raises(WorkspaceAlreadyExistsError):
        app.workspaces.create_workspace("clients")
    a = _make(app, "a", workspace_id=clients.id)
    b = _make(app, "b")
    assert {i.workspace.name: i.count for i in app.workspaces.list_workspaces()} == {"Clients": 1}
    assert app.workspaces.unassigned_count() == 1
    assert app.workspaces.move_profiles([b.id], clients.id) == 1
    assert app.profiles.get_profile(b.id).workspace_id == clients.id
    assert app.workspaces.move_profiles([a.id, b.id], None) == 2
    assert app.profiles.get_profile(a.id).workspace_id is None
    with pytest.raises(WorkspaceNotFoundError):
        app.workspaces.move_profiles([a.id], 999)
    with pytest.raises(WorkspaceNotFoundError):
        _make(app, "c", workspace_id=999)


def test_deleting_a_workspace_keeps_its_profiles(app):
    ws = app.workspaces.create_workspace("Temp")
    profile = _make(app, workspace_id=ws.id)
    assert app.workspaces.delete_workspace(ws.id) == 1
    assert app.profiles.get_profile(profile.id).workspace_id is None
    assert app.workspaces.list_workspaces() == []


def test_a_duplicate_stays_in_the_workspace_and_a_restored_profile_too(app):
    ws = app.workspaces.create_workspace("W")
    profile = _make(app, workspace_id=ws.id)
    assert app.profiles.duplicate_profile(profile.id).workspace_id == ws.id
    app.profiles.trash_profile(profile.id)
    assert app.profiles.restore_profile(profile.id).workspace_id == ws.id


def test_rename_and_recolour_a_workspace(app):
    ws = app.workspaces.create_workspace("Old", color=3)
    assert app.workspaces.rename_workspace(ws.id, "New").name == "New"
    assert app.workspaces.set_color(ws.id, 15).color == 3          # slots wrap around the palette of 12


# --------------------------------------------------------------------------- activity


def test_the_feed_records_what_happened_newest_first(app):
    profile = _make(app, "Shop")
    app.profiles.start_profile(profile.id)
    app.profiles.stop_profile(profile.id)
    app.profiles.trash_profile(profile.id)
    kinds = [e.kind for e in app.activity.list()]
    assert kinds == ["act.profile.trashed", "act.profile.stopped", "act.profile.started", "act.profile.created"]
    assert all(e.subject == "Shop" for e in app.activity.list())
    assert app.activity.list(group="profiles")[0].data["profile_id"] == profile.id


def test_a_failed_start_is_an_error_entry(app, monkeypatch):
    profile = _make(app)
    monkeypatch.setattr(app.browser, "start", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        app.profiles.start_profile(profile.id)
    errors = app.activity.list(errors_only=True)
    assert [e.kind for e in errors] == ["act.profile.start_failed"] and "boom" in errors[0].data["error"]


def test_groups_unseen_and_clear(app):
    _make(app, "p")
    app.tags.create_tag("t")
    app.workspaces.create_workspace("w")
    assert {e.kind for e in app.activity.list(group="organize")} == {"act.tag.created", "act.workspace.created"}
    assert [e.kind for e in app.activity.list(group="profiles")] == ["act.profile.created"]
    assert app.activity.unseen() == 3
    app.activity.mark_seen()
    assert app.activity.unseen() == 0
    app.tags.create_tag("t2")
    assert app.activity.unseen() == 1
    assert app.activity.clear() >= 4 and app.activity.list() == []


def test_the_feed_is_trimmed(app):
    repo = app.activity._repository
    repo.KEEP = 150
    for i in range(260):
        app.activity.record("act.proxy.deleted", count=i)
    assert len(app.activity.list(limit=1000)) <= 150 + repo._TRIM_EVERY
    assert app.activity.list(limit=1)[0].data["count"] == 259
