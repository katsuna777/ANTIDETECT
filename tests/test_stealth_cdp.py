from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.application.configuration_generator import (
    ConfigurationGenerator,
    build_client_hints,
    validate_draft,
)
from app.domain.errors import StealthError
from app.domain.models.browser_configuration import BrowserConfiguration
from app.infrastructure.chromium.chromium_manager import ChromiumManager
from app.infrastructure.stealth.cdp import (
    _stealth_js,
    apply_stealth,
    discover_browser_endpoint,
    discover_page_target,
    discover_page_targets,
    needs_stealth,
    spec_from_configuration,
)


def _spoofed_config() -> BrowserConfiguration:
    params = ConfigurationGenerator().generate_from_template("windows-chrome")
    return BrowserConfiguration(id=2, name="win", **params)


def test_needs_stealth_false_for_bare_default():
    assert needs_stealth(BrowserConfiguration(id=1, name="default")) is False


def test_needs_stealth_true_for_spoofed():
    assert needs_stealth(_spoofed_config()) is True


def test_spec_maps_windows_platform_and_hints():
    spec = spec_from_configuration(_spoofed_config())
    assert spec is not None
    assert spec.js_platform == "Win32"
    assert spec.hints_platform == "Windows"
    assert spec.full_version.startswith("152.")
    assert spec.webgl_renderer and "Direct3D11" in spec.webgl_renderer
    assert "en-US" in spec.languages


def test_spec_requires_user_agent_when_renderer_spoofed():
    cfg = BrowserConfiguration(
        id=9, name="broken", webgl_settings={"vendor": "V", "renderer": "R"}
    )
    with pytest.raises(StealthError):
        spec_from_configuration(cfg)


def test_validate_rejects_legacy_chrome_124():
    with pytest.raises(ValueError, match="legacy"):
        validate_draft({"user_agent": "Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36"})


def test_validate_rejects_ua_hints_major_mismatch():
    hints = build_client_hints("chrome", "windows", "152.0.0.0")
    with pytest.raises(ValueError, match="mismatches client_hints"):
        validate_draft(
            {
                "user_agent": "Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36",
                "platform": "windows",
                "client_hints": hints,
            }
        )


def test_validate_rejects_windows_apple_webgl():
    with pytest.raises(ValueError, match="mismatches WebGL"):
        validate_draft(
            {
                "user_agent": "Mozilla/5.0 Chrome/152.0.0.0 Safari/537.36",
                "platform": "windows",
                "webgl_settings": {
                    "vendor": "Google Inc. (Apple)",
                    "renderer": "ANGLE (Apple, Apple M2, OpenGL 4.1)",
                },
            }
        )


def test_stealth_js_embeds_overrides():
    js = _stealth_js(spec_from_configuration(_spoofed_config()))
    for token in ("webdriver", "userAgentData", "hardwareConcurrency", "0x9246", "Win32"):
        assert token in js


def test_apply_stealth_skips_bare_configuration(tmp_path: Path):
    assert apply_stealth(tmp_path, BrowserConfiguration(id=1, name="default")) == {
        "skipped": True
    }


def test_discover_page_target_missing_file_raises(tmp_path: Path):
    with pytest.raises(StealthError, match="DevTools port file"):
        discover_page_target(tmp_path / "nope", timeout=0.3)


class DummyDaemon:
    """Stand-in for StealthDaemon: records close() without any network."""

    instances: list["DummyDaemon"] = []

    def __init__(self) -> None:
        self.closed = False
        DummyDaemon.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _dummy_daemon_factory(profile_path, configuration):
    return DummyDaemon()


def test_start_applies_stealth_and_registers(fake_chromium: Path, tmp_path: Path):
    DummyDaemon.instances.clear()
    seen: dict = {}

    def recorder(profile_path, configuration):
        seen["profile"] = profile_path
        seen["config"] = configuration
        return {"userAgent": True}

    manager = ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        stealth_applier=recorder,
        stealth_daemon_factory=_dummy_daemon_factory,
    )
    profile_dir = tmp_path / "stealth_ok"
    pid = manager.start(profile_dir, _spoofed_config())
    try:
        assert seen["profile"] == profile_dir
        assert manager.is_running(profile_dir, pid) is True
        assert len(DummyDaemon.instances) == 1
        assert pid in manager._stealth_daemons
    finally:
        manager.stop(profile_dir, pid)
    assert DummyDaemon.instances[0].closed is True
    assert manager._stealth_daemons == {}


def test_daemon_factory_failure_kills_process(fake_chromium: Path, tmp_path: Path):
    def exploding(_profile_path, _configuration):
        raise StealthError("no browser endpoint")

    manager = ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        stealth_applier=lambda _p, _c: {"userAgent": True},
        stealth_daemon_factory=exploding,
    )
    profile_dir = tmp_path / "daemon_fail"
    with pytest.raises(StealthError, match="no browser endpoint"):
        manager.start(profile_dir, _spoofed_config())
    assert manager._processes == {}
    assert manager._stealth_daemons == {}


