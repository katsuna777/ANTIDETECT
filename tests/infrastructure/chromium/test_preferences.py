"""The profile's Preferences file: WebRTC policy written before Chrome starts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from antidetect.infrastructure.chromium import preferences as prefs


def _stored(profile: Path) -> dict:
    return json.loads(prefs.preferences_path(profile).read_text(encoding="utf-8"))


def test_policy_is_written_into_a_fresh_profile(tmp_path: Path):
    prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
    assert _stored(tmp_path) == {"webrtc": {"ip_handling_policy": "disable_non_proxied_udp"}}
    assert prefs.webrtc_policy(tmp_path) == "disable_non_proxied_udp"


def test_everything_else_chrome_stored_is_kept(tmp_path: Path):
    path = prefs.preferences_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"profile": {"name": "Shop"}, "webrtc": {"other": 1}, "intl": {"a": "b"}}))
    prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
    data = _stored(tmp_path)
    assert data["profile"] == {"name": "Shop"} and data["intl"] == {"a": "b"}
    assert data["webrtc"] == {"other": 1, "ip_handling_policy": "disable_non_proxied_udp"}


def test_clearing_restores_chromes_default_and_drops_an_empty_section(tmp_path: Path):
    prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
    prefs.set_webrtc_policy(tmp_path, None)
    assert prefs.webrtc_policy(tmp_path) is None
    assert "webrtc" not in _stored(tmp_path)


def test_clearing_keeps_the_other_webrtc_settings(tmp_path: Path):
    path = prefs.preferences_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"webrtc": {"ip_handling_policy": "x", "other": 1}}))
    prefs.set_webrtc_policy(tmp_path, None)
    assert _stored(tmp_path) == {"webrtc": {"other": 1}}


def test_a_profile_that_never_had_a_policy_is_not_created_or_touched(tmp_path: Path):
    prefs.set_webrtc_policy(tmp_path, None)
    assert not prefs.preferences_path(tmp_path).exists()           # no file made just to say "nothing"

    path = prefs.preferences_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"a": 1}  ')                                    # Chrome's own bytes stay as they were
    prefs.set_webrtc_policy(tmp_path, None)
    assert path.read_text() == '{"a": 1}  '


def test_setting_the_same_policy_again_does_not_rewrite_the_file(tmp_path: Path):
    prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
    path = prefs.preferences_path(tmp_path)
    path.write_text(path.read_text() + " ")                         # marker: a rewrite would remove it
    prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
    assert path.read_text().endswith(" ")


@pytest.mark.parametrize("content", ["", "{broken", "[1, 2]", "null"])
def test_a_damaged_file_is_replaced_by_one_that_works(tmp_path: Path, content: str):
    path = prefs.preferences_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(content)
    prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
    assert prefs.webrtc_policy(tmp_path) == "disable_non_proxied_udp"


def test_no_scratch_file_is_left_behind(tmp_path: Path):
    prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
    prefs.set_webrtc_policy(tmp_path, None)
    assert [p.name for p in prefs.preferences_path(tmp_path).parent.iterdir()] == ["Preferences"]


def test_an_unwritable_location_raises_oserror_for_the_caller_to_decide(tmp_path: Path):
    blocker = tmp_path / "Default"
    blocker.write_text("a file where the profile's Default folder should be")
    with pytest.raises(OSError):
        prefs.set_webrtc_policy(tmp_path, prefs.WEBRTC_PROXY_ONLY)
