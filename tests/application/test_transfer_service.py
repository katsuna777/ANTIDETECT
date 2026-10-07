"""Exporting a profile to an archive and importing it back."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from antidetect.application import transfer_service as ts
from antidetect.domain.errors import TransferError


@pytest.fixture()
def transfer(gui_container):
    return gui_container.transfer


def _make(container, name="Shop", platform="windows", **kw):
    profile = container.profiles.create_profile(name, platform=platform, auto_config=False, **kw)
    folder = Path(profile.profile_path)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Default").mkdir(exist_ok=True)
    (folder / "Default" / "Preferences").write_text('{"intl": {"a": 1}}')
    (folder / "Default" / "Local Storage").mkdir(exist_ok=True)
    (folder / "Default" / "Local Storage" / "leveldb.log").write_text("site data")
    (folder / "Default" / "Cache").mkdir(exist_ok=True)
    (folder / "Default" / "Cache" / "f_000001").write_text("cache " * 1000)
    (folder / "Default" / "Code Cache").mkdir(exist_ok=True)
    (folder / "Default" / "Code Cache" / "js").write_text("code")
    (folder / "SingletonLock").write_text("lock")
    (folder / ".antidetect-seed").write_text("123456")
    return profile


def _names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as z:
        return set(z.namelist())


def _manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("manifest.json"))


# ------------------------------------------------------------------- export

def test_the_archive_holds_the_manifest_and_the_browsers_data_but_not_its_caches(transfer, gui_container, tmp_path):
    profile = _make(gui_container)
    out = transfer.export_profile(profile.id, tmp_path / "shop.zip")
    names = _names(out)
    assert "manifest.json" in names
    assert "data/Default/Preferences" in names and "data/Default/Local Storage/leveldb.log" in names
    assert "data/.antidetect-seed" in names
    assert not any("Cache" in n for n in names)                    # rebuilt by the browser: not worth the megabytes
    assert "data/SingletonLock" not in names                       # only means "running"


def test_the_manifest_carries_the_settings_the_fingerprint_and_the_seed(transfer, gui_container, tmp_path):
    workspace = gui_container.workspaces.create_workspace("Clients")
    profile = _make(gui_container, notes="n", tags=["eu"], start_url="https://example.com/", workspace_id=workspace.id,
                    privacy_settings={"webrtc": "block"})
    manifest = _manifest(transfer.export_profile(profile.id, tmp_path / "a.zip"))
    assert manifest["format"] == "antidetect-profile" and manifest["version"] == 1
    assert manifest["profile"] == {"name": "Shop", "notes": "n", "tags": ["eu"], "start_url": "https://example.com/",
                                   "geo_auto": True, "workspace": "Clients"}
    config = gui_container.configurations.get_configuration(profile.configuration_id)
    assert manifest["configuration"]["user_agent"] == config.user_agent
    assert manifest["configuration"]["privacy_settings"] == {"webrtc": "block"}
    assert manifest["seed"] == 123456 and manifest["proxy"] is None


def test_a_profile_that_never_ran_exports_its_settings_and_fingerprint(transfer, gui_container, tmp_path):
    profile = gui_container.profiles.create_profile("Fresh", platform="windows", auto_config=False)
    assert not Path(profile.profile_path).is_dir()                          # no folder until the first start
    out = transfer.export_profile(profile.id, tmp_path / "fresh.zip")
    assert _names(out) == {"manifest.json"}
    imported = transfer.import_profile(out, name="Fresh copy")
    before = gui_container.configurations.get_configuration(profile.configuration_id)
    after = gui_container.configurations.get_configuration(imported.configuration_id)
    assert after.user_agent == before.user_agent and after.webgl_settings == before.webgl_settings


def test_the_proxy_goes_in_only_when_asked_for(transfer, gui_container, tmp_path):
    proxy_id = gui_container.proxies.import_text("user:secret@203.0.113.5:8080").ids[0]
    profile = _make(gui_container, proxy_id=proxy_id)
    assert _manifest(transfer.export_profile(profile.id, tmp_path / "a.zip"))["proxy"] is None
    with_proxy = _manifest(transfer.export_profile(profile.id, tmp_path / "b.zip", include_proxy=True))["proxy"]
    assert with_proxy["host"] == "203.0.113.5" and with_proxy["username"] == "user" and with_proxy["password"] == "secret"


def test_exporting_into_a_folder_names_the_file_after_the_profile(transfer, gui_container, tmp_path):
    profile = _make(gui_container, name='A/B: "x"')
    out = transfer.export_profile(profile.id, tmp_path)
    assert out.parent == tmp_path and out.suffix == ".zip" and "/" not in out.name and ":" not in out.name


def test_a_running_profile_is_refused(transfer, gui_container, tmp_path, fake_chromium):
    gui_container.browser.set_chromium_path(fake_chromium)
    profile = _make(gui_container)
    gui_container.profiles.start_profile(profile.id)
    try:
        with pytest.raises(TransferError, match="Stop"):
            transfer.export_profile(profile.id, tmp_path / "a.zip")
    finally:
        gui_container.profiles.stop_profile(profile.id)


def test_no_half_written_file_is_left_when_the_export_fails(transfer, gui_container, tmp_path, monkeypatch):
    profile = _make(gui_container)
    monkeypatch.setattr(ts.zipfile.ZipFile, "writestr", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = tmp_path / "out"
    with pytest.raises(RuntimeError):
        transfer.export_profile(profile.id, out / "a.zip")
    assert list(out.iterdir()) == []                               # neither the file nor its ".part"


def test_progress_counts_the_files(transfer, gui_container, tmp_path):
    profile = _make(gui_container)
    seen = []
    transfer.export_profile(profile.id, tmp_path / "a.zip", on_progress=lambda a, b: seen.append((a, b)))
    assert seen and seen[-1][0] == seen[-1][1]


# ------------------------------------------------------------------- import

def test_an_import_recreates_the_profile_with_the_same_fingerprint_and_data(transfer, gui_container, tmp_path):
    workspace = gui_container.workspaces.create_workspace("Clients")
    original = _make(gui_container, notes="hello", tags=["eu", "shop"], workspace_id=workspace.id,
                     privacy_settings={"noise_audio": False})
    archive = transfer.export_profile(original.id, tmp_path / "a.zip")
    gui_container.profiles.delete_profile(original.id)                          # as if moved to another computer

    imported = transfer.import_profile(archive)

    assert imported.name == "Shop" and imported.notes == "hello" and sorted(imported.tags) == ["eu", "shop"]
    assert imported.workspace_id == workspace.id
    config = gui_container.configurations.get_configuration(imported.configuration_id)
    assert config.privacy_settings == {"noise_audio": False}
    folder = Path(imported.profile_path)
    assert (folder / "Default" / "Preferences").read_text() == '{"intl": {"a": 1}}'
    assert (folder / "Default" / "Local Storage" / "leveldb.log").read_text() == "site data"
    assert (folder / ".antidetect-seed").read_text() == "123456"                # same canvas / audio noise as before
    assert not (folder / "Default" / "Cache").exists()


def test_the_imported_fingerprint_is_exactly_the_exported_one(transfer, gui_container, tmp_path):
    original = _make(gui_container)
    before = gui_container.configurations.get_configuration(original.configuration_id)
    archive = transfer.export_profile(original.id, tmp_path / "a.zip")
    imported = transfer.import_profile(archive, name="Copy")
    after = gui_container.configurations.get_configuration(imported.configuration_id)
    for field in ts._CONFIGURATION_FIELDS:
        assert getattr(after, field) == getattr(before, field), field
    assert imported.configuration_id != original.configuration_id              # its own row, not shared


def test_a_taken_name_gets_imported_and_a_number_never_overwriting_anything(transfer, gui_container, tmp_path):
    original = _make(gui_container)
    archive = transfer.export_profile(original.id, tmp_path / "a.zip")
    first = transfer.import_profile(archive)
    second = transfer.import_profile(archive)
    assert first.name == "Shop (imported)" and second.name == "Shop (imported 2)"
    assert gui_container.profiles.get_profile(original.id).name == "Shop"
    assert transfer.import_profile(archive, name="Chosen").name == "Chosen"


def test_the_proxy_comes_back_with_its_login_even_with_odd_characters(transfer, gui_container, tmp_path):
    proxy_id = gui_container.proxies.import_text("socks5://u%40x:p%3Ass%40w%2Frd@203.0.113.5:1080").ids[0]
    original = _make(gui_container, proxy_id=proxy_id)
    archive = transfer.export_profile(original.id, tmp_path / "a.zip", include_proxy=True)
    gui_container.profiles.delete_profile(original.id)
    gui_container.proxies.delete_proxies([proxy_id])                          # the new computer has never seen it

    imported = transfer.import_profile(archive)
    proxy = gui_container.proxies.get_proxy(imported.proxy_id)
    assert (proxy.protocol.value, proxy.host, proxy.port) == ("SOCKS5", "203.0.113.5", 1080)
    assert (proxy.username, proxy.password) == ("u@x", "p:ss@w/rd")


def test_an_archive_without_a_proxy_gives_a_profile_without_one(transfer, gui_container, tmp_path):
    proxy_id = gui_container.proxies.import_text("203.0.113.5:8080").ids[0]
    original = _make(gui_container, proxy_id=proxy_id)
    imported = transfer.import_profile(transfer.export_profile(original.id, tmp_path / "a.zip"))
    assert imported.proxy_id is None


def test_a_missing_workspace_is_created(transfer, gui_container, tmp_path):
    workspace = gui_container.workspaces.create_workspace("Clients")
    original = _make(gui_container, workspace_id=workspace.id)
    archive = transfer.export_profile(original.id, tmp_path / "a.zip")
    gui_container.profiles.delete_profile(original.id)
    gui_container.workspaces.delete_workspace(workspace.id)
    imported = transfer.import_profile(archive)
    names = {i.workspace.name for i in gui_container.workspaces.list_workspaces()}
    assert "Clients" in names and imported.workspace_id is not None


# --------------------------------------------------------- bad and hostile files

def _zip(path: Path, entries: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return path


def _plain_file(path: Path) -> Path:
    path.write_bytes(b"not a zip")
    return path


def _good_manifest(**changes) -> str:
    manifest = {"format": "antidetect-profile", "version": 1, "profile": {"name": "X"}, "configuration": None}
    manifest.update(changes)
    return json.dumps(manifest)


@pytest.mark.parametrize(
    "build, message",
    [
        (lambda p: p / "missing.zip", "not found"),
        (lambda p: _plain_file(p / "x.zip"), "not a valid archive"),
        (lambda p: _zip(p / "x.zip", {"hello.txt": "hi"}), "no manifest"),
        (lambda p: _zip(p / "x.zip", {"manifest.json": "{broken"}), "damaged"),
        (lambda p: _zip(p / "x.zip", {"manifest.json": json.dumps({"format": "other", "version": 1})}), "not a profile archive"),
        (lambda p: _zip(p / "x.zip", {"manifest.json": _good_manifest(version=99)}), "newer version"),
        (lambda p: _zip(p / "x.zip", {"manifest.json": _good_manifest(profile={"name": " "})}), "no profile name"),
    ],
)
def test_a_file_that_is_not_one_of_ours_is_refused_with_a_reason(transfer, gui_container, tmp_path, build, message):
    with pytest.raises(TransferError, match=message):
        transfer.import_profile(build(tmp_path))
    assert gui_container.profiles.list_profiles() == []


@pytest.mark.parametrize("evil", ["data/../../escape.txt", "data//etc/passwd", "data/a/../../../escape.txt"])
def test_a_path_that_climbs_out_of_the_profile_folder_is_refused_and_nothing_is_left(transfer, gui_container, tmp_path, evil):
    archive = _zip(tmp_path / "evil.zip", {"manifest.json": _good_manifest(), "data/ok.txt": "fine", evil: "gotcha"})
    with pytest.raises(TransferError, match="unsafe path"):
        transfer.import_profile(archive)
    assert gui_container.profiles.list_profiles() == []                         # the half-made profile was removed
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path.parent / "escape.txt").exists()


def test_an_invalid_fingerprint_in_the_archive_is_refused_and_cleaned_up(transfer, gui_container, tmp_path):
    bad = _good_manifest(configuration={"platform": "windows", "screen_width": -5, "screen_height": 1080})
    with pytest.raises(TransferError, match="invalid fingerprint"):
        transfer.import_profile(_zip(tmp_path / "bad.zip", {"manifest.json": bad}))
    assert gui_container.profiles.list_profiles() == []


def test_an_archive_with_no_data_still_gives_a_working_profile(transfer, gui_container, tmp_path):
    imported = transfer.import_profile(_zip(tmp_path / "bare.zip", {"manifest.json": _good_manifest()}))
    assert imported.name == "X" and Path(imported.profile_path).is_dir()


def test_reading_the_manifest_alone_changes_nothing(transfer, gui_container, tmp_path):
    original = _make(gui_container)
    manifest = transfer.read_manifest(transfer.export_profile(original.id, tmp_path / "a.zip"))
    assert manifest["profile"]["name"] == "Shop" and len(gui_container.profiles.list_profiles()) == 1


def test_a_deleted_profile_is_reported_as_not_found(transfer):
    with pytest.raises(ProfileNotFoundError):
        transfer.export_profile(999, Path("/tmp/never.zip"))


from antidetect.domain.errors import ProfileNotFoundError  # noqa: E402
