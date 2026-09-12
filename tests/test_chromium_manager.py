from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.errors import ChromiumError, ChromiumNotFoundError
from app.domain.models.browser_configuration import BrowserConfiguration
from app.domain.models.proxy import Proxy
from app.infrastructure.chromium import paths
from app.infrastructure.chromium.chromium_manager import (
    ChromiumManager,
    _proxy_server_url,
)
from app.infrastructure.chromium.paths import discover_chromium


@pytest.fixture()
def manager(fake_chromium: Path, tmp_path: Path) -> ChromiumManager:
    return ChromiumManager(
        chromium_path=fake_chromium, logs_dir=tmp_path / "logs", enable_stealth=False
    )


@pytest.fixture()
def proxy_ok():
    """Launch-time proxy probe stub: every proxy is considered usable."""
    return lambda proxy, timeout: True


def test_start_returns_live_pid(manager: ChromiumManager, tmp_path: Path):
    profile_dir = tmp_path / "p1"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        assert manager.is_running(profile_dir, pid) is True
        assert pid > 0
    finally:
        manager.stop(profile_dir, pid)


def test_is_running_reports_false_without_pid(manager: ChromiumManager, tmp_path: Path):
    assert manager.is_running(tmp_path / "nope", None) is False
    assert manager.is_running(tmp_path / "nope", 0) is False
    assert manager.is_running(tmp_path / "nope", 999_999_999) is False


def test_stop_terminates_process(manager: ChromiumManager, tmp_path: Path):
    profile_dir = tmp_path / "p2"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    manager.stop(profile_dir, pid)
    assert manager.is_running(profile_dir, pid) is False


def test_stop_is_idempotent(manager: ChromiumManager, tmp_path: Path):
    profile_dir = tmp_path / "p3"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    manager.stop(profile_dir, pid)
    manager.stop(profile_dir, pid)


def test_passes_user_data_dir_to_browser(manager: ChromiumManager, tmp_path: Path, monkeypatch):
    profile_dir = tmp_path / "custom_profile_dir"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        cmdline = _cmdline(pid)
        assert f"--user-data-dir={profile_dir}" in cmdline
    finally:
        manager.stop(profile_dir, pid)


def test_applies_configuration_flags(manager: ChromiumManager, tmp_path: Path):
    profile_dir = tmp_path / "cfg"
    configuration = BrowserConfiguration(
        id=2,
        name="custom",
        user_agent="MyUA/1.0",
        language="en-US",
        timezone="America/New_York",
    )
    pid = manager.start(profile_dir, configuration)
    try:
        cmdline = _cmdline(pid)
        assert "--user-agent=MyUA/1.0" in cmdline
        assert "--lang=en-US" in cmdline
        assert "--timezone-id=America/New_York" in cmdline
    finally:
        manager.stop(profile_dir, pid)


def test_applies_full_fingerprint_flags(manager: ChromiumManager, tmp_path: Path):
    profile_dir = tmp_path / "full_cfg"
    configuration = BrowserConfiguration(
        id=3,
        name="full",
        user_agent="Chrome/123.0.0.0",
        platform="windows",
        language="en",
        locale="en-US",
        timezone="Europe/Berlin",
        screen_width=2560,
        screen_height=1440,
        device_pixel_ratio=1.5,
        color_depth=24,
    )
    pid = manager.start(profile_dir, configuration)
    try:
        cmdline = _cmdline(pid)
        assert "--lang=en-US" in cmdline
        assert "--accept-lang=en-US,en" in cmdline
        assert "--timezone-id=Europe/Berlin" in cmdline
        assert "--window-size=2560,1440" in cmdline
        assert "--force-device-scale-factor=1.5" in cmdline
    finally:
        manager.stop(profile_dir, pid)


