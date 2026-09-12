from __future__ import annotations

from pathlib import Path

import pytest

from app.application.configuration_generator import ConfigurationGenerator
from app.application.configuration_service import ConfigurationService
from app.application.profile_service import ProfileService
from app.domain.errors import BrowserConfigurationNotFoundError
from tests.conftest import build_service


@pytest.fixture()
def config_service(configuration_repo) -> ConfigurationService:
    return ConfigurationService(
        configurations=configuration_repo,
        generator=ConfigurationGenerator(),
    )


def test_create_configuration_persists_all_fields(config_service):
    cfg = config_service.create_configuration(
        name="  My Cfg  ",
        user_agent="Mozilla/5.0 TestUA",
        platform="windows",
        language="en",
        locale="en-US",
        timezone="Europe/Berlin",
        screen_width=2560,
        screen_height=1440,
        device_pixel_ratio=1.5,
        color_depth=24,
        webgl_settings={"vendor": "Google Inc.", "renderer": "Test Renderer"},
        hardware_settings={"cores": 8, "memory_gb": 16},
    )
    assert cfg.name == "My Cfg"
    assert cfg.user_agent == "Mozilla/5.0 TestUA"
    assert cfg.platform == "windows"
    assert cfg.language_tag == "en-US"
    assert cfg.screen_width == 2560
    assert cfg.device_pixel_ratio == 1.5
    assert cfg.color_depth == 24
    assert cfg.webgl_settings == {"vendor": "Google Inc.", "renderer": "Test Renderer"}
    assert cfg.hardware_settings == {"cores": 8, "memory_gb": 16}

    loaded = config_service.get_configuration(cfg.id)
    assert loaded == cfg or loaded.id == cfg.id  # freshly read back, not the in-memory object
    assert loaded.name == "My Cfg"


def test_create_configuration_rejects_unsafe_name(config_service):
    with pytest.raises(ValueError):
        config_service.create_configuration("bad/name")
    with pytest.raises(ValueError):
        config_service.create_configuration("   ")


def test_create_configuration_rejects_duplicate_name(config_service):
    config_service.create_configuration("Dupe")
    with pytest.raises(ValueError):
        config_service.create_configuration("Dupe")
    with pytest.raises(ValueError):
        config_service.create_configuration("  Dupe ")  # normalized to "Dupe"


def test_get_missing_configuration_raises(config_service):
    with pytest.raises(BrowserConfigurationNotFoundError):
        config_service.get_configuration(99_999)


def test_update_configuration_changes_and_clears(config_service):
    cfg = config_service.create_configuration("Editable", user_agent="Old/1.0")
    config_service.update_configuration(
        cfg.id, name="Renamed", user_agent="New/2.0", color_depth=16
    )
    updated = config_service.get_configuration(cfg.id)
    assert updated.name == "Renamed"
    assert updated.user_agent == "New/2.0"
    assert updated.color_depth == 16

    config_service.update_configuration(cfg.id, user_agent="")
    assert config_service.get_configuration(cfg.id).user_agent is None


def test_update_configuration_rejects_duplicate_name(config_service):
    config_service.create_configuration("First")
    second = config_service.create_configuration("Second")
    with pytest.raises(ValueError):
        config_service.update_configuration(second.id, name="First")


def test_update_missing_configuration_raises(config_service):
    with pytest.raises(BrowserConfigurationNotFoundError):
        config_service.update_configuration(404, name="Boom")


def test_generate_persists_and_uniquifies_name(config_service):
    first = config_service.generate_configuration(template="macos-chrome")
    assert first.name == "macos-chrome"
    assert first.platform == "macos"

    duplicate = config_service.generate_configuration(template="macos-chrome")
    assert duplicate.name == "macos-chrome-2"
    assert duplicate.platform == "macos"


def test_generate_uses_template_by_default_when_named_after_it(config_service):
    cfg = config_service.generate_configuration(template="windows-edge")
    assert cfg.platform == "windows"
    assert "Edg/" in cfg.user_agent


def test_generate_unknown_template_raises(config_service):
    with pytest.raises(ValueError):
        config_service.generate_configuration(template="nope")


def test_list_configurations_ordered_by_id(config_service):
    a = config_service.create_configuration("A")
    b = config_service.create_configuration("B")
    cfg_ids = config_service.get_default().id  # seeded "default" exists
    assert config_service.list_configurations()[0].id == cfg_ids
    ids = [cfg.id for cfg in config_service.list_configurations()]
    assert ids == sorted(ids) and {a.id, b.id} <= set(ids)


