from __future__ import annotations

import json
import os
import random
import subprocess
import time
from pathlib import Path

import pytest

from antidetect.application.fingerprint import data as fd
from antidetect.application.fingerprint.generator import ConfigurationGenerator
from antidetect.domain.errors import StealthError
from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.infrastructure.chromium.chromium_manager import ChromiumManager
from antidetect.infrastructure.stealth import cdp
from antidetect.infrastructure.stealth.spec import spec_from_configuration

BINARY = "154.0.8037.93"


def _config(platform: str = "windows", seed: int = 7, **overrides) -> BrowserConfiguration:
    params = ConfigurationGenerator(random.Random(seed)).generate_random(platform=platform)
    params.update(overrides)
    return BrowserConfiguration(id=2, name="win", **params)


def _spec(**config_overrides):
    return spec_from_configuration(
        _config(language="es", locale="es-ES", timezone="Europe/Madrid", **config_overrides),
        browser_version=BINARY,
        seed=42,
        host_platform="macos",
    )


class FakeConn:
    """Records every CDP call; optionally fails chosen methods."""

    def __init__(self, fail: set[str] | None = None, replies: dict | None = None) -> None:
        self.calls: list[tuple[str, dict, str | None]] = []
        self.fail = fail or set()
        self.replies = replies or {}
        self.closed = False

    def call(self, method, params=None, session_id=None, *, timeout=8.0, tolerate=False):
        self.calls.append((method, params or {}, session_id))
        if method in self.fail:
            if tolerate:
                return {}
            raise StealthError(f"CDP {method} rejected")
        return self.replies.get(method, {})

    def fire(self, method, params=None, session_id=None):
        self.calls.append((method, params or {}, session_id))

    def methods(self, session: str | None = None) -> list[str]:
        return [m for m, _, s in self.calls if session is None or s == session]

    def params(self, method: str) -> dict:
        return next(p for m, p, _ in self.calls if m == method)


def _daemon(spec=None, **kwargs) -> cdp.StealthDaemon:
    return cdp.StealthDaemon("ws://unused", spec or _spec(), **kwargs)


def _attached(target_type: str, url: str = "https://example.com/", waiting: bool = True, tid: str = "T1"):
    return {
        "sessionId": f"S-{tid}",
        "waitingForDebugger": waiting,
        "targetInfo": {"type": target_type, "url": url, "targetId": tid},
    }


# --------------------------------------------------------- page / iframe / worker


def test_page_gets_native_emulation_then_payload_then_resume():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("page"))
    methods = conn.methods("S-T1")
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"  # always last: nothing runs unpatched
    for needed in (
        "Emulation.setUserAgentOverride", "Emulation.setLocaleOverride",
        "Emulation.setTimezoneOverride", "Emulation.setHardwareConcurrencyOverride",
        "Emulation.setDeviceMetricsOverride", "Emulation.setGeolocationOverride",
        "Page.addScriptToEvaluateOnNewDocument", "Target.setAutoAttach",
    ):
        assert needed in methods, needed
    # Regression: without Page.enable the script is not injected into child frames.
    assert methods.index("Page.enable") < methods.index("Page.addScriptToEvaluateOnNewDocument")
    assert daemon.ready.is_set()


def test_the_colour_scheme_is_emulated_on_pages_natively_and_never_on_frames():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("page"))
    emulated = conn.params("Emulation.setEmulatedMedia")
    assert emulated == {"features": [{"name": "prefers-color-scheme", "value": "light"}]}
    frame = FakeConn()
    daemon._on_attached(frame, _attached("iframe", tid="F1"))
    assert "Emulation.setEmulatedMedia" not in frame.methods("S-F1")                      # frames inherit the page's


def test_a_profile_that_follows_the_system_gets_no_emulation_at_all():
    conn = FakeConn()
    _daemon(_spec(privacy_settings={"theme": "auto"}))._on_attached(conn, _attached("page"))
    assert "Emulation.setEmulatedMedia" not in conn.methods("S-T1")


def test_user_agent_override_is_native_complete_and_without_q_values():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("page"))
    ua = conn.params("Emulation.setUserAgentOverride")
    assert ua["platform"] == "Win32"
    assert ua["acceptLanguage"] == "es-ES,es" and ";q=" not in ua["acceptLanguage"]
    meta = ua["userAgentMetadata"]
    assert meta["platform"] == "Windows" and meta["fullVersion"] == BINARY
    assert meta["fullVersionList"] and meta["formFactors"] == ["Desktop"]
    assert "Chrome/154.0.0.0" in ua["userAgent"]


def test_device_metrics_keep_the_real_viewport():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("page"))
    metrics = conn.params("Emulation.setDeviceMetricsOverride")
    assert metrics["dontSetVisibleSize"] is True and metrics["width"] == 0 and metrics["height"] == 0
    assert metrics["mobile"] is False and metrics["screenWidth"] > 0


def test_nested_auto_attach_pauses_children_and_ignores_internal_targets():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("page"))
    nested = conn.params("Target.setAutoAttach")
    assert nested["waitForDebuggerOnStart"] is True and nested["flatten"] is True
    kinds = [f.get("type") for f in nested["filter"] if "type" in f]
    assert set(kinds) == {"page", "iframe", "worker", "shared_worker", "service_worker"}
    assert nested["filter"][-1] == {"exclude": True}  # browser_ui / other never paused


