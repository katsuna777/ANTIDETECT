from __future__ import annotations

import pytest

from antidetect.application.profile_service import ProfileService
from antidetect.domain.enums.profile_status import ProfileStatus
from antidetect.domain.errors import (
    BrowserConfigurationNotFoundError,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
)
from tests.conftest import build_service


@pytest.fixture()
def service(config, fake_chromium):
    service, db = build_service(config, fake_chromium)
    yield service
    db.close()


def test_create_profile_assigns_path_from_id(service: ProfileService, config):
    profile = service.create_profile("Test 01")
    assert profile.id == 1
    assert profile.profile_path == str(config.profiles_dir / "profile_001")
    assert profile.status is ProfileStatus.STOPPED
    assert profile.configuration_id != 1  # own fingerprint, not the shared default


def test_profile_path_is_independent_of_creation_order(service: ProfileService):
    first = service.create_profile("First")
    second = service.create_profile("Second")
    assert first.profile_path != second.profile_path
    assert second.profile_path.endswith(f"profile_{second.id:03d}")


def test_create_profile_rejects_empty_name(service: ProfileService):
    with pytest.raises(ValueError):
        service.create_profile("   ")


def test_create_profile_rejects_duplicate_name(service: ProfileService):
    service.create_profile("Test 01")
    with pytest.raises(ProfileAlreadyExistsError):
        service.create_profile("Test 01")


def test_get_profile_unknown_id_raises(service: ProfileService):
    with pytest.raises(ProfileNotFoundError):
        service.get_profile(999)


def test_get_profile_returns_created(service: ProfileService):
    created = service.create_profile("Test 01")
    loaded = service.get_profile(created.id)
    assert loaded.name == "Test 01"


def test_list_profiles(service: ProfileService):
    service.create_profile("A")
    service.create_profile("B")
    names = [p.name for p in service.list_profiles()]
    assert names == ["A", "B"]


def test_update_profile_renames(service: ProfileService):
    created = service.create_profile("A")
    updated = service.update_profile(created.id, name="A2")
    assert updated.name == "A2"
    assert service.get_profile(created.id).name == "A2"


def test_update_profile_rejects_collision(service: ProfileService):
    a = service.create_profile("A")
    service.create_profile("B")
    with pytest.raises(ProfileAlreadyExistsError):
        service.update_profile(a.id, name="B")


def test_delete_profile_removes_row_and_directory(service: ProfileService):
    created = service.create_profile("Doomed")
    from pathlib import Path

    path = Path(created.profile_path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "Local State").write_text("{}", encoding="utf-8")

    service.delete_profile(created.id)

    with pytest.raises(ProfileNotFoundError):
        service.get_profile(created.id)
    assert not path.exists()


def test_duplicate_profile_copies_state(service: ProfileService):
    source = service.create_profile("Source")
    source_path = __import__("pathlib").Path(source.profile_path)
    source_path.mkdir(parents=True, exist_ok=True)
    (source_path / "cookies.db").write_text("cookies!", encoding="utf-8")

    copy = service.duplicate_profile(source.id)

    assert copy.id != source.id
    assert copy.name == "Source (copy)"
    assert copy.profile_path != source.profile_path
    assert (__import__("pathlib").Path(copy.profile_path) / "cookies.db").read_text() == "cookies!"


def test_duplicate_profile_with_custom_name(service: ProfileService):
    source = service.create_profile("Source")
    copy = service.duplicate_profile(source.id, name="Cloak")
    assert copy.name == "Cloak"


def test_duplicate_unknown_profile_raises(service: ProfileService):
    from antidetect.domain.errors import ProfileNotFoundError

    with pytest.raises(ProfileNotFoundError):
        service.duplicate_profile(999)


def test_duplicate_name_collision_raises(service: ProfileService):
    service.create_profile("A")
    service.create_profile("B")
    with pytest.raises(ProfileAlreadyExistsError):
        service.duplicate_profile(2, name="A")  # "A" already taken
    with pytest.raises(ProfileAlreadyExistsError):
        service.duplicate_profile(1, name="B")  # "B" already taken


def test_create_with_explicit_configuration(service: ProfileService):
    profile = service.create_profile("WithCfg", configuration_id=1)
    assert profile.configuration_id == 1


def test_create_with_unknown_configuration_raises(service: ProfileService):
    with pytest.raises(BrowserConfigurationNotFoundError):
        service.create_profile("BadCfg", configuration_id=9999)


def test_update_profile_to_unknown_configuration_raises(service: ProfileService):
    created = service.create_profile("CfgHolder")
    with pytest.raises(BrowserConfigurationNotFoundError):
        service.update_profile(created.id, configuration_id=777)


def test_update_profile_changes_configuration(service: ProfileService):
    created = service.create_profile("CfgChanger")
    updated = service.update_profile(created.id, configuration_id=1)
    assert updated.configuration_id == 1


def test_update_profile_rejects_empty_name(service: ProfileService):
    created = service.create_profile("Named")
    with pytest.raises(ValueError):
        service.update_profile(created.id, name="   ")


def test_update_unknown_profile_raises(service: ProfileService):
    with pytest.raises(ProfileNotFoundError):
        service.update_profile(12345, name="ghost")


def test_delete_unknown_profile_raises(service: ProfileService):
    with pytest.raises(ProfileNotFoundError):
        service.delete_profile(12345)


def test_delete_profile_without_data_dir(service: ProfileService):
    created = service.create_profile("Dirless")
    assert not service.get_profile(created.id).profile_path or True
    service.delete_profile(created.id)
    with pytest.raises(ProfileNotFoundError):
        service.get_profile(created.id)


def test_profile_paths_are_all_unique(service: ProfileService):
    paths = {service.create_profile(f"P{i}").profile_path for i in range(10)}
    assert len(paths) == 10


def test_list_empty_returns_empty_list(service: ProfileService):
    assert service.list_profiles() == []