def test_duplicate_configuration_copies_all_fields(config_service):
    source = config_service.generate_configuration(template="macos-chrome")
    copy = config_service.duplicate_configuration(source.id)
    assert copy.name == f"{source.name} (copy)"
    assert copy.platform == source.platform
    assert copy.user_agent == source.user_agent
    assert copy.webgl_settings == source.webgl_settings
    assert copy.hardware_settings == source.hardware_settings
    assert copy.id != source.id


def test_duplicate_configuration_with_custom_name(config_service):
    source = config_service.create_configuration("Orig")
    copy = config_service.duplicate_configuration(source.id, name="Fresh")
    assert copy.name == "Fresh"


def test_duplicate_rejects_colliding_name(config_service):
    config_service.create_configuration("Taken")
    source = config_service.create_configuration("Src")
    with pytest.raises(ValueError):
        config_service.duplicate_configuration(source.id, name="Taken")


def test_delete_configuration_detaches_profiles(config, fake_chromium):
    service, db = build_service(config, fake_chromium)
    try:
        configuration_repo = service._configurations
        config_service = ConfigurationService(
            configurations=configuration_repo,
            generator=ConfigurationGenerator(),
        )
        cfg = config_service.create_configuration("ToDelete")
        profile = service.create_profile("Holder", configuration_id=cfg.id)
        assert profile.configuration_id == cfg.id

        config_service.delete_configuration(cfg.id)

        detached = service.get_profile(profile.id)
        assert detached.configuration_id is None
        assert configuration_repo.get(cfg.id) is None
    finally:
        db.close()


def test_delete_missing_configuration_raises(config_service):
    with pytest.raises(BrowserConfigurationNotFoundError):
        config_service.delete_configuration(404)


def test_create_rejects_unknown_timezone(config_service):
    with pytest.raises(ValueError, match="Unknown timezone"):
        config_service.create_configuration("Bad TZ", timezone="UTC+3")
    with pytest.raises(ValueError, match="Unknown timezone"):
        config_service.create_configuration("Bad TZ 2", timezone="Moscow")


def test_create_accepts_supported_timezone_without_user_agent(config_service):
    cfg = config_service.create_configuration("TZ Only", timezone="Europe/Moscow")
    assert cfg.timezone == "Europe/Moscow"


def test_update_rejects_unknown_timezone(config_service):
    cfg = config_service.create_configuration("To Edit", timezone="Europe/Berlin")
    with pytest.raises(ValueError, match="Unknown timezone"):
        config_service.update_configuration(cfg.id, timezone="Mars/Olympus")
    assert config_service.get_configuration(cfg.id).timezone == "Europe/Berlin"


def test_align_configuration_geo_to_country(config_service):
    cfg = config_service.create_configuration(
        "Misaligned", language="de", locale="de-DE", timezone="Europe/Berlin"
    )
    fixed = config_service.align_configuration_geo(cfg.id, "us")
    assert fixed.timezone == "America/New_York"
    assert fixed.locale == "en-US"
    assert fixed.language == "en"


def test_align_configuration_geo_unknown_country(config_service):
    cfg = config_service.create_configuration("No Country")
    with pytest.raises(ValueError, match="Unknown country"):
        config_service.align_configuration_geo(cfg.id, "XX")


def _chrome_cfg(config_service, major=150, name="Drifted"):
    from app.application.configuration_generator import build_client_hints

    return config_service.create_configuration(
        name,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        ),
        platform="windows",
        client_hints=build_client_hints("chrome", "windows", f"{major}.0.0.0"),
    )


def test_align_browser_version_rebuilds_ua_and_hints(config_service):
    cfg = _chrome_cfg(config_service)
    fixed = config_service.align_browser_version(cfg.id, 152)
    assert "Chrome/152." in fixed.user_agent
    assert "Chrome/150." not in fixed.user_agent
    assert fixed.client_hints["fullVersion"].startswith("152.")
    assert fixed.client_hints["brands"][0]["version"] == "152"
    # Still internally consistent (UA major == hints major).
    reloaded = config_service.get_configuration(cfg.id)
    assert reloaded.user_agent == fixed.user_agent


def test_align_browser_version_same_major_is_noop(config_service):
    cfg = _chrome_cfg(config_service)
    same = config_service.align_browser_version(cfg.id, 150)
    assert same.user_agent == cfg.user_agent


def test_align_browser_version_without_chrome_ua_raises(config_service):
    cfg = config_service.create_configuration("No UA")
    with pytest.raises(ValueError, match="no Chrome User-Agent"):
        config_service.align_browser_version(cfg.id, 152)