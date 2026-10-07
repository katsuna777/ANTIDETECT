"""UA / Client Hints construction must match what a real Chrome emits."""

from __future__ import annotations

from antidetect.application.fingerprint import identity as ident
from antidetect.application.fingerprint import data as fd


def test_brand_list_matches_real_chrome_154():
    # Captured from a real Chrome 154 (navigator.userAgentData.brands).
    assert ident.brand_list(154) == [
        {"brand": "Chromium", "version": "154"},
        {"brand": "Google Chrome", "version": "154"},
        {"brand": "Not A(Brand", "version": "99"},
    ]


def test_full_version_list_uses_four_part_versions_and_grease_suffix():
    listing = ident.brand_list(154, full="154.0.8037.93")
    assert {"brand": "Chromium", "version": "154.0.8037.93"} in listing
    assert {"brand": "Google Chrome", "version": "154.0.8037.93"} in listing
    assert {"brand": "Not A(Brand", "version": "99.0.0.0"} in listing


def test_brand_order_and_grease_vary_with_major_like_chromium():
    seen_orders = set()
    for major in range(140, 160):
        listing = ident.brand_list(major)
        assert len(listing) == 3
        assert {b["brand"] for b in listing} >= {"Chromium", "Google Chrome"}
        seen_orders.add(tuple(b["brand"] == "Chromium" for b in listing))
    assert len(seen_orders) > 1  # not a fixed shuffle


def test_edge_brand_replaces_chrome():
    names = {b["brand"] for b in ident.brand_list(154, ident.EDGE)}
    assert "Microsoft Edge" in names and "Google Chrome" not in names
    assert ident.brand_for_binary("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge") == ident.EDGE
    assert ident.brand_for_binary("/usr/bin/google-chrome") == ident.CHROME


def test_user_agent_uses_reduced_form_and_os_token():
    ua = ident.build_user_agent("windows", 154)
    assert ua == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    )
    assert "Macintosh; Intel Mac OS X 10_15_7" in ident.build_user_agent("macos", 154)
    assert ident.build_user_agent("windows", 154, ident.EDGE).endswith("Edg/154.0.0.0")


def test_ua_metadata_is_complete_and_consistent():
    meta = ident.build_ua_metadata(
        "macos", "154.0.8037.93", platform_version="14.5.0", architecture="arm"
    )
    assert meta["platform"] == "macOS"
    assert meta["architecture"] == "arm" and meta["bitness"] == "64"
    assert meta["mobile"] is False and meta["wow64"] is False
    assert meta["formFactors"] == ["Desktop"]
    assert meta["fullVersion"] == "154.0.8037.93"
    assert meta["brands"] == ident.brand_list(154)


def test_apple_silicon_is_arm_everything_else_x86():
    assert ident.architecture_for("macos", "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)") == "arm"
    assert ident.architecture_for("windows", "ANGLE (NVIDIA, ...)") == "x86"
    assert ident.architecture_for("linux", None) == "x86"


def test_language_list_has_no_quality_values():
    assert ident.language_list("es", "es-ES") == ("es-ES", "es")
    assert ident.language_list("en", "en-US") == ("en-US", "en")
    assert ident.language_list(None, None) == ("en-US", "en")
    for value in ident.language_list("de", "de-DE"):
        assert ";q=" not in value


def test_every_gpu_belongs_to_its_platforms_backend():
    expected = {"windows": "d3d11", "macos": "metal", "linux": "gl"}
    for platform, pool in fd.GPUS.items():
        for gpu in pool:
            assert gpu.family == expected[platform]
            assert gpu.vendor.startswith("Google Inc. (")
            assert gpu.renderer.startswith("ANGLE (")
    assert all("Direct3D11" in g.renderer for g in fd.GPUS["windows"])
    assert all("ANGLE Metal Renderer" in g.renderer for g in fd.GPUS["macos"])


def test_gl_capability_tables_cover_every_backend():
    for family in ("d3d11", "metal", "gl"):
        assert fd.GL_PARAMS[family]["webgl"] and fd.GL_EXTENSIONS[family]["webgl"]
    # D3D11 has no Apple/mobile texture formats; Metal does.
    assert "WEBGL_compressed_texture_astc" in fd.GL_EXTENSIONS["metal"]["webgl"]
    assert "WEBGL_compressed_texture_astc" not in fd.GL_EXTENSIONS["d3d11"]["webgl"]


def test_screens_are_in_css_pixels_with_os_insets():
    for sc in fd.SCREENS["windows"]:
        assert sc.avail_height == sc.height - 40  # taskbar
    for sc in fd.SCREENS["macos"]:
        assert sc.avail_top in (25, 38) and sc.avail_height <= sc.height - sc.avail_top
    # 1920x1080 at 125% is 1536x864 CSS px, never 1920 wide at dpr 1.25.
    assert not any(sc.width == 1920 and sc.dpr == 1.25 for sc in fd.SCREENS["windows"])


def test_font_mask_only_for_foreign_os():
    assert fd.font_mask("windows", "windows") is None
    mask = fd.font_mask("windows", "macos")
    assert "Helvetica Neue" in mask["hide"] and "Menlo" in mask["hide"]
    assert "Segoe UI" in [name for name, _ in mask["fake"]]
    assert "Segoe UI" not in mask["hide"]
    reverse = fd.font_mask("macos", "windows")
    assert "Segoe UI" in reverse["hide"]
    assert "Helvetica Neue" in [name for name, _ in reverse["fake"]]
