"""Speech-synthesis voices: the host's own are never shown, the default matches the profile language."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from antidetect.application.fingerprint.generator import COUNTRY_DEFAULTS
from antidetect.infrastructure.chromium.chromium_manager import ChromiumManager
from antidetect.infrastructure.stealth import voices
from antidetect.infrastructure.stealth.spec import spec_from_configuration
from tests.infrastructure.stealth.test_stealth_cdp import BINARY, _config, _probe_server

LOCALES = sorted({entry[1] for entry in COUNTRY_DEFAULTS.values()})
MAC_ONLY = {"Zarvox", "Trinoids", "Albert", "Fred", "Bad News", "Cellos", "Whisper", "Samantha"}


def _primary(tag: str) -> str:
    return tag.split("-")[0].lower()


@pytest.mark.parametrize("platform", ["windows", "macos", "linux"])
@pytest.mark.parametrize("locale", LOCALES)
def test_at_most_one_default_voice_and_it_speaks_the_profile_language(platform, locale):
    listed = voices.voices_for(platform, locale)
    defaults = [v for v in listed if v[3]]
    assert len(defaults) <= 1
    assert all(v[2] for v in defaults), "the default voice is a local one"
    if platform != "linux":
        assert len(defaults) == 1, f"{platform} {locale}: a system voice must exist for the UI language"
        assert _primary(defaults[0][1]) == _primary(locale)  # CreepJS compares exactly this
    else:
        assert defaults == []  # Linux Chrome has no local voices to be the default


@pytest.mark.parametrize("platform", ["windows", "macos", "linux"])
def test_lists_have_the_shape_chrome_returns(platform):
    listed = voices.voices_for(platform, "de-DE")
    names = [v[0] for v in listed]
    assert len(names) == len(set(names)), "voice names are unique"
    local = [v for v in listed if v[2]]
    remote = [v for v in listed if not v[2]]
    assert listed == local + remote, "local voices first, then the remote Google ones"
    assert [v[0] for v in remote] == [name for name, _ in voices.GOOGLE_VOICES]
    assert all(v[1] and "-" in v[1] for v in listed)


def test_a_windows_profile_never_lists_macos_voices_and_vice_versa():
    windows = {v[0] for v in voices.voices_for("windows", "en-US")}
    mac = {v[0] for v in voices.voices_for("macos", "en-US")}
    assert not windows & MAC_ONLY and all(name.startswith(("Microsoft ", "Google")) for name in windows)
    assert MAC_ONLY <= mac and not any(name.startswith("Microsoft ") for name in mac)


def test_the_macos_list_has_the_size_of_a_real_macos_15_chrome():
    local = [v for v in voices.voices_for("macos", "en-US") if v[2]]
    assert len(local) == 191  # measured on Chrome 154 / macOS 15
    assert sum(1 for v in voices.voices_for("macos", "en-US")) == 191 + len(voices.GOOGLE_VOICES)


def test_unknown_locale_falls_back_to_no_default_instead_of_a_wrong_one():
    for platform in ("windows", "macos"):
        assert [v for v in voices.voices_for(platform, "xx-XX") if v[3]] == []


def test_the_spec_carries_the_voices_for_the_claimed_platform_and_locale():
    spec = spec_from_configuration(
        _config(platform="windows", language="de", locale="de-DE", timezone="Europe/Berlin"),
        browser_version=BINARY, seed=42, host_platform="macos",
    )
    payload = spec.js_config()
    assert payload["voices"] and spec.voices == tuple(payload["voices"])
    defaults = [v for v in payload["voices"] if v["d"]]
    assert [v["n"] for v in defaults] == ["Microsoft Hedda - German (Germany)"]
    assert set(payload["voices"][0]) == {"n", "l", "s", "d"}


# ------------------------------------------------------------------- live browser

_LIVE = pytest.mark.skipif(
    os.environ.get("ANTIDETECT_LIVE_BROWSER") != "1",
    reason="needs a real Chrome (set ANTIDETECT_LIVE_BROWSER=1)",
)


@_LIVE
@pytest.mark.parametrize("platform", ["windows", "linux", "macos"])
def test_live_voices_follow_the_claimed_machine(tmp_path: Path, platform: str, monkeypatch):
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    from antidetect.infrastructure.chromium.paths import discover_chromium
    from tests.infrastructure.stealth.test_stealth_cdp import _evaluate_on_new_tab

    server = _probe_server()
    manager = ChromiumManager(chromium_path=discover_chromium(), logs_dir=tmp_path / "logs")
    profile_dir = tmp_path / f"voices_{platform}"
    config = _config(platform)
    config.locale, config.language = "de-DE", "de"
    pid = manager.start(profile_dir, config)
    expression = """(async () => {
      const proto = SpeechSynthesisVoice.prototype;
      const list = speechSynthesis.getVoices();
      const v = list[0];
      const u = new SpeechSynthesisUtterance('x');
      let setError = null;
      try { u.voice = v; } catch (e) { setError = String(e); }
      const nameDesc = Object.getOwnPropertyDescriptor(proto, 'name');
      let badReceiver = null;
      try { nameDesc.get.call({}); } catch (e) { badReceiver = e.constructor.name + ': ' + e.message; }
      return JSON.stringify({
        n: list.length, names: list.map(x => x.name), defaults: list.filter(x => x.default).map(x => [x.name, x.lang, x.localService]),
        inst: v instanceof SpeechSynthesisVoice, tag: Object.prototype.toString.call(v), own: Object.getOwnPropertyNames(v),
        getterSrc: Function.prototype.toString.call(nameDesc.get), getVoicesSrc: Function.prototype.toString.call(speechSynthesis.getVoices),
        setError, assigned: u.voice === v, badReceiver, intl: Intl.DateTimeFormat().resolvedOptions().locale,
      });
    })()"""
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        seen = json.loads(_evaluate_on_new_tab(profile_dir, url, expression))
    finally:
        manager.stop(profile_dir, pid)
        server.shutdown()
    expected = voices.voices_for(platform, "de-DE")
    assert seen["names"] == [v[0] for v in expected]  # exactly the claimed machine's list, none of the host's
    assert [(n, l, s) for n, l, s, d in expected if d] == [tuple(x) for x in seen["defaults"]]
    assert seen["inst"] and seen["tag"] == "[object SpeechSynthesisVoice]" and seen["own"] == []
    assert seen["getterSrc"] == "function get name() { [native code] }"
    assert seen["getVoicesSrc"] == "function getVoices() { [native code] }"
    assert seen["setError"] is None and seen["assigned"] is True
    assert seen["badReceiver"] and "Illegal invocation" in seen["badReceiver"]
    assert seen["intl"] == "de-DE"