def test_applies_proxy_flag_for_unauthenticated_proxy(
    fake_chromium: Path, tmp_path: Path, proxy_ok
):
    manager = ChromiumManager(
        chromium_path=fake_chromium, logs_dir=tmp_path / "logs", proxy_probe=proxy_ok
    )
    profile_dir = tmp_path / "proxied"
    proxy = Proxy(
        id=1,
        protocol=ProxyProtocol.SOCKS5,
        host="68.183.1.2",
        port=1080,
    )
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"), proxy=proxy)
    try:
        cmdline = _cmdline(pid)
        assert "--proxy-server=socks5://68.183.1.2:1080" in cmdline
        assert manager._shims == {}
    finally:
        manager.stop(profile_dir, pid)


def test_authenticated_proxy_uses_local_shim(
    fake_chromium: Path, tmp_path: Path, proxy_ok
):
    manager = ChromiumManager(
        chromium_path=fake_chromium, logs_dir=tmp_path / "logs", proxy_probe=proxy_ok
    )
    profile_dir = tmp_path / "authed_proxied"
    proxy = Proxy(
        id=1,
        protocol=ProxyProtocol.HTTP,
        host="68.183.1.3",
        port=8080,
        username="user1",
        password="s3cret",
    )
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"), proxy=proxy)
    try:
        cmdline = _cmdline(pid)
        # Chromium cannot authenticate through --proxy-server, so the profile
        # must be routed through a credential-free local shim on 127.0.0.1.
        assert "--proxy-server=http://127.0.0.1:" in cmdline
        assert "user1" not in cmdline
        assert "s3cret" not in cmdline
        assert pid in manager._shims
    finally:
        manager.stop(profile_dir, pid)
    assert manager._shims == {}


def test_stop_closes_proxy_shim(fake_chromium: Path, tmp_path: Path, proxy_ok):
    manager = ChromiumManager(
        chromium_path=fake_chromium, logs_dir=tmp_path / "logs", proxy_probe=proxy_ok
    )
    profile_dir = tmp_path / "shim_stop"
    proxy = Proxy(
        id=1,
        protocol=ProxyProtocol.SOCKS5,
        host="68.183.1.4",
        port=1080,
        username="user1",
        password="s3cret",
    )
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"), proxy=proxy)
    shim = manager._shims[pid]
    assert shim.proxy_server_url.startswith("socks5://127.0.0.1:")
    manager.stop(profile_dir, pid)
    assert manager._shims == {}
    assert shim._server is None  # socket closed, no longer accepting


def test_start_rejects_proxy_failing_probe(fake_chromium: Path, tmp_path: Path):
    """A proxy that fails the end-to-end probe must abort launch with a clear
    error instead of handing a broken --proxy-server to Chromium (which would
    otherwise spin on the search page forever)."""
    manager = ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        proxy_probe=lambda proxy, timeout: False,
    )
    profile_dir = tmp_path / "bad_proxy"
    proxy = Proxy(
        id=1,
        protocol=ProxyProtocol.HTTP,
        host="86.53.110.3",
        port=7890,
    )
    with pytest.raises(ChromiumError, match="is not working"):
        manager.start(profile_dir, BrowserConfiguration(id=1, name="default"), proxy=proxy)
    assert manager.is_running(profile_dir, None) is False


def test_proxy_probe_exception_becomes_chromium_error(
    fake_chromium: Path, tmp_path: Path
):
    manager = ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        proxy_probe=lambda proxy, timeout: (_ for _ in ()).throw(OSError("refused")),
    )
    profile_dir = tmp_path / "bad_proxy_2"
    proxy = Proxy(
        id=1,
        protocol=ProxyProtocol.HTTP,
        host="86.53.110.3",
        port=7890,
    )
    with pytest.raises(ChromiumError, match="unusable"):
        manager.start(profile_dir, BrowserConfiguration(id=1, name="default"), proxy=proxy)


def test_proxy_server_url_percent_encodes_credentials() -> None:
    proxy = Proxy(
        id=1,
        protocol=ProxyProtocol.HTTP,
        host="10.0.0.1",
        port=8080,
        username="a@b",
        password="p:w",
    )
    assert _proxy_server_url(proxy) == "http://a%40b:p%3Aw@10.0.0.1:8080"


