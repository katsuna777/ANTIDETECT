"""A real Container + the API over real HTTP on a free port, with a stub browser."""

from __future__ import annotations

import http.client
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from antidetect.api import ApiManager
from antidetect.config import AppConfig
from antidetect.container import bootstrap
from tests.support.fakes import StubChecker


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Client:
    """Talks to the API the way a script would; headers can be overridden to play an attacker."""

    def __init__(self, port: int, token: str) -> None:
        self.port = port
        self.token = token

    def request(self, method: str, path: str, body=None, *, token="default", headers=None, raw: bytes | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            sent = dict(headers or {})
            lowered = {k.lower() for k in sent}
            conn.putrequest(method, path, skip_host="host" in lowered, skip_accept_encoding=True)
            if "host" not in lowered:
                conn.putheader("Host", f"127.0.0.1:{self.port}")
            use = self.token if token == "default" else token
            if use is not None and "authorization" not in lowered:
                conn.putheader("Authorization", f"Bearer {use}")
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
            if "content-length" not in lowered and (data or method in ("POST", "PATCH", "PUT")):
                conn.putheader("Content-Length", str(len(data)))
                conn.putheader("Content-Type", "application/json")
            for key, value in sent.items():
                conn.putheader(key, value)
            conn.endheaders(data)
            response = conn.getresponse()
            payload = response.read()
            parsed = json.loads(payload) if payload else None
            return response.status, parsed, {k.lower(): v for k, v in response.getheaders()}
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body, **kw)

    def patch(self, path, body=None, **kw):
        return self.request("PATCH", path, body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


@pytest.fixture()
def container(tmp_path: Path, fake_chromium: Path):
    """A real bootstrapped Container (stub browser, no network); the API is not running."""
    container = bootstrap(AppConfig(data_dir=tmp_path / "data", chromium_path=fake_chromium))
    container.proxies._checker = StubChecker()      # proxy checks never touch the network
    container.profiles._geo_lookup = lambda: None   # nor does the own-IP country lookup
    yield container
    for profile in container.profiles.list_profiles():
        if profile.status.value == "RUNNING":
            container.profiles.stop_profile(profile.id)
    container.close()


@pytest.fixture()
def api(container):
    changes: list[int] = []
    manager = ApiManager(container, on_change=lambda: changes.append(1))
    manager.settings.set_port(free_port())
    manager.set_enabled(True)
    yield SimpleNamespace(
        container=container, manager=manager, changes=changes,
        client=Client(manager.port, manager.settings.token),
    )
    manager.stop()
