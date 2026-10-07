"""Starting, stopping and re-configuring the server."""

from __future__ import annotations

import socket

import pytest

from antidetect.api import ApiManager, ApiSettings, ApiStartError
from antidetect.api.settings import DEFAULT_PORT, parse_port
from tests.api.conftest import Client, free_port

def test_settings_have_safe_defaults_and_persist(container):
    settings = ApiSettings(container.settings)
    assert settings.enabled is False and settings.port == DEFAULT_PORT
    token = settings.token
    assert token.startswith("ad_") and len(token) >= 40
    assert settings.token == token                                   # created once, then stable
    settings.set_port("40123")
    settings.set_enabled(True)
    again = ApiSettings(container.settings)
    assert (again.enabled, again.port, again.token) == (True, 40123, token)
    assert again.url == "http://127.0.0.1:40123"


@pytest.mark.parametrize("bad", ["", "abc", "0", "80", "1023", "65536", "-5", None, "8080.5"])
def test_unusable_ports_are_refused(bad):
    with pytest.raises(ValueError):
        parse_port(bad)


@pytest.mark.parametrize("good", ["1024", " 8080 ", 65535, 47831])
def test_usable_ports(good):
    assert parse_port(good) == int(str(good).strip())


def test_a_garbled_saved_port_falls_back_to_the_default(container):
    container.settings.set("api.port", "banana")
    assert ApiSettings(container.settings).port == DEFAULT_PORT


def test_start_and_stop_are_idempotent_and_free_the_port(container):
    manager = ApiManager(container)
    manager.settings.set_port(free_port())
    manager.start()
    manager.start()
    assert manager.running
    client = Client(manager.port, manager.settings.token)
    assert client.get("/v1/status")[0] == 200
    manager.stop()
    manager.stop()
    assert not manager.running
    with pytest.raises(OSError):
        client.get("/v1/status")
    with socket.socket() as sock:                                    # the port is free again at once
        sock.bind(("127.0.0.1", manager.settings.port))


def test_a_busy_port_leaves_the_api_off_and_says_so(container):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        manager = ApiManager(container)
        manager.settings.set_port(taken.getsockname()[1])
        with pytest.raises(ApiStartError, match="already in use"):
            manager.set_enabled(True)
        assert manager.settings.enabled is False and not manager.running
        manager.settings.set_enabled(True)                          # a saved "on" meets a busy port at launch
        assert "already in use" in manager.apply() and not manager.running


def test_apply_follows_the_saved_switch(container):
    manager = ApiManager(container)
    manager.settings.set_port(free_port())
    manager.settings.set_enabled(False)
    assert manager.apply() is None and not manager.running
    manager.settings.set_enabled(True)
    assert manager.apply() is None and manager.running
    manager.settings.set_enabled(False)
    assert manager.apply() is None and not manager.running


def test_changing_the_port_moves_a_running_server(api):
    old = api.manager.port
    new = free_port()
    assert api.manager.set_port(new) == new
    assert api.manager.port == new != old and api.manager.running
    assert Client(new, api.manager.settings.token).get("/v1/status")[0] == 200
    with pytest.raises(OSError):
        Client(old, api.manager.settings.token).get("/v1/status")


def test_a_busy_new_port_keeps_the_old_one_running(api):
    old = api.manager.port
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        with pytest.raises(ApiStartError):
            api.manager.set_port(taken.getsockname()[1])
    assert api.manager.port == old and api.manager.settings.port == old and api.manager.running
    assert api.client.get("/v1/status")[0] == 200


def test_a_bad_port_changes_nothing(api):
    old = api.manager.port
    with pytest.raises(ValueError):
        api.manager.set_port("22")
    assert api.manager.settings.port == old and api.manager.running


def test_the_log_says_when_the_api_starts_and_stops(api):
    api.manager.stop()
    messages = [e.message for e in api.container.logs.list_logs() if e.source == "api"]
    assert any("listening on http://127.0.0.1:" in m for m in messages)
    assert "API stopped" in messages