def test_proxy_server_url_without_credentials() -> None:
    proxy = Proxy(
        id=2,
        protocol=ProxyProtocol.SOCKS5,
        host="10.0.0.2",
        port=1080,
    )
    assert _proxy_server_url(proxy) == "socks5://10.0.0.2:1080"


def test_user_data_dir_guard_detects_wrong_profile(manager: ChromiumManager, tmp_path: Path):
    profile_dir = tmp_path / "own"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        other = tmp_path / "other"
        assert manager.is_running(other, pid) is False
    finally:
        manager.stop(profile_dir, pid)


def test_exit_during_stabilization_raises_chromium_error(manager, tmp_path, monkeypatch):
    """Deterministic version: a process that exits moments after launch must be
    reported as a launch failure regardless of wall-clock timing."""

    class ExitingProcess:
        pid = 9999
        returncode = None

        def __init__(self, *args, **kwargs):
            self.poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls >= 2:
                self.returncode = 3
                return 3
            return None

    monkeypatch.setattr(
        "app.infrastructure.chromium.chromium_manager.subprocess.Popen",
        lambda *a, **k: ExitingProcess(),
    )
    with pytest.raises(ChromiumError):
        manager.start(tmp_path / "p", BrowserConfiguration(id=1, name="default"))


def test_stable_process_registers_pid(manager, tmp_path, monkeypatch):
    class StableProcess:
        pid = 7777
        returncode = None

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return None

    monkeypatch.setattr(
        "app.infrastructure.chromium.chromium_manager.subprocess.Popen",
        lambda *a, **k: StableProcess(),
    )
    profile_dir = tmp_path / "stable"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    assert pid == 7777
    assert manager.is_running(profile_dir, pid) is True


def test_discover_chromium_uses_env_override(monkeypatch, fake_chromium: Path):
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(fake_chromium))
    assert discover_chromium() == fake_chromium


def test_discover_chromium_rejects_bad_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", "/definitely/not/a/browser")
    monkeypatch.setattr(paths, "_KNOWN_PATHS", {})
    monkeypatch.setattr(paths, "_KNOWN_COMMANDS", [])
    monkeypatch.setattr(paths, "_registry_candidates", lambda: [])
    monkeypatch.setattr(paths, "_windows_install_paths", lambda: [])
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ChromiumNotFoundError):
        discover_chromium()


def test_discover_chromium_raises_when_nothing_found(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("ANTIDETECT_CHROMIUM_PATH", raising=False)
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.setattr(paths, "_KNOWN_PATHS", {})
    monkeypatch.setattr(paths, "_KNOWN_COMMANDS", [])
    monkeypatch.setattr(paths, "_registry_candidates", lambda: [])
    monkeypatch.setattr(paths, "_windows_install_paths", lambda: [])
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ChromiumNotFoundError):
        discover_chromium()


def test_discover_chromium_finds_known_macos_path(monkeypatch, fake_chromium: Path):
    """The fallback list must resolve to a real install when present."""
    real = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not real.is_file():
        pytest.skip("Google Chrome is not installed on this machine")
    monkeypatch.delenv("ANTIDETECT_CHROMIUM_PATH", raising=False)
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.setattr(paths, "_KNOWN_PATHS", {"darwin": [real]})
    assert discover_chromium() == real


