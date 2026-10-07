"""StealthSpec: a stored configuration resolved against the real browser."""

from __future__ import annotations

import json
import random


from antidetect.application.fingerprint import data as fd
from antidetect.application.fingerprint.generator import ConfigurationGenerator
from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.infrastructure.stealth.payload import build_payload
from antidetect.infrastructure.stealth.spec import spec_from_configuration

BINARY = "154.0.8037.93"


def _config(platform="windows", seed=7, **overrides) -> BrowserConfiguration:
    params = ConfigurationGenerator(random.Random(seed)).generate_random(platform=platform)
    params.update(overrides)
    return BrowserConfiguration(id=1, name="t", **params)


def _host_other_than(platform: str) -> str:
    return next(p for p in fd.PLATFORMS if p != platform)


def test_ua_version_always_follows_the_installed_browser():
    # Stored UA says an old Chrome; the launch UA must match the binary.
    cfg = _config(user_agent=_config().user_agent.replace("Chrome/154", "Chrome/140"))
    spec = spec_from_configuration(cfg, browser_version=BINARY, seed=1)
    assert "Chrome/154.0.0.0" in spec.user_agent
    assert spec.ua_metadata["fullVersion"] == BINARY
    assert {"brand": "Google Chrome", "version": "154"} in spec.ua_metadata["brands"]


def test_navigator_platform_and_ua_metadata_per_os():
    for platform, nav, hints in (
        ("windows", "Win32", "Windows"),
        ("macos", "MacIntel", "macOS"),
        ("linux", "Linux x86_64", "Linux"),
    ):
        spec = spec_from_configuration(_config(platform), browser_version=BINARY, seed=2)
        assert spec.nav_platform == nav
        assert spec.ua_metadata["platform"] == hints
        assert spec.platform_key == platform


def test_languages_have_no_quality_values_and_match_accept_language():
    cfg = _config(language="es", locale="es-ES")
    spec = spec_from_configuration(cfg, browser_version=BINARY, seed=3)
    assert spec.languages == ("es-ES", "es")
    assert spec.accept_language == "es-ES,es"
    assert spec.locale == "es-ES"


def test_screen_carries_os_insets_and_dpr():
    cfg = _config("windows", screen_width=1536, screen_height=864, device_pixel_ratio=1.25)
    spec = spec_from_configuration(cfg, browser_version=BINARY, seed=4)
    assert (spec.screen.width, spec.screen.height, spec.screen.dpr) == (1536, 864, 1.25)
    assert spec.screen.avail_height == 864 - 40
    mac = spec_from_configuration(
        _config("macos", screen_width=1512, screen_height=982, device_pixel_ratio=2.0),
        browser_version=BINARY, seed=4,
    )
    assert mac.screen.avail_top == 38


def test_webgl_tables_only_attached_when_backend_differs_from_host():
    for platform in fd.PLATFORMS:
        host = _host_other_than(platform)
        spec = spec_from_configuration(_config(platform), browser_version=BINARY, seed=5, host_platform=host)
        assert spec.webgl["params"] and spec.webgl["extensions"]
        same = spec_from_configuration(_config(platform), browser_version=BINARY, seed=5, host_platform=platform)
        # Same backend as the host: only the vendor/renderer strings are replaced.
        assert "params" not in same.webgl and "extensions" not in same.webgl
        assert same.webgl["renderer"] == _config(platform).webgl_settings["renderer"]


def test_font_masking_is_experimental_and_off_by_default(monkeypatch):
    """IPHey rates a masked cross-OS profile worse than an unmasked one (measured)."""
    monkeypatch.delenv("ANTIDETECT_MASK_FONTS", raising=False)
    cross = spec_from_configuration(_config("windows"), browser_version=BINARY, seed=6, host_platform="macos")
    assert cross.font_mask is None
    assert "fonts" not in cross.js_config()


