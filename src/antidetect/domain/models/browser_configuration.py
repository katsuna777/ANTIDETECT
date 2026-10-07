from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


class BrowserConfiguration:
    """Browser runtime settings referenced by profiles.

    Every fingerprint-relevant parameter lives here. The scalar fields
    (``user_agent``, ``platform``, ``language``, ``locale``, ``timezone``,
    screen geometry, color depth) map directly on to Chromium command-line
    switches; the nested ``webgl_settings`` / ``hardware_settings`` /
    ``client_hints`` dicts are stored as opaque JSON and applied to the live
    renderer through the CDP stealth layer (``antidetect.infrastructure.stealth``),
    while still being validated and generated coherently with the rest of
    the fingerprint.
    """

    __slots__ = (
        "id",
        "name",
        "user_agent",
        "platform",
        "language",
        "locale",
        "timezone",
        "screen_width",
        "screen_height",
        "device_pixel_ratio",
        "color_depth",
        "webgl_settings",
        "hardware_settings",
        "client_hints",
        "privacy_settings",
        "created_at",
        "updated_at",
    )

    def __init__(
        self,
        id: int,
        name: str,
        user_agent: Optional[str] = None,
        platform: Optional[str] = None,
        language: Optional[str] = None,
        locale: Optional[str] = None,
        timezone: Optional[str] = None,
        screen_width: Optional[int] = None,
        screen_height: Optional[int] = None,
        device_pixel_ratio: Optional[float] = None,
        color_depth: Optional[int] = None,
        webgl_settings: Optional[dict[str, Any]] = None,
        hardware_settings: Optional[dict[str, Any]] = None,
        client_hints: Optional[dict[str, Any]] = None,
        privacy_settings: Optional[dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.user_agent = user_agent
        self.platform = platform
        self.language = language
        self.locale = locale
        self.timezone = timezone
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.device_pixel_ratio = device_pixel_ratio
        self.color_depth = color_depth
        self.webgl_settings = webgl_settings
        self.hardware_settings = hardware_settings
        self.client_hints = client_hints
        self.privacy_settings = privacy_settings
        self.created_at = created_at
        self.updated_at = updated_at

    def replace(self, **changes) -> "BrowserConfiguration":
        values = {
            "id": self.id,
            "name": self.name,
            "user_agent": self.user_agent,
            "platform": self.platform,
            "language": self.language,
            "locale": self.locale,
            "timezone": self.timezone,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "device_pixel_ratio": self.device_pixel_ratio,
            "color_depth": self.color_depth,
            "webgl_settings": self.webgl_settings,
            "hardware_settings": self.hardware_settings,
            "client_hints": self.client_hints,
            "privacy_settings": self.privacy_settings,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        values.update(changes)
        return BrowserConfiguration(**values)

    @property
    def language_tag(self) -> str | None:
        """Best value for Chromium's ``--lang`` switch.

        Prefers the full locale tag (e.g. ``en-US``) because that is what a real
        browser reports in ``navigator.language``; falls back to the primary
        language when only a short code was configured.
        """
        if self.locale:
            return self.locale
        return self.language

    def __repr__(self) -> str:
        return f"BrowserConfiguration(id={self.id}, name={self.name!r})"