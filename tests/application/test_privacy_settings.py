"""Per-profile protection switches: what is accepted, stored, copied and handed to the engine."""

from __future__ import annotations

import pytest

from antidetect.application.configuration_service import ConfigurationService
from antidetect.application.fingerprint import privacy
from antidetect.application.fingerprint.generator import ConfigurationGenerator


@pytest.fixture()
def config_service(configuration_repo) -> ConfigurationService:
    return ConfigurationService(configurations=configuration_repo, generator=ConfigurationGenerator())


def test_a_profile_that_never_chose_anything_gets_the_defaults():
    assert privacy.resolve(None) == {"webrtc": "auto", "noise_canvas": True, "noise_audio": True, "theme": "light"}
    assert privacy.resolve({}) == privacy.resolve(None)


def test_stored_choices_win_and_the_rest_stays_default():
    assert privacy.resolve({"webrtc": "block", "noise_audio": False}) == {
        "webrtc": "block", "noise_canvas": True, "noise_audio": False, "theme": "light",
    }


def test_resolving_never_trusts_a_damaged_row():
    assert privacy.resolve({"webrtc": "everything", "noise_canvas": "yes", "junk": 1}) == privacy.resolve(None)


@pytest.mark.parametrize("bad", [{"webrtc": "off"}, {"noise_canvas": 1}, {"noise_audio": "no"}, {"mystery": True}, "block", 5])
def test_validation_rejects_what_the_engine_would_not_understand(bad):
    with pytest.raises(ValueError):
        privacy.validate(bad)


def test_validation_accepts_every_documented_value():
    privacy.validate(None)
    privacy.validate({})
    for mode in privacy.WEBRTC_MODES:
        privacy.validate({"webrtc": mode, "noise_canvas": False, "noise_audio": True})


def test_the_switches_survive_a_round_trip_through_the_database(config_service):
    created = config_service.create_configuration(
        "Careful", privacy_settings={"webrtc": "block", "noise_canvas": False}
    )
    assert config_service.get_configuration(created.id).privacy_settings == {"webrtc": "block", "noise_canvas": False}

    updated = config_service.update_configuration(created.id, privacy_settings={"webrtc": "allow"})
    assert updated.privacy_settings == {"webrtc": "allow"}


def test_a_configuration_without_switches_reads_back_as_none(config_service):
    assert config_service.create_configuration("Plain").privacy_settings is None


def test_updating_something_else_leaves_the_switches_alone(config_service):
    created = config_service.create_configuration("Keep", privacy_settings={"webrtc": "block"})
    config_service.update_configuration(created.id, language="de")
    assert config_service.get_configuration(created.id).privacy_settings == {"webrtc": "block"}


def test_an_invalid_choice_is_refused_on_create_and_on_update(config_service):
    with pytest.raises(ValueError, match="webrtc"):
        config_service.create_configuration("Bad", privacy_settings={"webrtc": "maybe"})
    created = config_service.create_configuration("Fine")
    with pytest.raises(ValueError, match="unknown privacy setting"):
        config_service.update_configuration(created.id, privacy_settings={"canvas": True})
    assert config_service.get_configuration(created.id).privacy_settings is None


def test_a_duplicate_keeps_the_switches(config_service):
    created = config_service.create_configuration("Original", privacy_settings={"webrtc": "allow", "noise_audio": False})
    copy = config_service.duplicate_configuration(created.id, "Copy")
    assert copy.privacy_settings == {"webrtc": "allow", "noise_audio": False}


# ------------------------------------------------- ProfileService.set_privacy

@pytest.fixture()
def profiles(config, fake_chromium):
    from tests.conftest import build_service

    service, db = build_service(config, fake_chromium)
    yield service
    db.close()


def _stored(service, profile_id):
    profile = service.get_profile(profile_id)
    return service._configurations.get(profile.configuration_id).privacy_settings


