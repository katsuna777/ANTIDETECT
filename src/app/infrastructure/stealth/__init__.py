"""Renderer stealth layer (Chrome DevTools Protocol).

Command-line switches can only spoof HTTP headers and a handful of prefs;
everything a live renderer reports (``navigator.platform``,
``navigator.userAgentData``, ``Sec-CH-UA``, WebGL vendor/renderer,
``hardwareConcurrency``) must be overridden over CDP *before* the first
navigation. See :mod:`app.infrastructure.stealth.cdp`.
"""

from app.infrastructure.stealth.cdp import (
    StealthDaemon,
    StealthSpec,
    apply_stealth,
    needs_stealth,
    spec_from_configuration,
    start_daemon,
)

__all__ = [
    "StealthDaemon",
    "StealthSpec",
    "apply_stealth",
    "needs_stealth",
    "spec_from_configuration",
    "start_daemon",
]
