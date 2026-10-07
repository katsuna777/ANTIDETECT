"""Chrome profile preferences we have to set *before* the browser starts.

WebRTC is the reason this module exists. ``--force-webrtc-ip-handling-policy`` is accepted by
Chrome 154 and does nothing (measured: with the switch, with the switch plus a proxy, and with
other policy values an ``RTCPeerConnection`` still returned the machine's real public address as
a ``srflx`` candidate, i.e. the address a proxy exists to hide). The same policy written to the
profile's ``Preferences`` file is honoured: the candidate list comes back empty.

``Preferences`` is a plain JSON file Chrome rewrites on exit, so it is only touched while the
profile is not running (the manager never starts a profile twice) and is replaced atomically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: Only UDP that goes through the proxy is allowed; with an HTTP proxy that means none, so no
#: reflexive (public) address is ever gathered. Calls still work over TCP.
WEBRTC_PROXY_ONLY = "disable_non_proxied_udp"

_WEBRTC = "webrtc"
_POLICY_KEY = "ip_handling_policy"


def policy_for(mode: str, has_proxy: bool) -> str | None:
    """Chrome policy for a profile's WebRTC mode (``None`` = Chrome's own default)."""
    from antidetect.application.fingerprint import privacy

    if mode == privacy.WEBRTC_BLOCK or (mode == privacy.WEBRTC_AUTO and has_proxy):
        return WEBRTC_PROXY_ONLY
    return None


def preferences_path(profile_path: Path) -> Path:
    return Path(profile_path) / "Default" / "Preferences"


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # missing, or damaged: Chrome would drop a damaged file anyway
    return data if isinstance(data, dict) else {}


def set_webrtc_policy(profile_path: Path, policy: str | None) -> None:
    """Make ``policy`` the profile's WebRTC IP handling policy; ``None`` restores Chrome's default.

    Written on every launch, not only when a proxy is first attached: a profile that used a proxy
    yesterday and none today must not keep yesterday's setting (calls would stay UDP-less for no
    reason), and one that gets a proxy today must be protected from the very first request.
    Raises ``OSError`` when the file cannot be written; the caller decides whether that is fatal.
    """
    path = preferences_path(profile_path)
    data = _load(path)
    webrtc = data.get(_WEBRTC)
    if not isinstance(webrtc, dict):
        webrtc = {}
    if policy is None:
        if _POLICY_KEY not in webrtc:
            return  # nothing to undo: leave a file Chrome wrote untouched
        webrtc.pop(_POLICY_KEY)
    else:
        if webrtc.get(_POLICY_KEY) == policy:
            return
        webrtc[_POLICY_KEY] = policy
    if webrtc:
        data[_WEBRTC] = webrtc
    else:
        data.pop(_WEBRTC, None)

    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".antidetect-tmp")
    try:
        scratch.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.replace(scratch, path)
    finally:
        try:
            scratch.unlink()
        except OSError:
            pass


def webrtc_policy(profile_path: Path) -> str | None:
    """The policy currently stored for the profile (for tests and diagnostics)."""
    webrtc = _load(preferences_path(profile_path)).get(_WEBRTC)
    return webrtc.get(_POLICY_KEY) if isinstance(webrtc, dict) else None
