"""Coherent browser configuration generation.

A configuration is *not* a bag of independent random values: real fingerprints
follow constraints that chain from a platform token outward:

    platform -> UA string / Client Hints (version = the installed browser)
         |---> language / locale (region) -> timezone (region-aligned)
         |---> screen (CSS px) + device scale factor -> OS chrome insets
         |---> CPU cores / memory -> GPU vendor / renderer (OS-specific ANGLE)

Every random draw stays inside the per-platform pools of
:mod:`antidetect.application.fingerprint.data`, so a generated configuration reads
like one consistent machine. Templates are deterministic presets of the same
shape. The stored UA/hints are rebuilt from the real binary at launch; what is
stored here is the *intent* plus a faithful copy for display.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from antidetect.application.fingerprint import identity as ident
from antidetect.application.fingerprint import data as fd
from antidetect.application.fingerprint.identity import chrome_major, ua_chrome_major  # noqa: F401  (re-exported)

PLATFORMS = fd.PLATFORMS

#: Used only when the installed browser version cannot be probed.
FALLBACK_CHROME_VERSION = "154.0.8037.93"

# Chrome major versions below this are treated as legacy: their UA no longer
# matches any supported real-world binary and Google flags the mismatch as
# automation ("browser is not secure"). Migration 0006 purges them.
MIN_SUPPORTED_CHROME_MAJOR = 138
LEGACY_CHROME_MAJORS = tuple(range(120, 138))

#: Relative market share used when no platform is requested.
_PLATFORM_WEIGHTS = (("windows", 68), ("macos", 26), ("linux", 6))

#: Kept for callers that read the old (vendor, renderer) pools per platform.
_WEBGL: dict[str, tuple[tuple[str, str], ...]] = {
    platform: tuple((gpu.vendor, gpu.renderer) for gpu in pool)
    for platform, pool in fd.GPUS.items()
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


#: Main browser languages offered in the config dialog picker.
#: The language is always a manual choice — unlike timezone/locale it is
#: never auto-synced, so any value (even outside this pool) is accepted.
SUPPORTED_LANGUAGES: tuple[str, ...] = tuple(
    sorted({language for language, _locale, _timezone in COUNTRY_DEFAULTS.values()})
)


def build_user_agent(
    browser: str, platform: str, version: str, pattern: str | None = None
) -> str:
    """UA string for ``platform``; ``version`` is a full or major-only Chrome version."""
    major = chrome_major(version) or 0
    if pattern:
        return pattern.format(v=f"{major}.0.0.0")
    return ident.build_user_agent(platform, major, ident.EDGE if browser == "edge" else ident.CHROME)


def build_client_hints(
    browser: str,
    platform: str,
    version: str,
    *,
    renderer: str | None = None,
    platform_version: str | None = None,
) -> dict[str, Any]:
    """Client-Hints metadata that must accompany the spoofed User-Agent.

    Chromium derives Sec-CH-UA / navigator.userAgentData from the real binary,
    not from --user-agent, so the CDP layer overrides them with this payload.
    """
    brand = ident.EDGE if browser == "edge" else ident.CHROME
    major = chrome_major(version) or 0
    meta = ident.build_ua_metadata(
        platform,
        version if version.count(".") >= 3 else f"{major}.0.0.0",
        brand=brand,
        platform_version=platform_version or fd.PLATFORM_VERSIONS[platform][0],
        architecture=ident.architecture_for(platform, renderer),
    )
    return {
        "brands": meta["brands"],
        "fullVersion": meta["fullVersion"],
        "platform": meta["platform"],
        "platformVersion": meta["platformVersion"],
        "architecture": meta["architecture"],
        "bitness": meta["bitness"],
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


def _hardware_for(platform: str, gpu: fd.Gpu, rng: random.Random) -> tuple[int, int]:
    """(cores, RAM GB) that belong to the same machine as ``gpu``."""
    if platform == "macos":
        cores_options, ram_options = fd.MAC_CHIPS.get(gpu.label, ((8,), (8, 16)))
        return rng.choice(cores_options), rng.choice(ram_options)
    return rng.choice(fd.PC_HARDWARE[platform])


def _memory_class(memory_gb: int) -> int:
    """``navigator.deviceMemory`` bucket (power of two, <= installed RAM)."""
    value = 1
    while value * 2 <= memory_gb:
        value *= 2
    return min(value, 32)


def _webgl_settings(gpu: fd.Gpu) -> dict[str, Any]:
    return {
        "vendor": gpu.vendor,
        "renderer": gpu.renderer,
        "version": "WebGL 2.0",
        "shading_language_version": "WebGL GLSL ES 3.00",
    }


def _assemble(
    *,
    platform: str,
    version: str,
    language: str,
    locale: str,
    timezone: str | None,
    screen: fd.Screen,
    gpu: fd.Gpu,
    cores: int,
    memory_gb: int,
    browser: str = "chrome",
) -> dict[str, Any]:
    major = chrome_major(version) or 0
    return {
        "user_agent": build_user_agent(browser, platform, version),
        "platform": platform,
        "language": language,
        "locale": locale,
        "timezone": timezone,
        "screen_width": screen.width,
        "screen_height": screen.height,
        "device_pixel_ratio": screen.dpr,
        "color_depth": fd.default_color_depth(platform, screen.dpr),
        "webgl_settings": _webgl_settings(gpu),
        "hardware_settings": {
            "cores": cores,
            "memory_gb": memory_gb,
            "device_memory_gb": _memory_class(memory_gb),
        },
        "client_hints": build_client_hints(
            browser, platform, version if version.count(".") >= 3 else f"{major}.0.0.0",
            renderer=gpu.renderer,
        ),
    }


class ConfigurationGenerator:
    """Builds coherent fingerprint parameter sets.

    ``generate_random`` draws a full consistent configuration from the pools
    in :mod:`fingerprint_data`.  ``generate_from_template`` returns a
    deterministic preset.  Both return plain dicts meant for
    ``BrowserConfigurationRepository.create``.

    ``browser_version`` (optional callable) supplies the installed browser's
    full version so generated UA/hints match the engine that will run them.
    """

    def __init__(
        self,
        rng: random.Random | None = None,
        browser_version: Callable[[], str | None] | None = None,
    ) -> None:
        self._rng = rng or random.Random()
        self._browser_version = browser_version

    def list_templates(self) -> list[str]:
        return list(TEMPLATES)

    def current_version(self) -> str:
        """Full Chrome version to put into generated fingerprints."""
        if self._browser_version is not None:
            try:
                value = self._browser_version()
            except Exception:
                value = None
            if value and chrome_major(value):
                return value
        return FALLBACK_CHROME_VERSION

    def generate_random(
        self,
        platform: str | None = None,
        browser: str | None = None,
    ) -> dict[str, Any]:
        rng = self._rng
        if platform is None:
            names = [name for name, _ in _PLATFORM_WEIGHTS]
            weights = [weight for _, weight in _PLATFORM_WEIGHTS]
            platform = rng.choices(names, weights=weights, k=1)[0]
        if platform not in PLATFORMS:
            raise ValueError(
                f"Unknown platform {platform!r}; expected one of {PLATFORMS}"
            )
        browser = browser or "chrome"
        if browser not in ("chrome", "edge"):
            raise ValueError(f"Unknown browser {browser!r}; expected one of ('chrome', 'edge')")

        gpu = fd.pick_weighted(rng, fd.GPUS[platform])
        cores, memory_gb = _hardware_for(platform, gpu, rng)
        screen = fd.pick_weighted(rng, fd.SCREENS[platform])
        language, locale_tag, timezone = _pick_locale(rng)
        return validate_draft(
            _assemble(
                platform=platform,
                version=self.current_version(),
                language=language,
                locale=locale_tag,
                timezone=timezone,
                screen=screen,
                gpu=gpu,
                cores=cores,
                memory_gb=memory_gb,
                browser=browser,
            )
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
        # Presets follow the installed browser, not the version they were written for.
        version = self.current_version()
        platform = params["platform"]
        renderer = (params.get("webgl_settings") or {}).get("renderer")
        params["user_agent"] = build_user_agent("chrome", platform, version)
        params["client_hints"] = build_client_hints("chrome", platform, version, renderer=renderer)
        return validate_draft(params)


def _template(
    *,
    platform: str,
    language: str,
    locale: str,
    timezone: str,
    screen: fd.Screen,
    gpu_label: str,
    cores: int,
    memory_gb: int,
) -> dict[str, Any]:
    gpu = next(g for g in fd.GPUS[platform] if g.label == gpu_label)
    params = _assemble(
        platform=platform,
        version=FALLBACK_CHROME_VERSION,
        language=language,
        locale=locale,
        timezone=timezone,
        screen=screen,
        gpu=gpu,
        cores=cores,
        memory_gb=memory_gb,
    )
    params["browser"] = "chrome"
    return params


TEMPLATES: dict[str, dict[str, Any]] = {
    "windows-chrome": _template(
        platform="windows", language="en", locale="en-US", timezone="America/New_York",
        screen=fd.SCREENS["windows"][0], gpu_label="GTX 1650", cores=8, memory_gb=16,
    ),
    "windows-laptop": _template(
        platform="windows", language="en", locale="en-US", timezone="America/Chicago",
        screen=fd.SCREENS["windows"][1], gpu_label="Iris Xe", cores=8, memory_gb=16,
    ),
    "macos-chrome": _template(
        platform="macos", language="en", locale="en-US", timezone="America/Los_Angeles",
        screen=fd.SCREENS["macos"][1], gpu_label="Apple M2", cores=8, memory_gb=16,
    ),
    "linux-chrome": _template(
        platform="linux", language="de", locale="de-DE", timezone="Europe/Berlin",
        screen=fd.SCREENS["linux"][0], gpu_label="UHD 630", cores=8, memory_gb=16,
    ),
}