def test_iframe_is_patched_but_not_resized_or_relocated():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("iframe", tid="F1"))
    methods = conn.methods("S-F1")
    assert "Emulation.setUserAgentOverride" in methods
    assert "Page.addScriptToEvaluateOnNewDocument" in methods
    assert "Emulation.setDeviceMetricsOverride" not in methods
    assert "Emulation.setGeolocationOverride" not in methods
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"


def test_internal_tab_is_patched_because_the_user_navigates_away_from_it_in_place():
    """Regression: the first tab is chrome://newtab/. Typing an address there reuses the same
    target, so it must already carry the overrides — otherwise the page sees the real machine."""
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("page", url="chrome://newtab/", tid="NTP"))
    methods = conn.methods("S-NTP")
    for needed in ("Emulation.setUserAgentOverride", "Emulation.setHardwareConcurrencyOverride",
                   "Emulation.setDeviceMetricsOverride", "Page.addScriptToEvaluateOnNewDocument",
                   "Target.setAutoAttach"):
        assert needed in methods, needed
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"


def test_nested_internal_iframes_are_left_alone():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("iframe", url="chrome-untrusted://new-tab-page/", tid="NTPF"))
    methods = conn.methods("S-NTPF")
    assert "Emulation.setUserAgentOverride" not in methods
    assert "Page.addScriptToEvaluateOnNewDocument" not in methods
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"


def test_dedicated_worker_gets_the_payload_before_it_starts():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("worker", url="blob:https://example.com/x", tid="W1"))
    methods = conn.methods("S-W1")
    assert methods == ["Runtime.evaluate", "Runtime.runIfWaitingForDebugger"]
    expression = conn.params("Runtime.evaluate")["expression"]
    assert expression.rstrip().endswith(f"//# sourceURL={daemon._spec.token}")


def test_service_worker_is_resumed_first_because_paused_ones_never_answer_evaluate():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("service_worker", url="https://example.com/sw.js", tid="SW"))
    assert conn.methods("S-SW") == ["Runtime.runIfWaitingForDebugger", "Runtime.evaluate"]


def test_extension_workers_are_only_resumed():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(
        conn, _attached("service_worker", url="chrome-extension://abc/sw.js", tid="EXT")
    )
    assert conn.methods("S-EXT") == ["Runtime.runIfWaitingForDebugger"]


def test_a_failing_patch_never_leaves_the_target_paused():
    conn = FakeConn(fail={"Page.addScriptToEvaluateOnNewDocument"})
    daemon = _daemon()
    daemon._on_attached(conn, _attached("page"))
    assert conn.methods("S-T1")[-1] == "Runtime.runIfWaitingForDebugger"
    assert daemon.last_error and "addScript" in daemon.last_error.replace("Script", "Script")


def test_unpaused_targets_are_not_resumed():
    conn, daemon = FakeConn(), _daemon()
    daemon._on_attached(conn, _attached("page", waiting=False))
    assert "Runtime.runIfWaitingForDebugger" not in conn.methods("S-T1")


# ------------------------------------------------------------- windows & session


def test_window_is_shrunk_to_the_claimed_screen_only_when_it_exceeds_it():
    spec = _spec(screen_width=1366, screen_height=768, device_pixel_ratio=1.0)
    conn = FakeConn(replies={"Browser.getWindowForTarget": {
        "windowId": 7, "bounds": {"left": 22, "top": 47, "width": 1200, "height": 926},
    }})
    daemon = _daemon(spec)
    daemon._fit_window(conn, "T1")
    bounds = conn.params("Browser.setWindowBounds")["bounds"]
    assert bounds["width"] == 1200 and bounds["height"] == spec.screen.avail_height
    # Same window again: left alone.
    conn.calls.clear()
    daemon._fit_window(conn, "T1")
    assert not conn.calls or "Browser.setWindowBounds" not in conn.methods()

    roomy = FakeConn(replies={"Browser.getWindowForTarget": {
        "windowId": 8, "bounds": {"left": 0, "top": 0, "width": 900, "height": 600},
    }})
    _daemon(spec)._fit_window(roomy, "T2")
    assert "Browser.setWindowBounds" not in roomy.methods()


def test_session_is_written_restored_and_never_overwritten_by_an_empty_one(tmp_path: Path):
    daemon = _daemon(profile_path=tmp_path)
    daemon._track({"type": "page", "targetId": "a", "url": "https://one.example/"})
    daemon._track({"type": "page", "targetId": "b", "url": "https://two.example/x"})
    daemon._track({"type": "page", "targetId": "c", "url": "chrome://newtab/"})
    daemon._track({"type": "page", "targetId": "d", "url": "devtools://devtools/x"})
    daemon._write_session()
    saved = json.loads((tmp_path / ".antidetect-session.json").read_text())
    assert saved["urls"] == ["https://one.example/", "https://two.example/x"]

    daemon._pages.clear()  # everything closed
    daemon._write_session()
    assert json.loads((tmp_path / ".antidetect-session.json").read_text())["urls"] == saved["urls"]

    daemon._track({"type": "page", "targetId": "e", "url": "https://three.example/"})
    daemon.freeze()
    daemon._pages.clear()
    daemon._track({"type": "page", "targetId": "z", "url": "https://late.example/"})
    daemon._write_session()  # frozen: shutdown noise must not rewrite the snapshot
    assert "late.example" not in (tmp_path / ".antidetect-session.json").read_text()


