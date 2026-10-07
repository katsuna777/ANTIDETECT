"""User-Agent and Client Hints construction.

The UA string, ``Sec-CH-UA`` brand list and ``navigator.userAgentData`` are all
derived from one (platform, version, brand) triple so they can never drift
apart. Brand ordering and the GREASE entry follow Chromium's
``GenerateBrandVersionList`` (verified against a real Chrome 154 run).
"""

from __future__ import annotations

import re
from typing import Any

from antidetect.application.fingerprint.data import (
    HINTS_PLATFORM,
    UA_OS_TOKENS,
)

CHROME = "Google Chrome"
EDGE = "Microsoft Edge"

_GREASE_CHARS = (" ", "(", ":", "-", ".", "/", ")", ";", "=", "?", "_")
_GREASE_VERSIONS = ("8", "99", "24")
_ORDERS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))


def chrome_major(version: str | None) -> int | None:
    try:
        return int(str(version).split(".")[0])
    except (ValueError, IndexError, TypeError):
        return None


def ua_chrome_major(user_agent: str | None) -> int | None:
    match = re.search(r"Chrome/(\d+)\.", user_agent or "")
    return int(match.group(1)) if match else None


def brand_for_binary(binary_path: str | None) -> str:
    """UA-CH brand matching the browser binary that will really run."""
    name = (binary_path or "").lower()
    if "msedge" in name or "edge" in name:
        return EDGE
    return CHROME


def _grease(major: int) -> tuple[str, str]:
    name = f"Not{_GREASE_CHARS[major % 11]}A{_GREASE_CHARS[(major + 1) % 11]}Brand"
    return name, _GREASE_VERSIONS[major % 3]


def brand_list(major: int, brand: str = CHROME, *, full: str | None = None) -> list[dict[str, str]]:
    """Ordered ``brands`` (or ``fullVersionList`` when ``full`` is given)."""
    grease_name, grease_version = _grease(major)
    order = _ORDERS[major % 6]
    version = full if full else str(major)
    grease_ver = f"{grease_version}.0.0.0" if full else grease_version
    slots: list[dict[str, str] | None] = [None, None, None]
    slots[order[0]] = {"brand": grease_name, "version": grease_ver}
    slots[order[1]] = {"brand": "Chromium", "version": version}
    slots[order[2]] = {"brand": brand, "version": version}
    return [slot for slot in slots if slot is not None]


def build_user_agent(platform: str, major: int, brand: str = CHROME) -> str:
    token = UA_OS_TOKENS[platform]
    base = (
        f"Mozilla/5.0 ({token}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )
    if brand == EDGE:
        base += f" Edg/{major}.0.0.0"
    return base


def build_ua_metadata(
    platform: str,
    full_version: str,
    *,
    brand: str = CHROME,
    platform_version: str,
    architecture: str = "x86",
    bitness: str = "64",
) -> dict[str, Any]:
    """CDP ``userAgentMetadata`` for ``Emulation.setUserAgentOverride``."""
    major = chrome_major(full_version) or 0
    return {
        "brands": brand_list(major, brand),
        "fullVersionList": brand_list(major, brand, full=full_version),
        "fullVersion": full_version,
        "platform": HINTS_PLATFORM[platform],
        "platformVersion": platform_version,
        "architecture": architecture,
        "bitness": bitness,
        "model": "",
        "mobile": False,
        "wow64": False,
        "formFactors": ["Desktop"],
    }


def architecture_for(platform: str, renderer: str | None) -> str:
    """CPU architecture token implied by the platform / GPU."""
    if platform == "macos" and renderer and "Apple M" in renderer:
        return "arm"
    return "x86"


def language_list(language: str | None, locale: str | None) -> tuple[str, ...]:
    """Ordered ``navigator.languages``: region tag first, bare language next."""
    items: list[str] = []
    if locale:
        items.append(locale)
    if language:
        primary = language.split("-")[0]
        if primary and primary not in items:
            items.append(primary)
    if locale and "-" in locale:
        primary = locale.split("-")[0]
        if primary not in items:
            items.insert(1, primary)
    return tuple(items) or ("en-US", "en")