def test_font_mask_when_explicitly_requested_only_for_another_os():
    cross = spec_from_configuration(_config("windows"), browser_version=BINARY, seed=6, host_platform="macos", mask_fonts=True)
    assert cross.font_mask and "hide" in cross.font_mask and "fonts" in cross.js_config()
    same = spec_from_configuration(_config("windows"), browser_version=BINARY, seed=6, host_platform="windows", mask_fonts=True)
    assert same.font_mask is None


def test_env_switch_enables_font_masking(monkeypatch):
    monkeypatch.setenv("ANTIDETECT_MASK_FONTS", "1")
    spec = spec_from_configuration(_config("windows"), browser_version=BINARY, seed=6, host_platform="macos")
    assert spec.font_mask is not None


def test_seed_and_token_are_stable_and_distinct_per_profile():
    cfg = _config()
    a = spec_from_configuration(cfg, browser_version=BINARY, seed=111)
    b = spec_from_configuration(cfg, browser_version=BINARY, seed=111)
    c = spec_from_configuration(cfg, browser_version=BINARY, seed=222)
    assert (a.seed, a.token) == (b.seed, b.token)
    assert a.seed != c.seed and a.token != c.token


def test_geolocation_follows_timezone():
    spec = spec_from_configuration(_config(timezone="Europe/Berlin"), browser_version=BINARY, seed=8)
    lat, lon = spec.geolocation
    assert abs(lat - 52.52) < 0.1 and abs(lon - 13.405) < 0.1
    assert spec_from_configuration(_config(timezone=None), browser_version=BINARY, seed=8).geolocation is None


def test_bare_configuration_leaves_ua_native_but_keeps_noise():
    spec = spec_from_configuration(BrowserConfiguration(id=1, name="bare"), browser_version=BINARY, seed=9)
    assert spec.user_agent is None and spec.ua_metadata is None and spec.nav_platform is None
    assert spec.noise_canvas and spec.noise_audio
    assert spec.noise_webgl is False  # readPixels noise is off by default (flagged as masking)


def test_js_payload_is_self_contained_and_valid_json_config():
    spec = spec_from_configuration(_config(), browser_version=BINARY, seed=10, host_platform="macos", mask_fonts=True)
    script = build_payload(spec)
    assert "__CFG__" not in script and "__TOKEN__" not in script
    assert script.rstrip().endswith(f"//# sourceURL={spec.token}")
    # The embedded config literal must be valid JSON carrying the per-profile seed.
    start = script.rindex("})(") + 3
    end = script.rindex(");\n//# sourceURL")
    cfg = json.loads(script[start:end])
    assert cfg["seed"] == spec.seed and cfg["token"] == spec.token
    assert cfg["uaData"]["platform"] == "Windows"
    assert cfg["fonts"]["hide"]


def test_payload_never_patches_function_to_string_proxy_style():
    """Regression guard for the two ways detectors catch JS stealth."""
    spec = spec_from_configuration(_config(), browser_version=BINARY, seed=11)
    script = build_payload(spec)
    assert "new Proxy" not in script and "_Proxy" not in script  # Proxy wrappers are detectable
    assert "chrome.runtime" not in script  # faking it is itself a tell
    assert "defineProperty(navigator" not in script  # instance-level patches are detectable


# ------------------------------------------------ display depth and the WebGPU adapter

def test_payload_config_names_the_same_gpu_for_webgpu_as_for_webgl():
    for platform in fd.PLATFORMS:
        spec = spec_from_configuration(_config(platform), browser_version=BINARY, seed=5, host_platform="macos")
        webgl = spec.js_config()["webgl"]
        assert webgl["gpu"] == fd.webgpu_info(webgl["renderer"], platform)
        assert webgl["gpu"]["vendor"] in webgl["renderer"].lower() or platform == "macos"


def test_screen_carries_the_colour_depth_and_derives_the_colour_profile():
    windows = spec_from_configuration(_config("windows", color_depth=24), browser_version=BINARY, seed=6)
    assert windows.screen.color_depth == 24 and windows.screen.color_profile == "srgb"
    assert windows.js_config()["screen"]["colorDepth"] == 24

    mac = spec_from_configuration(
        _config("macos", color_depth=30, device_pixel_ratio=2.0), browser_version=BINARY, seed=6
    )
    assert mac.screen.color_depth == 30 and mac.screen.color_profile == "display-p3-d65"
    assert mac.js_config()["screen"]["colorDepth"] == 30