def test_set_privacy_merges_by_default_and_replaces_on_request(profiles):
    profile = profiles.create_profile("A")
    assert profiles.set_privacy(profile.id, {"webrtc": "block"}) == {
        "webrtc": "block", "noise_canvas": True, "noise_audio": True, "theme": "light",
    }
    profiles.set_privacy(profile.id, {"noise_audio": False})
    assert _stored(profiles, profile.id) == {"webrtc": "block", "noise_audio": False}          # merged

    profiles.set_privacy(profile.id, {"noise_canvas": False}, replace=True)
    assert _stored(profiles, profile.id) == {"noise_canvas": False}                          # the rest back to default

    profiles.set_privacy(profile.id, {}, replace=True)
    assert _stored(profiles, profile.id) is None


def test_set_privacy_rejects_junk_and_changes_nothing(profiles):
    profile = profiles.create_profile("B", privacy_settings={"webrtc": "allow"})
    with pytest.raises(ValueError):
        profiles.set_privacy(profile.id, {"webrtc": "sideways"})
    assert _stored(profiles, profile.id) == {"webrtc": "allow"}


def test_a_configuration_shared_with_other_profiles_is_copied_not_changed_for_everyone(profiles):
    shared = profiles._configurations.create("Shared", platform="windows", user_agent="Mozilla/5.0 X")
    one = profiles.create_profile("One", configuration_id=shared.id)
    two = profiles.create_profile("Two", configuration_id=shared.id)

    profiles.set_privacy(one.id, {"webrtc": "block"})

    assert profiles.get_profile(one.id).configuration_id != shared.id            # One got its own copy
    assert profiles.get_profile(two.id).configuration_id == shared.id
    assert _stored(profiles, one.id) == {"webrtc": "block"}
    assert _stored(profiles, two.id) is None                                     # Two is untouched
    assert profiles._configurations.get(shared.id).privacy_settings is None


def test_set_privacy_without_changes_touches_nothing(profiles):
    profile = profiles.create_profile("C")
    before = profiles._configurations.get(profiles.get_profile(profile.id).configuration_id).updated_at
    profiles.set_privacy(profile.id, {"webrtc": "auto"})                          # the default: nothing to store
    after = profiles._configurations.get(profiles.get_profile(profile.id).configuration_id).updated_at
    assert before == after


def test_a_new_fingerprint_keeps_the_switches_of_a_dedicated_configuration(profiles):
    profile = profiles.create_profile("D", privacy_settings={"webrtc": "block", "noise_audio": False})
    profiles.regenerate_configuration(profile.id)
    assert _stored(profiles, profile.id) == {"webrtc": "block", "noise_audio": False}



# ----------------------------------------------------------- the colour scheme

def test_a_new_profile_follows_no_system_theme_and_an_old_choice_of_auto_is_kept():
    assert privacy.resolve(None)["theme"] == "light"
    assert privacy.resolve({"theme": "auto"})["theme"] == "auto"
    assert privacy.minimal({"theme": "light"}) == {}                    # the default is stored as nothing
    assert privacy.minimal({"theme": "auto"}) == {"theme": "auto"}      # leaving the default is stored
    assert privacy.minimal({"theme": "dark"}) == {"theme": "dark"}


@pytest.mark.parametrize("bad", ["blue", "", 1, None, True])
def test_only_the_three_schemes_are_accepted(bad):
    with pytest.raises(ValueError, match="theme"):
        privacy.validate({"theme": bad})
    assert privacy.resolve({"theme": bad})["theme"] == "light"            # a damaged row falls back to the default


def test_the_scheme_is_stored_changed_and_copied_like_the_other_switches(profiles):
    profile = profiles.create_profile("T", privacy_settings={"theme": "dark"})
    assert _stored(profiles, profile.id) == {"theme": "dark"}
    profiles.set_privacy(profile.id, {"theme": "auto"})
    assert _stored(profiles, profile.id) == {"theme": "auto"}
    profiles.set_privacy(profile.id, {"theme": "light"})
    assert _stored(profiles, profile.id) is None
    profiles.regenerate_configuration(profile.id)
    assert _stored(profiles, profile.id) is None
    profiles.set_privacy(profile.id, {"theme": "dark"})
    copy = profiles.duplicate_profile(profile.id)
    assert _stored(profiles, copy.id) == {"theme": "dark"}
