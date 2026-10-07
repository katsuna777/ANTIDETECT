from __future__ import annotations

import random

import pytest

from antidetect.application.fingerprint import data as fd
from antidetect.application.fingerprint.generator import (
    PLATFORMS,
    SUPPORTED_LANGUAGES,
    ConfigurationGenerator,
    build_user_agent,
    validate_draft,
)


def test_list_templates_covers_all_platforms():
    templates = ConfigurationGenerator().list_templates()
    assert set(templates) == {
        "windows-chrome",
        "windows-laptop",
        "macos-chrome",
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
        assert (
            config["hardware_settings"]["cores"],
            config["hardware_settings"]["memory_gb"],
        ) in _hardware_for(platform)


def _screens_for(platform: str):
    return {(sc.width, sc.height, sc.dpr) for sc in fd.SCREENS[platform]}


def _webgl_for(platform: str):
    return {gpu.vendor for gpu in fd.GPUS[platform]}


def _hardware_for(platform: str):
    if platform == "macos":
        return {
            (cores, ram)
            for cores_options, ram_options in fd.MAC_CHIPS.values()
            for cores in cores_options
            for ram in ram_options
        }
    return set(fd.PC_HARDWARE[platform])


def test_generate_random_all_fields_set():
    config = ConfigurationGenerator(rng=random.Random(1)).generate_random()
    assert config["user_agent"]
    assert config["screen_width"] > 0
    assert config["screen_height"] > 0
    assert config["device_pixel_ratio"] > 0
    assert config["color_depth"] == 24
    assert set(config["webgl_settings"]) >= {"vendor", "renderer", "version"}
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


def test_supported_languages_pool():
    assert "en" in SUPPORTED_LANGUAGES
    assert "de" in SUPPORTED_LANGUAGES
    assert "ru" in SUPPORTED_LANGUAGES
    assert list(SUPPORTED_LANGUAGES) == sorted(SUPPORTED_LANGUAGES)
    assert len(SUPPORTED_LANGUAGES) >= 20

# ---------------------------------------------------- display kind and WebGPU naming

def test_a_retina_mac_reports_30_bit_colour_and_every_other_display_24():
    assert fd.default_color_depth("macos", 2.0) == 30
    assert fd.default_color_depth("macos", 1.0) == 24        # an sRGB external monitor
    assert fd.default_color_depth("windows", 2.0) == 24
    assert fd.default_color_depth("linux", None) == 24
    assert fd.color_profile(30) == fd.COLOR_PROFILE_P3
    assert fd.color_profile(24) == fd.COLOR_PROFILE_SRGB
    assert fd.color_profile(None) == fd.COLOR_PROFILE_SRGB


@pytest.mark.parametrize("platform", fd.PLATFORMS)
def test_generated_colour_depth_matches_the_generated_display(platform):
    for seed in range(20):
        params = ConfigurationGenerator(random.Random(seed)).generate_random(platform=platform)
        assert params["color_depth"] == fd.default_color_depth(platform, params["device_pixel_ratio"])


def test_every_known_gpu_gets_a_webgpu_name_of_its_own_vendor():
    expected = {"NVIDIA": "nvidia", "Intel": "intel", "AMD": "amd", "Apple": "apple"}
    for platform, gpus in fd.GPUS.items():
        for gpu in gpus:
            info = fd.webgpu_info(gpu.renderer, platform)
            assert info["vendor"] in expected.values(), gpu.label
            assert info["architecture"], gpu.label
            vendor_in_webgl = next(v for key, v in expected.items() if key.lower() in gpu.renderer.lower())
            assert info["vendor"] == vendor_in_webgl, f"{gpu.label}: WebGL says {vendor_in_webgl}, WebGPU {info['vendor']}"


@pytest.mark.parametrize(
    "renderer, architecture",
    [
        ("ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002504) Direct3D11 vs_5_0 ps_5_0, D3D11)", "ampere"),
        ("ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 (0x00002786) Direct3D11 vs_5_0 ps_5_0, D3D11)", "lovelace"),
        ("ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 (0x00001F82) Direct3D11 vs_5_0 ps_5_0, D3D11)", "turing"),
        ("ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 6GB (0x00001C03) Direct3D11 vs_5_0 ps_5_0, D3D11)", "pascal"),
        ("ANGLE (AMD, AMD Radeon RX 580 Series (0x000067DF) Direct3D11 vs_5_0 ps_5_0, D3D11)", "gcn-4"),
        ("ANGLE (AMD, AMD Radeon RX 6600 (0x000073FF) Direct3D11 vs_5_0 ps_5_0, D3D11)", "rdna-2"),
        ("ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) Direct3D11 vs_5_0 ps_5_0, D3D11)", "gen-9"),
        ("ANGLE (Intel, Intel(R) UHD Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)", "gen-12lp"),
        ("ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)", "metal-3"),
    ],
)
def test_webgpu_architecture_per_card(renderer, architecture):
    assert fd.webgpu_info(renderer, None)["architecture"] == architecture


def test_an_unknown_renderer_names_nothing_rather_than_the_hosts_card():
    assert fd.webgpu_info("Something Else", "windows") == {"vendor": "", "architecture": ""}
    assert fd.webgpu_info(None, None) == {"vendor": "", "architecture": ""}
