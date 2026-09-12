from __future__ import annotations

import random

import pytest

from app.application.configuration_generator import (
    PLATFORMS,
    ConfigurationGenerator,
    build_user_agent,
    validate_draft,
)


def test_list_templates_covers_all_platforms():
    templates = ConfigurationGenerator().list_templates()
    assert set(templates) == {
        "windows-chrome",
        "windows-edge",
        "macos-chrome",
        "macos-edge",
        "linux-chrome",
    }
    assert set(t.split("-")[0] for t in templates) == set(PLATFORMS)


def test_generate_random_is_platform_coherent():
    for platform in PLATFORMS:
        config = ConfigurationGenerator(rng=random.Random(7)).generate_random(platform=platform)
        assert config["platform"] == platform
        ua = config["user_agent"]
        if platform == "windows":
            assert "Windows NT 10.0" in ua
        elif platform == "macos":
            assert "Macintosh" in ua
        else:
            assert "Linux x86_64" in ua

        # Locale -> language prefix corresponds to the regional pool.
        assert config["locale"].lower().startswith(config["language"].lower())
        # Screen comes from the platform's real-world pool.
        screen_choices = {
            (w, h, dpr)
            for w, h, dpr in _screens_for(platform)
        }
        assert (config["screen_width"], config["screen_height"], config["device_pixel_ratio"]) in screen_choices
        # WebGL vendor/renderer and hardware match the platform pools.
        assert config["webgl_settings"]["vendor"] in _webgl_for(platform)
        assert any(
            (cores, mem) == (config["hardware_settings"]["cores"], config["hardware_settings"]["memory_gb"])
            for cores, mem in _hardware_for(platform)
        )


def _screens_for(platform: str):
    return {
        "windows": [
            (1920, 1080, 1.0), (1920, 1080, 1.25), (1920, 1080, 1.5),
            (2560, 1440, 1.0), (2560, 1440, 1.5), (1366, 768, 1.0),
            (1600, 900, 1.0), (3840, 2160, 1.5), (3840, 2160, 2.0),
        ],
        "macos": [
            (1440, 900, 2.0), (2560, 1600, 2.0), (1728, 1117, 2.0),
            (3024, 1964, 2.0), (2560, 1440, 1.0), (2880, 1800, 2.0),
            (1920, 1200, 1.5),
        ],
        "linux": [
            (1920, 1080, 1.0), (1366, 768, 1.0), (2560, 1440, 1.0),
            (1280, 720, 1.0), (3840, 2160, 1.0),
        ],
    }[platform]


def _webgl_for(platform: str):
    return {
        "windows": {"Google Inc. (Intel)", "Google Inc. (NVIDIA)", "Google Inc. (AMD)"},
        "macos": {"Google Inc. (Apple)"},
        "linux": {"Google Inc. (Mesa)"},
    }[platform]


def _hardware_for(platform: str):
    return {
        "windows": [(4, 8), (8, 8), (8, 16), (12, 16), (16, 32), (32, 64)],
        "macos": [(8, 8), (8, 16), (10, 16), (12, 32), (12, 48)],
        "linux": [(4, 4), (4, 8), (8, 8), (8, 16), (16, 32)],
    }[platform]


def test_generate_random_all_fields_set():
    config = ConfigurationGenerator(rng=random.Random(1)).generate_random()
    assert config["user_agent"]
    assert config["screen_width"] > 0
    assert config["screen_height"] > 0
    assert config["device_pixel_ratio"] > 0
    assert config["color_depth"] in (16, 24)
    assert set(config["webgl_settings"]) >= {"vendor", "renderer", "version", "extensions"}
    assert set(config["hardware_settings"]) >= {"cores", "memory_gb", "device_memory_gb"}


def test_generate_random_deterministic_with_seed():
    a = ConfigurationGenerator(rng=random.Random(42)).generate_random()
    b = ConfigurationGenerator(rng=random.Random(42)).generate_random()
    assert a == b


def test_generate_random_different_without_seed():
    seen = set()
    for i in range(5):
        config = ConfigurationGenerator(rng=random.Random(i)).generate_random()
        seen.add(hash(config["user_agent"]))
    assert len(seen) > 1  # fixed seeds are far apart, never all-identical


def test_generate_random_rejects_unknown_platform():
    with pytest.raises(ValueError):
        ConfigurationGenerator().generate_random(platform="beos")


def test_generate_from_template_is_coherent():
    for name in ConfigurationGenerator().list_templates():
        config = ConfigurationGenerator().generate_from_template(name)
        platform = name.split("-")[0]
        assert config["platform"] == platform
        assert config["locale"].lower().startswith(config["language"].lower())
        assert config["screen_width"] > 0


def test_generate_from_template_unknown_raises():
    with pytest.raises(ValueError):
        ConfigurationGenerator().generate_from_template("temple-of-doom")


def test_build_user_agent_substitutes_version():
    assert "Chrome/123.0.0.0" in build_user_agent("chrome", "windows", "123.0.0.0")


def test_validate_draft_rejects_mismatched_screen():
    with pytest.raises(ValueError):
        validate_draft({"screen_width": 1920, "screen_height": None})
    with pytest.raises(ValueError):
        validate_draft({"screen_width": None, "screen_height": 1080})


@pytest.mark.parametrize(
    "params",
    [
        {"screen_width": -5, "screen_height": 1080},
        {"color_depth": 0},
        {"device_pixel_ratio": 0},
        {"device_pixel_ratio": -1.5},
        {"user_agent": 42},
    ],
)
def test_validate_draft_rejects_bad_values(params: dict):
    with pytest.raises(ValueError):
        validate_draft(params)