def test_initial_tabs_open_start_url_first_then_restored_session(tmp_path: Path):
    (tmp_path / ".antidetect-session.json").write_text(
        json.dumps({"urls": ["https://a.example/", "chrome-error://x", "https://b.example/"]})
    )
    conn = FakeConn(replies={"Target.createTarget": {"targetId": "T"}})
    daemon = _daemon(profile_path=tmp_path, start_urls=["https://start.example/"])
    daemon._open_initial_tabs(conn)
    created = [p for m, p, _ in conn.calls if m == "Target.createTarget"]
    # Websites are created blank and loaded later (see the deferred-navigation tests).
    assert [c["url"] for c in created] == ["about:blank"] * 3
    assert created[0]["newWindow"] is True and created[1]["newWindow"] is False


def test_empty_profile_opens_a_new_tab_page(tmp_path: Path):
    conn = FakeConn(replies={"Target.createTarget": {"targetId": "T"}})
    _daemon(profile_path=tmp_path)._open_initial_tabs(conn)
    assert conn.params("Target.createTarget")["url"] == "chrome://newtab/"  # internal page: no request to leak


def test_a_website_is_only_requested_after_its_tab_is_patched_and_resumed():
    """Regression: a tab created with a URL sends its first request before DevTools can attach,
    so the server saw the real machine in Sec-CH-UA-Platform (2ip said macOS for a Windows profile)."""
    conn, daemon = FakeConn(replies={"Target.createTarget": {"targetId": "T9"}}), _daemon()
    daemon._create_tab(conn, "https://site.example/page", new_window=False, tolerate=True)
    assert conn.params("Target.createTarget")["url"] == "about:blank"
    assert not any(m == "Page.navigate" for m, _, _ in conn.calls)  # nothing requested yet
    daemon._on_attached(conn, _attached("page", url="about:blank", tid="T9"))
    methods = conn.methods("S-T9")
    assert methods.index("Emulation.setUserAgentOverride") < methods.index("Runtime.runIfWaitingForDebugger")
    assert methods.index("Runtime.runIfWaitingForDebugger") < methods.index("Page.navigate")
    assert methods[-1] == "Page.navigate"
    assert next(p for m, p, _ in conn.calls if m == "Page.navigate")["url"] == "https://site.example/page"
    # one-shot: attaching again (e.g. a re-attach) never navigates twice
    conn.calls.clear()
    daemon._on_attached(conn, _attached("page", url="https://site.example/page", tid="T9"))
    assert "Page.navigate" not in conn.methods()


def test_internal_and_non_http_urls_are_created_directly():
    conn, daemon = FakeConn(replies={"Target.createTarget": {"targetId": "T"}}), _daemon()
    daemon._create_tab(conn, "chrome://settings/", new_window=False, tolerate=True)
    assert conn.params("Target.createTarget")["url"] == "chrome://settings/" and daemon._deferred == {}


def test_requests_to_open_a_page_go_through_the_same_deferred_path():
    conn, daemon = FakeConn(replies={"Target.createTarget": {"targetId": "T5"}}), _daemon()
    daemon.request_open("https://check.example/")
    daemon._drain_open_requests(conn)
    assert conn.params("Target.createTarget")["url"] == "about:blank"
    assert daemon._deferred == {"T5": "https://check.example/"}
    assert "Target.activateTarget" in conn.methods()


def test_a_blank_tab_is_never_saved_into_the_restorable_session(tmp_path: Path):
    daemon = _daemon(profile_path=tmp_path)
    daemon._track({"type": "page", "targetId": "a", "url": "about:blank"})
    daemon._track({"type": "page", "targetId": "b", "url": "https://real.example/"})
    daemon._write_session()
    assert json.loads((tmp_path / ".antidetect-session.json").read_text()) == {"urls": ["https://real.example/"]}


def test_closing_the_last_tab_quits_the_browser_after_a_grace_period():
    conn, daemon = FakeConn(), _daemon()
    daemon._track({"type": "page", "targetId": "a", "url": "https://one.example/"})
    daemon._handle(conn, {"method": "Target.targetDestroyed", "params": {"targetId": "a"}})
    daemon._tick(conn)  # starts the grace timer
    assert "Browser.close" not in conn.methods()
    daemon._empty_since = time.monotonic() - 3.0
    daemon._tick(conn)
    assert "Browser.close" in conn.methods()


def test_a_new_tab_during_the_grace_period_cancels_the_quit():
    conn, daemon = FakeConn(), _daemon()
    daemon._track({"type": "page", "targetId": "a", "url": "https://one.example/"})
    daemon._pages.clear()
    daemon._tick(conn)
    daemon._track({"type": "page", "targetId": "b", "url": "https://two.example/"})
    daemon._tick(conn)
    assert daemon._empty_since is None and "Browser.close" not in conn.methods()


def test_discovery_reports_a_missing_endpoint(tmp_path: Path):
    with pytest.raises(StealthError, match="unreachable"):
        cdp.discover_browser_endpoint(tmp_path / "nope", timeout=0.3)