def test_start_kills_process_when_stealth_fails(fake_chromium: Path, tmp_path: Path):
    def failing(_profile_path, _configuration):
        raise StealthError("no DevTools endpoint")

    manager = ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        stealth_applier=failing,
    )
    profile_dir = tmp_path / "stealth_fail"
    with pytest.raises(StealthError, match="no DevTools endpoint"):
        manager.start(profile_dir, _spoofed_config())
    assert manager.is_running(profile_dir, None) is False
    assert manager._processes == {}


def test_start_skips_stealth_for_bare_config(fake_chromium: Path, tmp_path: Path):
    def exploding(_profile_path, _configuration):  # pragma: no cover
        raise AssertionError("must not be called for bare configs")

    manager = ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        stealth_applier=exploding,
    )
    profile_dir = tmp_path / "bare_ok"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        assert manager.is_running(profile_dir, pid) is True
    finally:
        manager.stop(profile_dir, pid)


def test_launch_flags_are_stealth_allowlisted(fake_chromium: Path, tmp_path: Path):
    manager = ChromiumManager(
        chromium_path=fake_chromium, logs_dir=tmp_path / "logs", enable_stealth=False
    )
    profile_dir = tmp_path / "flags"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        cmdline = _cmdline(pid)
        # Bare ephemeral port (binds 127.0.0.1 — verified via lsof); the
        # host:port form is ignored by Chrome and DevTools never starts.
        assert "--remote-debugging-port=0" in cmdline
        assert "127.0.0.1:0" not in cmdline
        assert "--disable-blink-features=AutomationControlled" in cmdline
        assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in cmdline
    finally:
        manager.stop(profile_dir, pid)


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
        "app.infrastructure.database.migrations.versions.0006_client_hints"
    )
    with db.transaction() as conn:
        module.upgrade(conn)
    names = {row["name"] for row in db.execute("SELECT name FROM browser_configurations")}
    assert "legacy" not in names
    assert "default" in names


def test_daemon_is_none_for_bare_configuration(tmp_path: Path):
    from app.infrastructure.stealth.cdp import start_daemon

    assert (
        start_daemon(tmp_path, BrowserConfiguration(id=1, name="default")) is None
    )


_LIVE_BROWSER = pytest.mark.skipif(
    __import__("os").environ.get("ANTIDETECT_LIVE_BROWSER") != "1",
    reason="needs a real Chrome (ANTIDETECT_LIVE_BROWSER=1)",
)


@_LIVE_BROWSER
def test_live_windows_spoof_on_all_tabs(tmp_path: Path):
    """Production path on a real browser: launch + injection + daemon, then
    verify the spoof on the first tab AND a freshly opened second tab."""
    import time as _time

    import json as _json

    from app.infrastructure.chromium.paths import discover_chromium
    from app.infrastructure.stealth.cdp import _CdpConnection

    binary = discover_chromium()
    manager = ChromiumManager(chromium_path=binary, logs_dir=tmp_path / "logs")
    profile_dir = tmp_path / "live"
    pid = manager.start(profile_dir, _spoofed_config())
    try:
        endpoint = discover_browser_endpoint(profile_dir, timeout=20)
        browser = _CdpConnection(endpoint)
        try:
            browser.call("Target.createTarget", {"url": "about:blank"})
            _time.sleep(2.0)  # let the daemon attach and patch the new tab
            probe = (
                "JSON.stringify({plat: navigator.platform, "
                "cores: navigator.hardwareConcurrency, "
                "chP: navigator.userAgentData && navigator.userAgentData.platform})"
            )
            targets = discover_page_targets(profile_dir)
            assert len(targets) >= 2, targets
            for target_ws in targets:
                tab = _CdpConnection(target_ws)
                try:
                    # A real cross-document navigation is required: re-navigating
                    # a tab to its current about:blank is a no-op (script never
                    # runs), and data: URLs from WebUI newtab pages inherit a
                    # quirked document. This test is live-gated, so network use
                    # is acceptable.
                    tab.call("Page.navigate", {"url": "https://example.com/"})
                    _time.sleep(2.0)
                    value = (
                        tab.call(
                            "Runtime.evaluate",
                            {"expression": probe, "returnByValue": True},
                        )
                        .get("result", {})
                        .get("value", "{}")
                    )
                    assert _json.loads(value) == {
                        "plat": "Win32",
                        "cores": 8,
                        "chP": "Windows",
                    }, value
                finally:
                    tab.close()
        finally:
            browser.close()
    finally:
        manager.stop(profile_dir, pid)


def _cmdline(pid: int) -> str:
    if sys.platform == "win32":
        pytest.skip("ps inspection not covered on Windows in CI")
    # `ps -o command=` truncates to display width on Linux (no tty),
    # cutting off the flags under test — read the full /proc cmdline first.
    proc = Path(f"/proc/{pid}/cmdline")
    if proc.is_file():
        return proc.read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
    output = subprocess.run(
        ["ps", "-o", "command=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    ).stdout
    return output
