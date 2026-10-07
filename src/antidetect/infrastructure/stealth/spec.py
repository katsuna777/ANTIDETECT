"""Renderer-facing fingerprint spec derived from a stored configuration.

A stored :class:`BrowserConfiguration` is an *intent* (platform, locale,
screen, GPU, ...). At launch it is resolved against the browser that will
really run: the UA version always equals the installed binary (a UA that
disagrees with the engine is detectable by feature probing), brands/full
version come from the same value, and WebGL capability tables are attached
only when the spoofed GPU belongs to a different graphics backend than the
host's.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from antidetect.application.fingerprint import identity as ident
from antidetect.application.fingerprint import data as fd
from antidetect.application.fingerprint import privacy
from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.infrastructure.stealth.voices import js_voices


@dataclass(frozen=True)
class ScreenSpec:
    width: int
    height: int
    dpr: float
    avail_width: int
    avail_height: int
    avail_left: int
    avail_top: int
    color_depth: int = 24

    @property
    def color_profile(self) -> str:
        """Value for Chrome's ``--force-color-profile`` (decides ``color-gamut`` / ``dynamic-range``)."""
        return fd.color_profile(self.color_depth)


@dataclass(frozen=True)
class StealthSpec:
    """Everything the engine applies to a profile, already resolved."""

    platform_key: str                       # windows | macos | linux
    user_agent: str | None
    ua_metadata: dict[str, Any] | None
    nav_platform: str | None
    accept_language: str | None
    languages: tuple[str, ...]
    locale: str | None
    timezone_id: str | None
    cores: int | None
    device_memory: int | None
    screen: ScreenSpec | None
    webgl: dict[str, Any] | None
    geolocation: tuple[float, float] | None
    font_mask: dict[str, Any] | None
    seed: int
    token: str
    noise_canvas: bool = True
    noise_audio: bool = True
    voices: tuple[dict[str, Any], ...] = ()
    # Off by default: readPixels noise cannot be made consistent between partial
    # and full reads, and pixelscan flags it as "masking" (verified).
    noise_webgl: bool = False
    # Both values come from the host's network and disk, so every profile on one computer would
    # report the same ones; each profile gets its own plausible pair, stable between launches.
    connection: dict[str, Any] | None = None
    storage_quota: int | None = None
    #: ``light`` / ``dark``: what ``prefers-color-scheme`` answers; ``None`` leaves the system's (done natively over CDP).
    color_scheme: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def js_config(self) -> dict[str, Any]:
        """JSON handed to the in-page payload."""
        cfg: dict[str, Any] = {
            "token": self.token,
            "seed": self.seed,
            "platform": self.nav_platform,
            "userAgent": self.user_agent,
            "appVersion": (
                self.user_agent[len("Mozilla/"):]
                if self.user_agent and self.user_agent.startswith("Mozilla/")
                else None
            ),
            "cores": self.cores,
            "deviceMemory": self.device_memory,
            "languages": list(self.languages),
            "noise": {"canvas": self.noise_canvas, "audio": self.noise_audio},
        }
        if self.connection:
            cfg["connection"] = dict(self.connection)
        if self.storage_quota:
            cfg["storageQuota"] = int(self.storage_quota)
        if self.voices:
            cfg["voices"] = list(self.voices)
        if self.font_mask is not None:
            cfg["fonts"] = self.font_mask
        if self.ua_metadata is not None:
            meta = self.ua_metadata
            cfg["uaData"] = {
                "brands": meta["brands"],
                "fullVersionList": meta["fullVersionList"],
                "platform": meta["platform"],
                "platformVersion": meta["platformVersion"],
                "architecture": meta["architecture"],
                "bitness": meta["bitness"],
                "model": meta["model"],
                "mobile": meta["mobile"],
                "wow64": meta["wow64"],
                "formFactors": meta["formFactors"],
                "uaFullVersion": meta["fullVersion"],
            }
        if self.screen is not None:
            cfg["screen"] = {
                "colorDepth": self.screen.color_depth,
                "availWidth": self.screen.avail_width,
                "availHeight": self.screen.avail_height,
                "availLeft": self.screen.avail_left,
                "availTop": self.screen.avail_top,
            }
        if self.webgl is not None:
            webgl = dict(self.webgl)
            webgl["noise"] = self.noise_webgl
            cfg["webgl"] = webgl
        return cfg


