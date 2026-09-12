"""Coherent browser configuration generation.

A configuration is *not* a bag of independent random values: real fingerprints
follow constraints that chain from a platform token outward:

    platform -> OS/browser -> UA string
         |---> language / locale (region) -> timezone (region-aligned)
         |---> screen geometry + device scale factor -> color depth
         |---> CPU cores / memory -> GPU vendor / renderer (OS-specific ANGLE)

Every random draw stays inside these per-platform pools, so a generated
configuration reads like a single consistent machine instead of a blender of
mismatched parts.  Templates are deterministic presets of the same shape.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

PLATFORMS = ("macos", "windows", "linux")

_CHROME_VERSIONS = (
    "150.0.0.0",
    "151.0.0.0",
    "152.0.0.0",
)

# Chrome major versions below this are treated as legacy: their UA no longer
# matches any supported real-world binary and Google flags the mismatch as
# automation ("browser is not secure"). Migration 0006 purges them.
MIN_SUPPORTED_CHROME_MAJOR = 138
LEGACY_CHROME_MAJORS = tuple(range(120, 138))

_UA_PATTERNS: dict[str, dict[str, str]] = {
    "chrome": {
        "windows": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36"
        ),
        "macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36"
        ),
        "linux": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36"
        ),
    },
    "edge": {
        "windows": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36 Edg/{v}"
        ),
        "macos": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36 Edg/{v}"
        ),
        "linux": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v} Safari/537.36 Edg/{v}"
        ),
    },
}


@dataclass(frozen=True)
class LocaleChoice:
    language: str
    locale: str
    timezones: tuple[str, ...] = field(default_factory=tuple)


_LOCALES = (
    LocaleChoice(
        "en", "en-US",
        ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"),
    ),
    LocaleChoice("en", "en-GB", ("Europe/London",)),
    LocaleChoice("de", "de-DE", ("Europe/Berlin",)),
    LocaleChoice("fr", "fr-FR", ("Europe/Paris",)),
    LocaleChoice("es", "es-ES", ("Europe/Madrid",)),
    LocaleChoice("it", "it-IT", ("Europe/Rome",)),
    LocaleChoice("nl", "nl-NL", ("Europe/Amsterdam",)),
    LocaleChoice("pl", "pl-PL", ("Europe/Warsaw",)),
    LocaleChoice("pt", "pt-BR", ("America/Sao_Paulo",)),
    LocaleChoice("ru", "ru-RU", ("Europe/Moscow", "Asia/Yekaterinburg")),
    LocaleChoice("uk", "uk-UA", ("Europe/Kyiv",)),
    LocaleChoice("tr", "tr-TR", ("Europe/Istanbul",)),
    LocaleChoice("cs", "cs-CZ", ("Europe/Prague",)),
    LocaleChoice("sv", "sv-SE", ("Europe/Stockholm",)),
    LocaleChoice("fi", "fi-FI", ("Europe/Helsinki",)),
    LocaleChoice("da", "da-DK", ("Europe/Copenhagen",)),
    LocaleChoice("ro", "ro-RO", ("Europe/Bucharest",)),
    LocaleChoice("hu", "hu-HU", ("Europe/Budapest",)),
    LocaleChoice("ja", "ja-JP", ("Asia/Tokyo",)),
    LocaleChoice("zh", "zh-CN", ("Asia/Shanghai",)),
    LocaleChoice("ko", "ko-KR", ("Asia/Seoul",)),
)

# (width, height, device_pixel_ratio) — pairs that actually occur in the wild.
_SCREENS: dict[str, tuple[tuple[int, int, float], ...]] = {
    "windows": (
        (1920, 1080, 1.0),
        (1920, 1080, 1.25),
        (1920, 1080, 1.5),
        (2560, 1440, 1.0),
        (2560, 1440, 1.5),
        (1366, 768, 1.0),
        (1600, 900, 1.0),
        (3840, 2160, 1.5),
        (3840, 2160, 2.0),
    ),
    "macos": (
        (1440, 900, 2.0),
        (2560, 1600, 2.0),
        (1728, 1117, 2.0),
        (3024, 1964, 2.0),
        (2560, 1440, 1.0),
        (2880, 1800, 2.0),
        (1920, 1200, 1.5),
    ),
    "linux": (
        (1920, 1080, 1.0),
        (1366, 768, 1.0),
        (2560, 1440, 1.0),
        (1280, 720, 1.0),
        (3840, 2160, 1.0),
    ),
}

# (cores, system_memory_gb) pools consistent with each platform class.
_HARDWARE: dict[str, tuple[tuple[int, int], ...]] = {
    "windows": ((4, 8), (8, 8), (8, 16), (12, 16), (16, 32), (32, 64)),
    "macos": ((8, 8), (8, 16), (10, 16), (12, 32), (12, 48)),
    "linux": ((4, 4), (4, 8), (8, 8), (8, 16), (16, 32)),
}

# (vendor, renderer) — OS-specific ANGLE device strings.
_WEBGL: dict[str, tuple[tuple[str, str], ...]] = {
    "windows": (
        (
            "Google Inc. (Intel)",
            "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        ),
        (
            "Google Inc. (NVIDIA)",
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        ),
        (
            "Google Inc. (AMD)",
            "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        ),
    ),
    "macos": (
        ("Google Inc. (Apple)", "ANGLE (Apple, Apple M1, OpenGL 4.1)"),
        ("Google Inc. (Apple)", "ANGLE (Apple, Apple M2, OpenGL 4.1)"),
        ("Google Inc. (Apple)", "ANGLE (Apple, Apple M3, OpenGL 4.1)"),
    ),
    "linux": (
        (
            "Google Inc. (Mesa)",
            "ANGLE (Mesa, llvmpipe (LLVM 15.0.7, 256 bits), "
            "OpenGL 4.5 (Core Profile) Mesa 23.2.1)",
        ),
        (
            "Google Inc. (Mesa)",
            "ANGLE (Mesa, Mesa Intel(R) UHD Graphics 630 (CFL GT2), "
            "OpenGL 4.5 (Core Profile) Mesa 23.2.1)",
        ),
    ),
}

_WEBGL_EXTENSIONS = (
    "ANGLE_instanced_arrays",
    "EXT_blend_minmax",
    "EXT_color_buffer_half_float",
    "EXT_disjoint_timer_query",
    "EXT_float_blend",
    "EXT_shader_texture_lod",
    "EXT_texture_compression_bptc",
    "EXT_texture_compression_rgtc",
    "EXT_texture_filter_anisotropic",
    "OES_element_index_uint",
    "OES_fbo_render_mipmap",
    "OES_standard_derivatives",
    "OES_texture_float_linear",
    "OES_vertex_array_object",
    "WEBGL_color_buffer_float",
    "WEBGL_compressed_texture_s3tc",
    "WEBGL_debug_renderer_info",
    "WEBGL_debug_shaders",
    "WEBGL_depth_texture",
    "WEBGL_lose_context",
)


def _pick_locale(rng: random.Random) -> tuple[str, str, str | None]:
    choice = rng.choice(_LOCALES)
    timezone = rng.choice(choice.timezones) if choice.timezones else None
    return choice.language, choice.locale, timezone


# Country -> (language, locale, timezone): the geo a profile must show when it
# exits through a proxy in that country. Every entry keeps the doctor gate
# green (locale suffix == timezone country == exit country). Covers the full
# random-pool geography plus common proxy exits.
COUNTRY_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "US": ("en", "en-US", "America/New_York"),
    "GB": ("en", "en-GB", "Europe/London"),
    "DE": ("de", "de-DE", "Europe/Berlin"),
    "FR": ("fr", "fr-FR", "Europe/Paris"),
    "ES": ("es", "es-ES", "Europe/Madrid"),
    "IT": ("it", "it-IT", "Europe/Rome"),
    "NL": ("nl", "nl-NL", "Europe/Amsterdam"),
    "PL": ("pl", "pl-PL", "Europe/Warsaw"),
    "BR": ("pt", "pt-BR", "America/Sao_Paulo"),
    "RU": ("ru", "ru-RU", "Europe/Moscow"),
    "UA": ("uk", "uk-UA", "Europe/Kyiv"),
    "TR": ("tr", "tr-TR", "Europe/Istanbul"),
    "CZ": ("cs", "cs-CZ", "Europe/Prague"),
    "SE": ("sv", "sv-SE", "Europe/Stockholm"),
    "FI": ("fi", "fi-FI", "Europe/Helsinki"),
    "DK": ("da", "da-DK", "Europe/Copenhagen"),
    "RO": ("ro", "ro-RO", "Europe/Bucharest"),
    "HU": ("hu", "hu-HU", "Europe/Budapest"),
    "JP": ("ja", "ja-JP", "Asia/Tokyo"),
    "CN": ("zh", "zh-CN", "Asia/Shanghai"),
    "KR": ("ko", "ko-KR", "Asia/Seoul"),
    "CA": ("en", "en-CA", "America/Toronto"),
    "AU": ("en", "en-AU", "Australia/Sydney"),
    "CH": ("de", "de-CH", "Europe/Zurich"),
    "AT": ("de", "de-AT", "Europe/Vienna"),
    "BE": ("nl", "nl-BE", "Europe/Brussels"),
    "IE": ("en", "en-IE", "Europe/Dublin"),
    "PT": ("pt", "pt-PT", "Europe/Lisbon"),
    "GR": ("el", "el-GR", "Europe/Athens"),
    "NO": ("nb", "nb-NO", "Europe/Oslo"),
    "SK": ("sk", "sk-SK", "Europe/Bratislava"),
    "BG": ("bg", "bg-BG", "Europe/Sofia"),
    "KZ": ("ru", "ru-KZ", "Asia/Almaty"),
    "MX": ("es", "es-MX", "America/Mexico_City"),
    "AR": ("es", "es-AR", "America/Argentina/Buenos_Aires"),
    "IN": ("en", "en-IN", "Asia/Kolkata"),
    "SG": ("en", "en-SG", "Asia/Singapore"),
}


def country_defaults(country_code: str | None) -> tuple[str, str, str] | None:
    """(language, locale, timezone) for an exit country, or None if unknown."""
    if not country_code:
        return None
    return COUNTRY_DEFAULTS.get(country_code.strip().upper())


def build_user_agent(
    browser: str, platform: str, version: str, pattern: str | None = None
) -> str:
    template = pattern or _UA_PATTERNS[browser][platform]
    return template.format(v=version)


def chrome_major(version: str) -> int | None:
    try:
        return int(str(version).split(".")[0])
    except (ValueError, IndexError):
        return None


def ua_chrome_major(user_agent: str) -> int | None:
    import re

    match = re.search(r"Chrome/(\d+)\.", user_agent or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def build_client_hints(browser: str, platform: str, version: str) -> dict[str, Any]:
    """Client-Hints metadata that must accompany the spoofed User-Agent.

    Chromium derives Sec-CH-UA / navigator.userAgentData from the real binary,
    not from --user-agent, so the CDP layer overrides them with this payload.
    """
    major = chrome_major(version) or 0
    if browser == "edge":
        brands = [
            {"brand": "Chromium", "version": str(major)},
            {"brand": "Microsoft Edge", "version": str(major)},
            {"brand": "Not-A.Brand", "version": "99"},
        ]
    else:
        brands = [
            {"brand": "Chromium", "version": str(major)},
            {"brand": "Google Chrome", "version": str(major)},
            {"brand": "Not-A.Brand", "version": "99"},
        ]
    platform_token = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[platform]
    return {
        "brands": brands,
        "fullVersion": version,
        "platform": platform_token,
        "platformVersion": {"windows": "15.0.0", "macos": "14.5.0", "linux": "6.8.0"}[platform],
        "architecture": "x86",
        "bitness": "64",
        "mobile": False,
        "model": "",
    }


def validate_draft(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize and structurally validate a generated/manual configuration."""
    draft = dict(params)

    def positive_int(value, name: str) -> None:
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise ValueError(f"{name} must be a positive integer, got {value!r}")

    positive_int(draft.get("screen_width"), "screen_width")
    positive_int(draft.get("screen_height"), "screen_height")
    positive_int(draft.get("color_depth"), "color_depth")
    if draft.get("screen_width") is None and draft.get("screen_height") is not None:
        raise ValueError("screen_height requires screen_width to be set too")
    if draft.get("screen_width") is not None and draft.get("screen_height") is None:
        raise ValueError("screen_width requires screen_height to be set too")

    dpr = draft.get("device_pixel_ratio")
    if dpr is not None and (not isinstance(dpr, (int, float)) or dpr <= 0):
        raise ValueError(f"device_pixel_ratio must be positive, got {dpr!r}")

    for key in ("user_agent", "platform", "language", "locale", "timezone"):
        value = draft.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be a string, got {value!r}")

    ua = draft.get("user_agent")
    if isinstance(ua, str) and ua:
        major = ua_chrome_major(ua)
        if major is not None and major in LEGACY_CHROME_MAJORS:
            raise ValueError(
                f"user_agent Chrome/{major} is legacy (purged by migration 0006); "
                f"regenerate with Chrome >={MIN_SUPPORTED_CHROME_MAJOR}"
            )
        hints = draft.get("client_hints")
        if isinstance(hints, dict) and hints:
            hint_version = str(hints.get("fullVersion") or "")
            hint_major = chrome_major(hint_version)
            if major is not None and hint_major is not None and major != hint_major:
                raise ValueError(
                    f"user_agent Chrome/{major} mismatches client_hints {hint_version!r}; "
                    "generate them atomically via build_client_hints()"
                )
            hint_platform = str(hints.get("platform") or "")
            platform = draft.get("platform")
            expected = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}.get(platform or "")
            if expected and hint_platform and hint_platform != expected:
                raise ValueError(
                    f"platform {platform!r} mismatches client_hints platform {hint_platform!r}"
                )
        _check_platform_webgl_consistency(draft)
    return draft


