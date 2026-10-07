"""Renderer stealth layer (Chrome DevTools Protocol).

Command-line switches only reach HTTP headers and a few prefs; everything a live
renderer reports (``navigator.platform``, ``userAgentData``, ``Sec-CH-UA``,
timezone, screen, WebGL, workers) is applied over CDP *before* a target's first
script runs. See :mod:`antidetect.infrastructure.stealth.cdp`.
"""

from antidetect.infrastructure.stealth.cdp import StealthDaemon, start_daemon
from antidetect.infrastructure.stealth.spec import StealthSpec, spec_from_configuration

__all__ = [
    "StealthDaemon",
    "StealthSpec",
    "spec_from_configuration",
    "start_daemon",
]
