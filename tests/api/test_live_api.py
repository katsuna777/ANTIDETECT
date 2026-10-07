"""The API against a real Chrome (opt-in: ANTIDETECT_LIVE_BROWSER=1).

What an automation tool does: ask the API for a profile, take the address it returns, and connect
to the *running* browser. Whatever it opens there must show the claimed machine, not the host.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from antidetect.api import ApiManager
from antidetect.application.fingerprint import data as fd
from antidetect.config import AppConfig
from antidetect.container import bootstrap
from antidetect.infrastructure.stealth.cdp import _CdpConnection
from tests.api.conftest import Client, free_port

pytestmark = pytest.mark.skipif(
    os.environ.get("ANTIDETECT_LIVE_BROWSER") != "1",
    reason="needs a real Chrome (set ANTIDETECT_LIVE_BROWSER=1)",
)

_PROBE = ("JSON.stringify({platform: navigator.platform, uad: navigator.userAgentData.platform, "
          "ua: navigator.userAgent, screen: [screen.width, screen.height], webdriver: navigator.webdriver})")


class _Page(BaseHTTPRequestHandler):
    def do_GET(self) -> None:                                   # noqa: N802
        body = b"<!doctype html><title>probe</title><p>hello"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def live(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTIDETECT_DISABLE_STEALTH", raising=False)
    container = bootstrap(AppConfig(data_dir=tmp_path / "data"))
    container.profiles._geo_lookup = lambda: None
    manager = ApiManager(container)
    manager.settings.set_port(free_port())
    manager.set_enabled(True)
    site = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    yield Client(manager.port, manager.settings.token), f"http://127.0.0.1:{site.server_address[1]}/", container
    for profile in container.profiles.list_profiles():
        if profile.status.value == "RUNNING":
            container.profiles.stop_profile(profile.id)
    site.shutdown()
    manager.stop()
    container.close()


def _evaluate(conn: _CdpConnection, target_id: str, url: str) -> dict:
    session = conn.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
    conn.call("Page.enable", {}, session)
    conn.call("Page.navigate", {"url": url}, session, timeout=30.0)    # a hosted Windows runner can take over 8 s here
    time.sleep(2.0)
    reply = conn.call("Runtime.evaluate", {"expression": _PROBE, "returnByValue": True}, session)
    return json.loads(reply["result"]["value"])


def test_live_a_tool_connecting_through_the_api_sees_the_claimed_machine(live):
    client, page_url, _ = live
    other = next(p for p in ("windows", "linux", "macos") if p != fd.host_platform())
    status, profile, _ = client.post("/v1/profiles", {"name": "live", "platform": other, "geo_auto": False})
    assert status == 201
    status, run, _ = client.post(f"/v1/profiles/{profile['id']}/start")
    assert status == 200 and run["status"] == "running"
    connection = run["connection"]
    assert connection["ws"].startswith("ws://127.0.0.1:") and connection["debugger_address"].startswith("127.0.0.1:")

    conn = _CdpConnection(connection["ws"])                     # what Playwright / Puppeteer / Selenium do
    try:
        first = next(i for i in conn.call("Target.getTargets")["targetInfos"] if i["type"] == "page")
        seen = _evaluate(conn, first["targetId"], page_url)
        assert seen["platform"] == fd.NAVIGATOR_PLATFORM[other]
        assert seen["uad"] == {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[other]
        assert seen["webdriver"] is False
        width, height = (int(n) for n in profile["screen"].split("x"))
        assert seen["screen"] == [width, height]
        # a tab the tool opens itself must be patched before its first script runs
        tab = conn.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        assert _evaluate(conn, tab, page_url)["platform"] == fd.NAVIGATOR_PLATFORM[other]
    finally:
        conn.close()

    cookie = {"name": "sid", "value": "abc", "domain": "127.0.0.1", "path": "/"}
    assert client.post(f"/v1/profiles/{profile['id']}/cookies", {"cookies": [cookie]})[1] == {"imported": 1}
    cookies = client.get(f"/v1/profiles/{profile['id']}/cookies")[1]
    # Chrome itself talks to Google on a runner (its start page sets a NID cookie): only ours count.
    assert [(c["name"], c["value"]) for c in cookies["cookies"] if c["domain"].lstrip(".") == "127.0.0.1"] == [("sid", "abc")]
    assert client.delete(f"/v1/profiles/{profile['id']}/cookies")[1] == {"cleared": True}
    assert client.get(f"/v1/profiles/{profile['id']}/cookies")[1]["count"] == 0

    assert client.post(f"/v1/profiles/{profile['id']}/start")[1]["already_running"] is True
    again = client.get(f"/v1/profiles/{profile['id']}/connection")[1]
    assert again["ws"] == connection["ws"]                      # the same browser, the same address
    started = time.monotonic()
    stopped = client.post(f"/v1/profiles/{profile['id']}/stop")[1]
    assert stopped["status"] == "stopped" and stopped["connection"] is None
    assert time.monotonic() - started < 5.0
    assert client.get(f"/v1/profiles/{profile['id']}/connection")[0] == 409