def test_stale_port_file_is_removed_before_launch(tmp_path: Path):
    (tmp_path / "DevToolsActivePort").write_text("12345\n/devtools/browser/x")
    cdp.clear_stale_port_file(tmp_path)
    assert not (tmp_path / "DevToolsActivePort").exists()
    cdp.clear_stale_port_file(tmp_path)  # idempotent


# ------------------------------------------------------- ChromiumManager wiring


class DummyDaemon:
    """Stand-in for StealthDaemon: records lifecycle calls, touches no network."""

    instances: list["DummyDaemon"] = []

    def __init__(self, *, ready_error: Exception | None = None) -> None:
        self.closed = False
        self.close_requested = False
        self.ready_error = ready_error
        DummyDaemon.instances.append(self)

    def wait_ready(self, timeout: float = 25.0) -> None:
        if self.ready_error is not None:
            raise self.ready_error

    def request_close(self) -> None:
        self.close_requested = True

    def close(self) -> None:
        self.closed = True


def _manager(fake_chromium: Path, tmp_path: Path, factory, **kwargs) -> ChromiumManager:
    return ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        stealth_factory=factory,
        stop_timeout=1.0,
        **kwargs,
    )


def _cmdline(pid: int) -> str:
    out = subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return out.stdout


@pytest.fixture()
def stealth_on(monkeypatch):
    """The suite disables stealth globally (stub binaries have no DevTools)."""
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)


def test_start_resolves_spec_from_the_real_binary_and_registers_daemon(
    fake_chromium: Path, tmp_path: Path, stealth_on
):
    DummyDaemon.instances.clear()
    seen: dict = {}

    def factory(profile_path, spec, **kwargs):
        seen.update(profile=profile_path, spec=spec, kwargs=kwargs)
        return DummyDaemon()

    manager = _manager(fake_chromium, tmp_path, factory)
    profile_dir = tmp_path / "stealth_ok"
    pid = manager.start(profile_dir, _config())
    try:
        assert seen["profile"] == profile_dir
        # The stub binary reports 152: the UA follows the browser, not the stored config.
        assert "Chrome/152.0.0.0" in seen["spec"].user_agent
        assert seen["kwargs"]["restore_session"] is True
        assert manager.is_running(profile_dir, pid)
        assert pid in manager._stealth_daemons
        assert (profile_dir / ".antidetect-seed").read_text().strip().isdigit()
    finally:
        manager.stop(profile_dir, pid)
    daemon = DummyDaemon.instances[0]
    assert daemon.close_requested and daemon.closed  # graceful quit first, then cleanup
    assert manager._stealth_daemons == {}


def test_profile_seed_is_stable_between_runs(fake_chromium: Path, tmp_path: Path, stealth_on):
    seeds = []

    def factory(profile_path, spec, **kwargs):
        seeds.append(spec.seed)
        return DummyDaemon()

    manager = _manager(fake_chromium, tmp_path, factory)
    profile_dir = tmp_path / "seeded"
    for _ in range(2):
        pid = manager.start(profile_dir, _config())
        manager.stop(profile_dir, pid)
    assert seeds[0] == seeds[1]
    other = tmp_path / "other"
    pid = manager.start(other, _config())
    manager.stop(other, pid)
    assert seeds[2] != seeds[0]


def test_start_url_is_handed_to_the_stealth_layer(fake_chromium: Path, tmp_path: Path, stealth_on):
    seen: dict = {}

    def factory(profile_path, spec, **kwargs):
        seen.update(kwargs)
        return DummyDaemon()

    manager = _manager(fake_chromium, tmp_path, factory)
    pid = manager.start(tmp_path / "p", _config(), start_url="https://start.example/")
    manager.stop(tmp_path / "p", pid)
    assert seen["start_urls"] == ["https://start.example/"]


def test_stealth_failure_kills_the_browser_and_raises(fake_chromium: Path, tmp_path: Path, stealth_on):
    def factory(profile_path, spec, **kwargs):
        return DummyDaemon(ready_error=StealthError("no DevTools endpoint"))

    manager = _manager(fake_chromium, tmp_path, factory)
    profile_dir = tmp_path / "stealth_fail"
    with pytest.raises(StealthError, match="no DevTools endpoint"):
        manager.start(profile_dir, _config())
    assert manager._processes == {} and manager._stealth_daemons == {}
    assert DummyDaemon.instances[-1].closed is True


def test_factory_exception_is_fail_closed(fake_chromium: Path, tmp_path: Path, stealth_on):
    def factory(profile_path, spec, **kwargs):
        raise StealthError("cannot attach")

    manager = _manager(fake_chromium, tmp_path, factory)
    with pytest.raises(StealthError, match="cannot attach"):
        manager.start(tmp_path / "boom", _config())
    assert manager._processes == {}