_HOST_FAMILY = {"macos": "metal", "windows": "d3d11", "linux": "gl"}


def _connection_spec(seed: int) -> dict[str, Any]:
    """What ``navigator.connection`` reports on a broadband desktop: Chrome rounds ``rtt`` to
    25 ms and ``downlink`` to 25 kbps, and caps ``downlink`` at 10 Mbps."""
    rng = random.Random(seed ^ 0xC0DE)
    rtt = rng.choice((50, 50, 50, 100, 100, 150, 200))
    downlink = 10.0 if rng.random() < 0.35 else round(rng.uniform(1.5, 9.9) / 0.025) * 0.025
    return {"effectiveType": "4g", "rtt": rtt, "downlink": round(downlink, 3)}


def _storage_quota(seed: int) -> int:
    """``navigator.storage.estimate().quota``: a share of the disk, which differs per computer."""
    rng = random.Random(seed ^ 0x5707)
    disk_gb = rng.choice((128, 256, 512, 512, 1024))
    return int(disk_gb * 1e9 * rng.uniform(0.25, 0.55))

_DEVICE_MEMORY_STEPS = (0.25, 0.5, 1, 2, 4, 8, 16, 32)


def _snap_memory(gb: int | float | None) -> int | None:
    if not gb:
        return None
    best = max(step for step in _DEVICE_MEMORY_STEPS if step <= gb) if gb >= 0.25 else 0.25
    return int(best) if best >= 1 else best  # type: ignore[return-value]


def _screen_spec(configuration: BrowserConfiguration, platform: str) -> ScreenSpec | None:
    width, height = configuration.screen_width, configuration.screen_height
    if not width or not height:
        return None
    dpr = float(configuration.device_pixel_ratio or 1.0)
    depth = int(configuration.color_depth or 24)
    for known in fd.SCREENS.get(platform, ()):
        if known.width == width and known.height == height:
            return ScreenSpec(width, height, dpr, width, known.avail_height, 0, known.avail_top, depth)
    inset_top = 25 if platform == "macos" else (27 if platform == "linux" else 0)
    inset_bottom = 40 if platform == "windows" else 0
    return ScreenSpec(width, height, dpr, width, height - inset_top - inset_bottom, 0, inset_top, depth)


def _webgl_spec(
    configuration: BrowserConfiguration, platform: str, host: str
) -> dict[str, Any] | None:
    settings = configuration.webgl_settings or {}
    vendor, renderer = settings.get("vendor"), settings.get("renderer")
    if not vendor and not renderer:
        return None
    family = fd.family_for_renderer(renderer, platform)
    spec: dict[str, Any] = {
        "vendor": vendor,
        "renderer": renderer,
        "family": family,
        # What navigator.gpu answers: it must name the same card as WebGL does.
        "gpu": fd.webgpu_info(renderer, platform),
    }
    if family != _HOST_FAMILY[host]:
        spec["params"] = fd.GL_PARAMS.get(family, {})
        spec["extensions"] = fd.GL_EXTENSIONS.get(family, {})
    return spec