def _check_platform_webgl_consistency(draft: dict[str, Any]) -> None:
    platform = draft.get("platform")
    webgl = draft.get("webgl_settings")
    if not platform or not isinstance(webgl, dict):
        return
    renderer = str(webgl.get("renderer") or "")
    vendor = str(webgl.get("vendor") or "")
    blob = f"{vendor} {renderer}"
    if platform == "windows" and ("Apple" in blob or "Mesa" in blob or "llvmpipe" in blob):
        raise ValueError(f"platform 'windows' mismatches WebGL {blob!r} (expected ANGLE Direct3D11)")
    if platform == "macos" and ("Direct3D11" in blob or "Mesa" in blob or "llvmpipe" in blob):
        raise ValueError(f"platform 'macos' mismatches WebGL {blob!r} (expected ANGLE Apple OpenGL)")
    if platform == "linux" and ("Direct3D11" in blob or "Apple M" in blob):
        raise ValueError(f"platform 'linux' mismatches WebGL {blob!r} (expected ANGLE Mesa)")


class ConfigurationGenerator:
    """Builds coherent fingerprint parameter sets.

    ``generate_random`` draws a full consistent configuration from the pools
    above.  ``generate_from_template`` returns a deterministic preset.  Both
    return plain dicts meant for ``BrowserConfigurationRepository.create``.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def list_templates(self) -> list[str]:
        return list(TEMPLATES)

    def generate_random(
        self,
        platform: str | None = None,
        browser: str | None = None,
    ) -> dict[str, Any]:
        rng = self._rng
        platform = platform or rng.choice(PLATFORMS)
        if platform not in PLATFORMS:
            raise ValueError(
                f"Unknown platform {platform!r}; expected one of {PLATFORMS}"
            )
        browser = browser or (rng.choice(("chrome", "chrome", "chrome", "edge")))
        if browser not in _UA_PATTERNS:
            raise ValueError(
                f"Unknown browser {browser!r}; expected one of {tuple(_UA_PATTERNS)}"
            )

        version = rng.choice(_CHROME_VERSIONS)
        user_agent = build_user_agent(browser, platform, version)
        client_hints = build_client_hints(browser, platform, version)

        language, locale_tag, timezone = _pick_locale(rng)
        width, height, dpr = rng.choice(_SCREENS[platform])
        # Color depth: 24-bit dominates; 16-bit occasionally on Windows/Linux.
        color_depth = 24 if rng.random() > 0.12 else 16
        cores, memory_gb = rng.choice(_HARDWARE[platform])
        vendor, renderer = rng.choice(_WEBGL[platform])
        extensions = [ext for ext in _WEBGL_EXTENSIONS if rng.random() > 0.25]

        return validate_draft(
            {
                "user_agent": user_agent,
                "platform": platform,
                "language": language,
                "locale": locale_tag,
                "timezone": timezone,
                "screen_width": width,
                "screen_height": height,
                "device_pixel_ratio": dpr,
                "color_depth": color_depth,
                "webgl_settings": {
                    "vendor": vendor,
                    "renderer": renderer,
                    "version": "WebGL 2.0",
                    "shading_language_version": "WebGL GLSL ES 3.00",
                    "extensions": extensions,
                },
                "hardware_settings": {
                    "cores": cores,
                    "memory_gb": memory_gb,
                    "device_memory_gb": min(8, memory_gb),
                },
                "client_hints": client_hints,
            }
        )

    def generate_for_country(
        self,
        country_code: str,
        platform: str | None = None,
    ) -> dict[str, Any]:
        """Generate a fingerprint coherent with a proxy exit country.

        Same platform pools as ``generate_random``, but language/locale/
        timezone are pinned to the exit country so the doctor geo-gate
        (exit == timezone == locale) passes. Raises ValueError for unknown
        countries.
        """
        code = (country_code or "").strip().upper()
        defaults = country_defaults(code)
        if defaults is None:
            raise ValueError(
                f"Unknown country {country_code!r}; cannot pin a locale/timezone. "
                "Check the proxy or extend COUNTRY_DEFAULTS."
            )
        language, locale_tag, timezone = defaults
        params = self.generate_random(platform=platform)
        params.update(
            {"language": language, "locale": locale_tag, "timezone": timezone}
        )
        return validate_draft(params)

    def generate_from_template(self, template: str) -> dict[str, Any]:
        try:
            base = TEMPLATES[template]
        except KeyError:
            raise ValueError(
                f"Unknown template {template!r}; "
                f"available: {', '.join(sorted(TEMPLATES))}"
            ) from None
        params = {key: (list(value) if isinstance(value, tuple) else value)
                  for key, value in base.items()}
        params.pop("browser", None)
        return validate_draft(params)


def _template(
    *,
    platform: str,
    browser: str,
    version: str,
    language: str,
    locale: str,
    timezone: str,
    width: int,
    height: int,
    dpr: float,
    color_depth: int,
    cores: int,
    memory_gb: int,
    vendor: str,
    renderer: str,
) -> dict[str, Any]:
    return {
        "browser": browser,
        "user_agent": build_user_agent(browser, platform, version),
        "platform": platform,
        "language": language,
        "locale": locale,
        "timezone": timezone,
        "screen_width": width,
        "screen_height": height,
        "device_pixel_ratio": dpr,
        "color_depth": color_depth,
        "webgl_settings": {
            "vendor": vendor,
            "renderer": renderer,
            "version": "WebGL 2.0",
            "shading_language_version": "WebGL GLSL ES 3.00",
            "extensions": list(_WEBGL_EXTENSIONS),
        },
        "hardware_settings": {
            "cores": cores,
            "memory_gb": memory_gb,
            "device_memory_gb": min(8, memory_gb),
        },
        "client_hints": build_client_hints(browser, platform, version),
    }


TEMPLATES: dict[str, dict[str, Any]] = {
    "windows-chrome": _template(
        platform="windows", browser="chrome", version="152.0.0.0",
        language="en", locale="en-US", timezone="America/New_York",
        width=1920, height=1080, dpr=1.0, color_depth=24,
        cores=8, memory_gb=16,
        vendor="Google Inc. (Intel)",
        renderer=(
            "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, "
            "D3D11)"
        ),
    ),
    "windows-edge": _template(
        platform="windows", browser="edge", version="152.0.0.0",
        language="en", locale="en-US", timezone="America/Chicago",
        width=2560, height=1440, dpr=1.5, color_depth=24,
        cores=16, memory_gb=32,
        vendor="Google Inc. (NVIDIA)",
        renderer=(
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, "
            "D3D11)"
        ),
    ),
    "macos-chrome": _template(
        platform="macos", browser="chrome", version="152.0.0.0",
        language="en", locale="en-US", timezone="America/Los_Angeles",
        width=2560, height=1600, dpr=2.0, color_depth=24,
        cores=10, memory_gb=16,
        vendor="Google Inc. (Apple)",
        renderer="ANGLE (Apple, Apple M2, OpenGL 4.1)",
    ),
    "macos-edge": _template(
        platform="macos", browser="edge", version="151.0.0.0",
        language="en", locale="en-GB", timezone="Europe/London",
        width=1728, height=1117, dpr=2.0, color_depth=24,
        cores=12, memory_gb=32,
        vendor="Google Inc. (Apple)",
        renderer="ANGLE (Apple, Apple M3, OpenGL 4.1)",
    ),
    "linux-chrome": _template(
        platform="linux", browser="chrome", version="151.0.0.0",
        language="de", locale="de-DE", timezone="Europe/Berlin",
        width=1920, height=1080, dpr=1.0, color_depth=24,
        cores=8, memory_gb=16,
        vendor="Google Inc. (Mesa)",
        renderer=(
            "ANGLE (Mesa, Mesa Intel(R) UHD Graphics 630 (CFL GT2), "
            "OpenGL 4.5 (Core Profile) Mesa 23.2.1)"
        ),
    ),
}