def test_stealth_launches_without_a_startup_window(fake_chromium: Path, tmp_path: Path, stealth_on):
    manager = _manager(fake_chromium, tmp_path, lambda *a, **k: DummyDaemon())
    profile_dir = tmp_path / "flags"
    pid = manager.start(profile_dir, _config())
    try:
        cmdline = _cmdline(pid)
        assert "--no-startup-window" in cmdline  # nothing may load before the layer attaches
        assert "--remote-debugging-port=0" in cmdline
        assert "--disable-blink-features=AutomationControlled" in cmdline
        # Chrome 154 ignores this switch (the real IP still leaked), so it must not be relied on.
        assert "--force-webrtc-ip-handling-policy" not in cmdline
        assert "--force-color-profile=srgb" in cmdline                # a Windows profile: sRGB, not the host's P3
        assert "--user-agent=" in cmdline and "--accept-lang=" in cmdline
    finally:
        manager.stop(profile_dir, pid)


def _proxy():
    from tests.support.fakes import make_proxy

    return make_proxy(1, host="203.0.113.7", port=3128)


def test_a_proxied_profile_gets_the_webrtc_policy_before_chrome_starts(fake_chromium: Path, tmp_path: Path, stealth_on):
    from antidetect.infrastructure.chromium import preferences

    manager = _manager(fake_chromium, tmp_path, lambda *a, **k: DummyDaemon(), proxy_probe=lambda p, t: True)
    profile_dir = tmp_path / "proxied"
    pid = manager.start(profile_dir, _config(), proxy=_proxy())
    try:
        assert preferences.webrtc_policy(profile_dir) == "disable_non_proxied_udp"
    finally:
        manager.stop(profile_dir, pid)


def test_a_profile_without_a_proxy_loses_a_policy_left_over_from_one(fake_chromium: Path, tmp_path: Path, stealth_on):
    from antidetect.infrastructure.chromium import preferences

    profile_dir = tmp_path / "was_proxied"
    preferences.set_webrtc_policy(profile_dir, preferences.WEBRTC_PROXY_ONLY)
    manager = _manager(fake_chromium, tmp_path, lambda *a, **k: DummyDaemon())
    pid = manager.start(profile_dir, _config())
    try:
        assert preferences.webrtc_policy(profile_dir) is None         # calls work again once the proxy is gone
    finally:
        manager.stop(profile_dir, pid)


def test_the_launch_is_refused_when_webrtc_cannot_be_protected_behind_a_proxy(
    fake_chromium: Path, tmp_path: Path, stealth_on, monkeypatch
):
    from antidetect.domain.errors import ChromiumError
    from antidetect.infrastructure.chromium import preferences

    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(preferences, "set_webrtc_policy", refuse)
    manager = _manager(fake_chromium, tmp_path, lambda *a, **k: DummyDaemon(), proxy_probe=lambda p, t: True)
    with pytest.raises(ChromiumError, match="protect WebRTC"):
        manager.start(tmp_path / "refused", _config(), proxy=_proxy())
    assert manager._processes == {}                                  # nothing was started

    pid = manager.start(tmp_path / "direct", _config())              # no proxy, nothing to protect: still starts
    manager.stop(tmp_path / "direct", pid)


@pytest.mark.parametrize(
    "mode, with_proxy, expected",
    [
        ("auto", True, "disable_non_proxied_udp"),
        ("auto", False, None),
        ("block", True, "disable_non_proxied_udp"),
        ("block", False, "disable_non_proxied_udp"),      # an explicit choice holds without a proxy too
        ("allow", True, None),                            # calls matter more to this profile
        ("allow", False, None),
    ],
)
def test_the_webrtc_mode_decides_the_policy(fake_chromium: Path, tmp_path: Path, stealth_on, mode, with_proxy, expected):
    from antidetect.infrastructure.chromium import preferences

    manager = _manager(fake_chromium, tmp_path, lambda *a, **k: DummyDaemon(), proxy_probe=lambda p, t: True)
    profile_dir = tmp_path / f"{mode}_{with_proxy}"
    pid = manager.start(
        profile_dir, _config(privacy_settings={"webrtc": mode}), proxy=_proxy() if with_proxy else None
    )
    try:
        assert preferences.webrtc_policy(profile_dir) == expected
    finally:
        manager.stop(profile_dir, pid)


def test_a_windows_profile_on_a_mac_gets_classic_scroll_bars_and_nothing_else_does(monkeypatch):
    from antidetect.infrastructure.chromium import chromium_manager as cm

    spec = lambda platform: type("S", (), {"platform_key": platform})()      # noqa: E731
    monkeypatch.setattr(fd, "host_platform", lambda: "macos")
    assert cm._scrollbar_arguments(spec("windows")) == ["-AppleShowScrollBars", "Always"]
    assert cm._scrollbar_arguments(spec("linux")) == ["-AppleShowScrollBars", "Always"]
    assert cm._scrollbar_arguments(spec("macos")) == []          # a Mac keeps what a Mac has
    assert cm._scrollbar_arguments(None) == []                   # no stealth layer: Chrome would open "Always" as a page

    monkeypatch.setattr(fd, "host_platform", lambda: "windows")
    assert cm._scrollbar_arguments(spec("windows")) == []        # classic already; the argument is Cocoa-only


def test_the_colour_profile_follows_the_claimed_display(fake_chromium: Path, tmp_path: Path, stealth_on):
    manager = _manager(fake_chromium, tmp_path, lambda *a, **k: DummyDaemon())
    for platform, expected in (("windows", "srgb"), ("linux", "srgb"), ("macos", "display-p3-d65")):
        profile_dir = tmp_path / f"color_{platform}"
        config = _config(platform, color_depth=fd.default_color_depth(platform, 2.0), device_pixel_ratio=2.0)
        pid = manager.start(profile_dir, config)
        try:
            assert f"--force-color-profile={expected}" in _cmdline(pid), platform
        finally:
            manager.stop(profile_dir, pid)