def spec_from_configuration(
    configuration: BrowserConfiguration,
    *,
    browser_version: str | None = None,
    browser_brand: str = ident.CHROME,
    seed: int = 0,
    host_platform: str | None = None,
    mask_fonts: bool | None = None,
) -> StealthSpec:
    """Resolve a configuration against the real browser into a launch spec.

    ``mask_fonts`` (default off, or ``ANTIDETECT_MASK_FONTS=1``) enables the
    experimental ``@font-face`` masking for cross-OS profiles. It is off because
    it measurably *hurts*: IPHey rates a Windows profile on a Mac "Trustworthy"
    (MX 100) without it and "Unreliable" (MX 70) with it, and the other checkers
    (CreepJS, Pixelscan) are indifferent. Kept for experiments only.
    """
    import os

    if mask_fonts is None:
        mask_fonts = os.environ.get("ANTIDETECT_MASK_FONTS", "").strip().lower() in ("1", "true", "yes")
    host = host_platform or fd.host_platform()
    platform = configuration.platform if configuration.platform in fd.PLATFORMS else host
    rng = random.Random(seed ^ 0x5EED)

    user_agent: str | None = None
    metadata: dict[str, Any] | None = None
    nav_platform: str | None = None
    if configuration.user_agent:
        full_version = browser_version
        if not full_version:
            stored_major = ident.ua_chrome_major(configuration.user_agent) or 0
            hints_full = str((configuration.client_hints or {}).get("fullVersion") or "")
            full_version = hints_full if ident.chrome_major(hints_full) == stored_major else f"{stored_major}.0.0.0"
        major = ident.chrome_major(full_version) or 0
        user_agent = ident.build_user_agent(platform, major, browser_brand)
        hints = configuration.client_hints or {}
        platform_version = str(hints.get("platformVersion") or "") or rng.choice(
            fd.PLATFORM_VERSIONS[platform]
        )
        webgl_settings = configuration.webgl_settings or {}
        metadata = ident.build_ua_metadata(
            platform,
            full_version,
            brand=browser_brand,
            platform_version=platform_version,
            architecture=str(hints.get("architecture") or ident.architecture_for(platform, webgl_settings.get("renderer"))),
            bitness=str(hints.get("bitness") or "64"),
        )
        nav_platform = fd.NAVIGATOR_PLATFORM[platform]

    languages = ident.language_list(configuration.language, configuration.locale)
    accept = ",".join(languages) if (configuration.language or configuration.locale) else None

    hardware = configuration.hardware_settings or {}
    cores = hardware.get("cores")
    memory = _snap_memory(hardware.get("device_memory_gb"))

    timezone = configuration.timezone
    coords = fd.TIMEZONE_COORDS.get(timezone or "")
    geolocation = None
    if coords:
        jitter = random.Random(seed ^ 0x6E0)
        geolocation = (
            round(coords[0] + jitter.uniform(-0.04, 0.04), 5),
            round(coords[1] + jitter.uniform(-0.04, 0.04), 5),
        )

    locale = configuration.locale or (languages[0] if configuration.language else None)
    switches = privacy.resolve(configuration.privacy_settings)
    token = "".join(random.Random(seed ^ 0xA11CE).choice("abcdefghijklmnopqrstuvwxyz") for _ in range(10))
    return StealthSpec(
        platform_key=platform,
        user_agent=user_agent,
        ua_metadata=metadata,
        nav_platform=nav_platform,
        accept_language=accept,
        languages=languages if (configuration.language or configuration.locale) else (),
        locale=locale,
        timezone_id=timezone,
        cores=int(cores) if cores else None,
        device_memory=memory,
        screen=_screen_spec(configuration, platform),
        webgl=_webgl_spec(configuration, platform, host),
        geolocation=geolocation,
        font_mask=fd.font_mask(platform, host) if mask_fonts else None,
        seed=seed & 0xFFFFFFFF,
        token=token,
        noise_canvas=switches["noise_canvas"],
        noise_audio=switches["noise_audio"],
        color_scheme=None if switches["theme"] == privacy.THEME_AUTO else switches["theme"],
        connection=_connection_spec(seed),
        storage_quota=_storage_quota(seed),
        voices=tuple(js_voices(platform, locale)),
    )


def spec_json(spec: StealthSpec) -> str:
    return json.dumps(spec.js_config(), ensure_ascii=False, separators=(",", ":"))
