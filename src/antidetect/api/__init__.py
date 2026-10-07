"""Local HTTP API: lets scripts create, start and stop profiles and connect Playwright, Puppeteer or Selenium to them.

The names below load on first use, so importing this package (the GUI does, to read the settings)
does not pull the HTTP server in until the API is actually switched on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from antidetect.api.settings import DEFAULT_PORT, HOST, ApiKey, ApiKeyError, ApiSettings

if TYPE_CHECKING:
    from antidetect.api.manager import ApiManager, ApiStartError

__all__ = ["ApiKey", "ApiKeyError", "ApiManager", "ApiSettings", "ApiStartError", "DEFAULT_PORT", "HOST"]


def __getattr__(name: str):
    if name in ("ApiManager", "ApiStartError"):
        from antidetect.api import manager

        return getattr(manager, name)
    raise AttributeError(f"module 'antidetect.api' has no attribute {name!r}")