def test_disabled_stealth_never_calls_the_factory(fake_chromium: Path, tmp_path: Path):
    def factory(*a, **k):  # pragma: no cover
        raise AssertionError("stealth is disabled")

    manager = _manager(fake_chromium, tmp_path, factory, enable_stealth=False)
    profile_dir = tmp_path / "off"
    pid = manager.start(profile_dir, _config())
    try:
        assert "--no-startup-window" not in _cmdline(pid)
    finally:
        manager.stop(profile_dir, pid)


def test_env_switch_disables_stealth(fake_chromium: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTIDETECT_DISABLE_STEALTH", "1")

    def factory(*a, **k):  # pragma: no cover
        raise AssertionError("stealth is disabled")

    manager = _manager(fake_chromium, tmp_path, factory)
    pid = manager.start(tmp_path / "envoff", _config())
    manager.stop(tmp_path / "envoff", pid)


def test_migration_0006_purges_legacy_and_keeps_default(db):
    columns = {row["name"] for row in db.execute("PRAGMA table_info(browser_configurations)")}
    assert "client_hints" in columns
    db.execute(
        "INSERT INTO browser_configurations (name, user_agent, created_at, updated_at) "
        "VALUES ('legacy', 'Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36', 'now', 'now')"
    )
    db.commit()
    import importlib

    module = importlib.import_module(
        "antidetect.infrastructure.database.migrations.versions.0006_client_hints"
    )
    with db.transaction() as conn:
        module.upgrade(conn)
    names = {row["name"] for row in db.execute("SELECT name FROM browser_configurations")}
    assert "legacy" not in names
    assert "default" in names


# ------------------------------------------------------------------- live browser

_LIVE = pytest.mark.skipif(
    os.environ.get("ANTIDETECT_LIVE_BROWSER") != "1",
    reason="needs a real Chrome (set ANTIDETECT_LIVE_BROWSER=1)",
)
_DATA = Path(__file__).parent / "data"


def _probe_server():
    """Local pages for the cross-realm checks (iframe / popup / SW / shared worker)."""
    import http.server
    import socketserver
    import threading

    probe = r"""
async function probe() {
  const o = { ua: navigator.userAgent, platform: navigator.platform, cores: navigator.hardwareConcurrency, mem: navigator.deviceMemory,
    langs: JSON.stringify(navigator.languages), tz: Intl.DateTimeFormat().resolvedOptions().timeZone, locale: Intl.DateTimeFormat().resolvedOptions().locale };
  if (navigator.userAgentData) o.uadPlatform = navigator.userAgentData.platform;
  try { const c = (typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(2, 2) : document.createElement('canvas')).getContext('webgl');
    const e = c.getExtension('WEBGL_debug_renderer_info'); o.glRenderer = c.getParameter(e.UNMASKED_RENDERER_WEBGL); o.glVendor = c.getParameter(e.UNMASKED_VENDOR_WEBGL); } catch (err) { o.glErr = String(err); }
  if (typeof screen !== 'undefined') o.screen = [screen.width, screen.height, screen.availWidth, screen.availHeight, devicePixelRatio];
  try { if (navigator.gpu) { const a = await navigator.gpu.requestAdapter(); o.gpu = a ? a.info.vendor + '/' + a.info.architecture : 'none'; } else o.gpu = 'no navigator.gpu'; } catch (err) { o.gpu = 'err'; }
  try { o.conn = navigator.connection ? navigator.connection.effectiveType + '/' + navigator.connection.rtt + '/' + navigator.connection.downlink : 'none'; } catch (err) { o.conn = 'err'; }
  try { o.quota = navigator.storage ? (await navigator.storage.estimate()).quota : 'none'; } catch (err) { o.quota = 'err'; }
  return o;
}
"""
    frame = ("<!doctype html><title>f</title><script>" + probe +
             "\n(async()=>{ const o = await probe(); try{ (window.opener||parent).postMessage({probe:o}, '*'); }catch(e){} })();</script>").encode()
    sw = (probe + "\nself.addEventListener('message', async e => { e.source.postMessage({probe: await probe()}); });"
          "\nself.addEventListener('install', () => self.skipWaiting()); self.addEventListener('activate', e => e.waitUntil(clients.claim()));").encode()
    shared = (probe + "\nonconnect = async e => { const p = e.ports[0]; p.postMessage({probe: await probe()}); };").encode()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            ctype = "text/html"
            if path == "/frame":
                body = frame
            elif path == "/sw.js":
                body, ctype = sw, "text/javascript"
            elif path == "/shared.js":
                body, ctype = shared, "text/javascript"
            else:
                body = b"<!doctype html><title>leaktest</title><body>ok</body>"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if path == "/sw.js":
                self.send_header("Service-Worker-Allowed", "/")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _evaluate_on_new_tab(profile_dir: Path, url: str, expression: str, wait: float = 4.0):
    from antidetect.infrastructure.stealth.cdp import _CdpConnection, discover_browser_endpoint

    browser = _CdpConnection(discover_browser_endpoint(profile_dir, timeout=20))
    try:
        target = browser.call("Target.createTarget", {"url": url})["targetId"]
        session = browser.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        time.sleep(wait)
        reply = browser.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True, "userGesture": True},
            session,
            timeout=90,
        )
        return reply["result"]["value"]
    finally:
        browser.close()