def test_a_configuration_without_colour_depth_is_treated_as_24():
    spec = spec_from_configuration(_config("windows", color_depth=None), browser_version=BINARY, seed=6)
    assert spec.screen.color_depth == 24


def test_the_payload_patches_depth_battery_and_webgpu():
    spec = spec_from_configuration(_config("windows"), browser_version=BINARY, seed=7)
    source = build_payload(spec)
    for needle in ("colorDepth", "BatteryManager", "GPUAdapterInfo"):
        assert needle in source


# --------------------------------------- per-profile network / disk numbers and the switches

def _spec_for(seed, **overrides):
    return spec_from_configuration(_config("windows", **overrides), browser_version=BINARY, seed=seed)


def test_connection_and_storage_are_stable_for_a_profile_and_differ_between_profiles():
    again = [(_spec_for(77).connection, _spec_for(77).storage_quota) for _ in range(3)]
    assert again[0] == again[1] == again[2]

    seen = {(tuple(sorted(_spec_for(seed).connection.items())), _spec_for(seed).storage_quota) for seed in range(40)}
    assert len(seen) > 30                                   # not one shared value for every profile on this computer


def test_connection_values_are_what_chrome_can_actually_report():
    for seed in range(200):
        c = _spec_for(seed).connection
        assert c["effectiveType"] == "4g"
        assert c["rtt"] % 25 == 0 and 50 <= c["rtt"] <= 200            # Chrome rounds rtt to 25 ms
        assert 1.5 <= c["downlink"] <= 10.0                             # ...and caps bandwidth at 10 Mbps
        assert abs(c["downlink"] / 0.025 - round(c["downlink"] / 0.025)) < 1e-6   # in 25 kbps steps


def test_storage_quota_is_a_plausible_share_of_a_disk():
    for seed in range(200):
        quota = _spec_for(seed).storage_quota
        assert 30e9 <= quota <= 600e9


def test_the_payload_receives_both_numbers():
    cfg = _spec_for(5).js_config()
    assert cfg["connection"]["effectiveType"] == "4g" and cfg["storageQuota"] > 0


def test_noise_switches_reach_the_payload():
    default = _spec_for(5).js_config()["noise"]
    assert default == {"canvas": True, "audio": True}
    off = _spec_for(5, privacy_settings={"noise_canvas": False, "noise_audio": False}).js_config()["noise"]
    assert off == {"canvas": False, "audio": False}
    mixed = _spec_for(5, privacy_settings={"noise_audio": False}).js_config()["noise"]
    assert mixed == {"canvas": True, "audio": False}


def test_the_payload_never_reads_navigator_connection_in_a_worker():
    """Reading it while a worker is paused at start blocks the page's main thread (measured on Chrome 154:
    every Worker / SharedWorker / ServiceWorker the page created hung, and the Runtime.evaluate with it).
    The class has to be patched by name there; the object may only be read in a window."""
    import re
    from pathlib import Path

    import antidetect.infrastructure.stealth as stealth

    source = (Path(stealth.__file__).parent / "js" / "payload.js").read_text(encoding="utf-8")
    reads = [m.start() for m in re.finditer(r"G\.navigator\.connection", source)]       # code, not the comments about it
    assert reads, "the connection patch is gone: update this test"
    for position in reads:
        guard = source[max(0, position - 120):position]
        assert "!IS_WORKER" in guard, "navigator.connection is read where a worker may run it"
    assert "typeof NetworkInformation" in source



def test_the_colour_scheme_is_emulated_only_when_the_profile_does_not_follow_the_system():
    assert _spec_for(5).color_scheme == "light"                                            # the default for a profile
    assert _spec_for(5, privacy_settings={"theme": "dark"}).color_scheme == "dark"
    assert _spec_for(5, privacy_settings={"theme": "auto"}).color_scheme is None          # nothing is overridden