def test_discover_chromium_finds_patch_command(monkeypatch, fake_chromium: Path, tmp_path: Path):
    monkeypatch.delenv("ANTIDETECT_CHROMIUM_PATH", raising=False)
    monkeypatch.delenv("CHROME_PATH", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    symlink = bin_dir / "chromium"
    symlink.symlink_to(fake_chromium)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(paths, "_KNOWN_PATHS", {})
    assert discover_chromium() == symlink


def test_start_creates_log_files(manager: ChromiumManager, tmp_path: Path):
    profile_dir = tmp_path / "logs_me"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        logs = tmp_path / "logs"
        assert (logs / "chromium.stdout.log").exists()
        assert (logs / "chromium.stderr.log").exists()
    finally:
        manager.stop(profile_dir, pid)


def test_start_creates_log_files_inside_profile_dir(tmp_path: Path, fake_chromium: Path):
    manager = ChromiumManager(chromium_path=fake_chromium)  # no logs_dir set
    profile_dir = tmp_path / "inline_logs"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        assert (profile_dir / ".logs" / "chromium.stderr.log").exists()
    finally:
        manager.stop(profile_dir, pid)


def test_stop_unregistered_dead_pid_is_safe(manager: ChromiumManager, tmp_path: Path):
    manager.stop(tmp_path / "anywhere", 999_999_999)


def test_stop_unregistered_live_pid_fallback(manager: ChromiumManager, tmp_path: Path):
    """A pid not owned by this manager instance but still alive must be stopped
    via the raw-signal fallback (e.g. CLI restarted and lost the registry)."""
    profile_dir = tmp_path / "orphan"
    started = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    manager._processes.pop(started, None)  # simulate fresh manager instance

    assert manager.is_running(profile_dir, started) is True
    manager.stop(profile_dir, started)
    assert manager.is_running(profile_dir, started) is False


def test_is_running_on_unrelated_live_process(tmp_path: Path, fake_chromium: Path):
    manager = ChromiumManager(chromium_path=fake_chromium, logs_dir=tmp_path / "logs")
    # A live process whose command line does NOT mention our profile dir.
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert manager.is_running(tmp_path / "mine", sleeper.pid) is False
    finally:
        sleeper.terminate()
        sleeper.wait()


def test_start_logs_launch_and_pid(fake_chromium: Path, tmp_path: Path):
    from tests.fakes import RecordingLogSink

    sink = RecordingLogSink()
    manager = ChromiumManager(
        chromium_path=fake_chromium, logs_dir=tmp_path / "logs", log_sink=sink
    )
    profile_dir = tmp_path / "logged"
    pid = manager.start(profile_dir, BrowserConfiguration(id=1, name="default"))
    try:
        sources = {source for _level, source, _msg, _extra in sink.entries}
        assert "chromium" in sources
        assert any("Launching Chromium" in msg for _l, _s, msg, _e in sink.entries)
        assert any(str(pid) in msg and "started" in msg for _l, _s, msg, _e in sink.entries)
        assert {src for src, _path in sink.tailed} == {"chromium.stdout", "chromium.stderr"}
    finally:
        manager.stop(profile_dir, pid)
    assert any("Stopping Chromium" in msg for _l, _s, msg, _e in sink.entries)


def test_failed_proxy_probe_is_logged_as_error(fake_chromium: Path, tmp_path: Path):
    from app.domain.enums.proxy_status import ProxyProtocol
    from tests.fakes import RecordingLogSink

    sink = RecordingLogSink()
    manager = ChromiumManager(
        chromium_path=fake_chromium,
        logs_dir=tmp_path / "logs",
        proxy_probe=lambda proxy, timeout: False,
        log_sink=sink,
    )
    proxy = Proxy(id=1, protocol=ProxyProtocol.HTTP, host="86.53.110.3", port=7890)
    with pytest.raises(ChromiumError, match="is not working"):
        manager.start(
            tmp_path / "bad_logged",
            BrowserConfiguration(id=1, name="default"),
            proxy=proxy,
        )
    errors = [
        (source, msg) for level, source, msg, _e in sink.entries if level == "ERROR"
    ]
    assert errors, "expected at least one ERROR log"
    assert any("is not working" in msg for _s, msg in errors)


def test_user_data_dir_match_is_exact_not_substring(tmp_path: Path) -> None:
    from app.infrastructure.chromium.chromium_manager import _cmdline_matches

    own = tmp_path / "profile_001"
    other = tmp_path / "profile_0010"
    assert _cmdline_matches(f"chrome --user-data-dir={own}", own) is True
    assert _cmdline_matches(f"chrome --user-data-dir={other}", own) is False
    assert _cmdline_matches(f'chrome --user-data-dir="{own}"', own) is True


def _cmdline(pid: int) -> str:
    if sys.platform == "win32":
        raise pytest.skip("ps inspection not covered on Windows in CI")
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