@_LIVE
@pytest.mark.parametrize("platform", ["windows", "macos", "linux"])
def test_live_spoof_survives_every_detector_check(tmp_path: Path, platform: str, monkeypatch):
    """Production path on a real Chrome: the first tab, iframes, popups and every
    worker kind must agree with the claimed machine, with no tampering tells."""
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    from antidetect.infrastructure.chromium.paths import discover_chromium

    server = _probe_server()
    manager = ChromiumManager(chromium_path=discover_chromium(), logs_dir=tmp_path / "logs")
    profile_dir = tmp_path / f"live_{platform}"
    pid = manager.start(profile_dir, _config(platform))
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        results = json.loads(_evaluate_on_new_tab(profile_dir, url, (_DATA / "leaktest.js").read_text()))
        failures = {k: v["detail"] for k, v in results.items() if not k.startswith("_") and not v["ok"]}
        assert failures == {}
        lies = json.loads(_evaluate_on_new_tab(profile_dir, url, (_DATA / "liebattery.js").read_text(), wait=2.0))
        assert lies == {}  # no API reports "failed toString / illegal error / ..."
    finally:
        manager.stop(profile_dir, pid)
        server.shutdown()


@_LIVE
def test_live_stop_is_fast_and_session_is_restored(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    from antidetect.infrastructure.chromium.paths import discover_chromium
    from antidetect.infrastructure.stealth.cdp import _CdpConnection, discover_browser_endpoint

    server = _probe_server()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    manager = ChromiumManager(chromium_path=discover_chromium(), logs_dir=tmp_path / "logs")
    profile_dir = tmp_path / "live_session"
    config = _config()

    def pages() -> list[str]:
        conn = _CdpConnection(discover_browser_endpoint(profile_dir, timeout=20))
        try:
            infos = conn.call("Target.getTargets")["targetInfos"]
            return sorted(i["url"] for i in infos if i["type"] == "page")
        finally:
            conn.close()

    pid = manager.start(profile_dir, config)
    try:
        conn = _CdpConnection(discover_browser_endpoint(profile_dir, timeout=20))
        conn.call("Target.createTarget", {"url": base + "/?a=1"})
        time.sleep(1.5)
        conn.close()
        started = time.monotonic()
        manager.stop(profile_dir, pid)
        assert time.monotonic() - started < 3.0  # Browser.close, not a 5 s SIGTERM wait
        pid = manager.start(profile_dir, config)
        time.sleep(2.0)
        assert base + "/?a=1" in pages()
    finally:
        manager.stop(profile_dir, pid)
        server.shutdown()


@_LIVE
def test_live_first_tab_navigated_in_place_is_still_spoofed(tmp_path: Path, monkeypatch):
    """What a user does: start a profile (no start page -> New Tab), type an address into that
    same tab. The page must see the claimed machine, not the host."""
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    from antidetect.infrastructure.chromium.paths import discover_chromium
    from antidetect.infrastructure.stealth.cdp import _CdpConnection, discover_browser_endpoint

    other = next(p for p in ("windows", "linux", "macos") if p != fd.host_platform())
    server = _probe_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    manager = ChromiumManager(chromium_path=discover_chromium(), logs_dir=tmp_path / "logs")
    profile_dir = tmp_path / "live_inplace"
    pid = manager.start(profile_dir, _config(other))
    try:
        conn = _CdpConnection(discover_browser_endpoint(profile_dir, timeout=20))
        try:
            tab = next(i for i in conn.call("Target.getTargets")["targetInfos"] if i["type"] == "page")
            assert tab["url"].startswith("chrome://newtab")
            session = conn.call("Target.attachToTarget", {"targetId": tab["targetId"], "flatten": True})["sessionId"]
            conn.call("Page.enable", {}, session)
            conn.call("Page.navigate", {"url": url}, session, timeout=30.0)    # a hosted Windows runner is slow here
            time.sleep(3.0)
            seen = json.loads(conn.call(
                "Runtime.evaluate",
                {"expression": "JSON.stringify({p: navigator.platform, u: navigator.userAgentData.platform, "
                               "ua: navigator.userAgent})", "returnByValue": True},
                session,
            )["result"]["value"])
        finally:
            conn.close()
        expected = fd.NAVIGATOR_PLATFORM[other]
        assert seen["p"] == expected and seen["u"] == {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[other]
    finally:
        manager.stop(profile_dir, pid)
        server.shutdown()


@_LIVE
def test_live_the_first_request_of_every_tab_we_open_carries_the_claimed_platform(tmp_path: Path, monkeypatch):
    """The server side of the story: Sec-CH-UA-Platform of the very first request, for tabs opened by
    open_url, as a start page, and as restored tabs after a restart."""
    import http.server
    import socketserver
    import threading

    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    from antidetect.infrastructure.chromium.paths import discover_chromium

    other = next(p for p in ("windows", "linux", "macos") if p != fd.host_platform())
    expected = '"' + {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[other] + '"'
    seen: dict[str, str | None] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if not self.path.startswith("/favicon"):
                seen[self.path] = self.headers.get("Sec-CH-UA-Platform")
            body = b"<!doctype html><title>x</title>hi"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    manager = ChromiumManager(chromium_path=discover_chromium(), logs_dir=tmp_path / "logs")
    profile_dir = tmp_path / "live_headers"
    config = _config(other)
    pid = manager.start(profile_dir, config, start_url=base + "/start-page")
    try:
        time.sleep(2.0)
        assert manager.open_url(pid, base + "/open-url")
        time.sleep(3.0)
    finally:
        manager.stop(profile_dir, pid)
    pid = manager.start(profile_dir, config, start_url=base + "/second-start")  # + restored tabs
    try:
        time.sleep(4.0)
    finally:
        manager.stop(profile_dir, pid)
        server.shutdown()
    assert {"/start-page", "/open-url", "/second-start"} <= set(seen)
    assert {path: value for path, value in seen.items() if value != expected} == {}, seen


_WEBRTC_PROBE = r"""
(async () => {
  const out = [];
  const pc = new RTCPeerConnection({iceServers: [{urls: ['stun:stun.l.google.com:19302', 'stun:stun1.l.google.com:19302']}]});
  pc.createDataChannel('x');
  await new Promise(done => {
    pc.onicecandidate = e => { if (e.candidate) out.push(e.candidate.type); else done(); };
    pc.createOffer().then(o => pc.setLocalDescription(o));
    setTimeout(done, 6000);
  });
  return JSON.stringify(out);
})()
"""


@_LIVE
def test_live_webrtc_does_not_reveal_the_real_address_behind_a_proxy(tmp_path: Path, monkeypatch):
    """A STUN server answers a WebRTC page with the address it was reached from: through UDP that
    bypasses the proxy, the real one. ``--force-webrtc-ip-handling-policy`` did not prevent that on
    Chrome 154; the policy in the profile's Preferences does."""
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    from antidetect.infrastructure.chromium.paths import discover_chromium
    from tests.support.fakes import make_proxy

    server = _probe_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/"          # loopback is never sent through a proxy

    def candidate_types(name: str, proxy) -> list[str]:
        manager = ChromiumManager(
            chromium_path=discover_chromium(), logs_dir=tmp_path / "logs", proxy_probe=lambda p, t: True
        )
        profile_dir = tmp_path / name
        pid = manager.start(profile_dir, _config("windows"), proxy=proxy)
        try:
            return json.loads(_evaluate_on_new_tab(profile_dir, url, _WEBRTC_PROBE, wait=3.0))
        finally:
            manager.stop(profile_dir, pid)

    try:
        direct = candidate_types("direct", None)
        if "srflx" not in direct:
            pytest.skip("no STUN server reachable: silence could not be told from protection")
        proxied = candidate_types("proxied", make_proxy(1, host="127.0.0.1", port=9))
        assert "srflx" not in proxied and "relay" not in proxied, proxied
    finally:
        server.shutdown()


@_LIVE
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_live_the_colour_scheme_is_the_profiles_own_not_the_systems(tmp_path: Path, monkeypatch, theme):
    """The first tab goes New Tab -> website in place (the renderer changes process, which drops some CDP
    overrides), then a frame and a second tab are asked too. All must answer the profile's scheme, whatever
    the computer is set to (a "light" profile on a dark Mac is the case that proves it)."""
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    from antidetect.infrastructure.chromium.paths import discover_chromium
    from antidetect.infrastructure.stealth.cdp import _CdpConnection, discover_browser_endpoint

    server = _probe_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    manager = ChromiumManager(chromium_path=discover_chromium(), logs_dir=tmp_path / "logs")
    profile_dir = tmp_path / f"live_scheme_{theme}"
    pid = manager.start(profile_dir, _config("windows", privacy_settings={"theme": theme}))
    ask = (
        "(async () => { const dark = w => w.matchMedia('(prefers-color-scheme: dark)').matches;"
        " const f = document.createElement('iframe'); f.src = '/frame'; document.body.appendChild(f);"
        " await new Promise(r => f.onload = r);"
        " return JSON.stringify({page: dark(window), frame: dark(f.contentWindow)}); })()"
    )
    try:
        conn = _CdpConnection(discover_browser_endpoint(profile_dir, timeout=20))
        try:
            tab = next(i for i in conn.call("Target.getTargets")["targetInfos"] if i["type"] == "page")
            session = conn.call("Target.attachToTarget", {"targetId": tab["targetId"], "flatten": True})["sessionId"]
            conn.call("Page.enable", {}, session)
            conn.call("Page.navigate", {"url": url}, session)
            time.sleep(3.0)
            first = json.loads(conn.call("Runtime.evaluate", {"expression": ask, "awaitPromise": True, "returnByValue": True},
                                         session, timeout=30)["result"]["value"])
        finally:
            conn.close()
        second = json.loads(_evaluate_on_new_tab(profile_dir, url, ask, wait=3.0))
        expected = theme == "dark"
        assert first == {"page": expected, "frame": expected}
        assert second == {"page": expected, "frame": expected}
    finally:
        manager.stop(profile_dir, pid)
        server.shutdown()
