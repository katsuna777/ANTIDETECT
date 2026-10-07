"""Per-profile protection switches: WebRTC mode, canvas / audio noise and the colour scheme of sites.

Stored as one JSON blob on the configuration (``privacy_settings``). A missing key means the
default, so a profile that never touched these keeps behaving as before.
"""

from __future__ import annotations

from typing import Any

#: WebRTC follows the proxy: blocked behind one (the real address would otherwise show next to the
#: proxy's), untouched without one (the address is the user's own, and calls work normally).
WEBRTC_AUTO = "auto"
#: Never lets WebRTC reach the network around the proxy, even without a proxy.
WEBRTC_BLOCK = "block"
#: Leaves WebRTC alone: calls work, the real address may be visible. For profiles that need calls.
WEBRTC_ALLOW = "allow"

WEBRTC_MODES = (WEBRTC_AUTO, WEBRTC_BLOCK, WEBRTC_ALLOW)

#: The colour scheme sites are told the profile prefers (``prefers-color-scheme``). Left alone it is the
#: host's, so every profile on a computer in dark mode shows the same "dark" bit; and a profile's own
#: choice does not change with the system's.
THEME_LIGHT = "light"
THEME_DARK = "dark"
#: Follow the system, as a normal browser does (what profiles made before this setting existed keep).
THEME_AUTO = "auto"
THEMES = (THEME_LIGHT, THEME_DARK, THEME_AUTO)

DEFAULTS: dict[str, Any] = {
    "webrtc": WEBRTC_AUTO,
    "noise_canvas": True,
    "noise_audio": True,
    "theme": THEME_LIGHT,       # the most common choice, and it does not depend on the computer
}


def validate(raw: Any) -> None:
    """Reject values the engine would not understand; unknown keys are rejected too."""
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError(f"privacy_settings must be an object, got {type(raw).__name__}")
    for key, value in raw.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown privacy setting {key!r}; known: {', '.join(DEFAULTS)}")
        if key == "webrtc":
            if value not in WEBRTC_MODES:
                raise ValueError(f"webrtc must be one of {', '.join(WEBRTC_MODES)}, got {value!r}")
        elif key == "theme":
            if value not in THEMES:
                raise ValueError(f"theme must be one of {', '.join(THEMES)}, got {value!r}")
        elif not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false, got {value!r}")


def resolve(raw: dict[str, Any] | None) -> dict[str, Any]:
    """The full set of switches: stored values over the defaults, nothing unknown or malformed."""
    result = dict(DEFAULTS)
    for key, value in (raw or {}).items():
        if key == "webrtc" and value in WEBRTC_MODES:
            result[key] = value
        elif key == "theme" and value in THEMES:
            result[key] = value
        elif key in ("noise_canvas", "noise_audio") and isinstance(value, bool):
            result[key] = value
    return result


def minimal(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Only what differs from the defaults: what gets stored, so an untouched profile stores nothing."""
    resolved = resolve(raw)
    return {key: value for key, value in resolved.items() if value != DEFAULTS[key]}
