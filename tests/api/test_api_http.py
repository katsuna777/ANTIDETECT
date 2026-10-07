"""The HTTP surface: who gets in, and what a bad request gets back."""

from __future__ import annotations

import socket

import pytest

from tests.api.conftest import Client

pytestmark = pytest.mark.usefixtures("api")


def test_listens_on_loopback_only(api):
    server = api.manager._server._httpd
    assert server.server_address[0] == "127.0.0.1"


def test_every_endpoint_needs_the_token(api):
    c = api.client
    for method, path in [("GET", "/v1/status"), ("GET", "/v1/profiles"), ("POST", "/v1/profiles"),
                         ("GET", "/v1/profiles/1"), ("POST", "/v1/profiles/1/start"), ("GET", "/v1/proxies"),
                         ("GET", "/v1/does-not-exist"), ("GET", "/")]:
        status, body, _ = c.request(method, path, token=None)
        assert status == 401 and body["error"]["code"] == "unauthorized", (method, path)
        status, body, _ = c.request(method, path, token="ad_wrong")
        assert status == 401, (method, path)


def test_the_token_is_accepted_as_bearer_or_api_key(api):
    c = api.client
    assert c.get("/v1/status")[0] == 200
    status, _, _ = c.get("/v1/status", token=None, headers={"X-API-Key": api.manager.settings.token})
    assert status == 200
    status, _, _ = c.get("/v1/status", token=None, headers={"X-API-Key": "nope"})
    assert status == 401


def test_health_needs_no_token_but_is_not_a_door_for_web_pages(api):
    c = api.client
    status, body, _ = c.get("/v1/health", token=None)
    assert status == 200 and body == {"ok": True, "app": "antidetect"}
    assert c.get("/v1/health", token=None, headers={"Origin": "https://evil.example"})[0] == 403


def test_a_browser_cross_site_request_is_refused_even_with_the_token(api):
    status, body, _ = api.client.get("/v1/profiles", headers={"Origin": "https://evil.example"})
    assert status == 403 and body["error"]["code"] == "forbidden_origin"
    status, _, _ = api.client.post("/v1/profiles", {"name": "x"}, headers={"Origin": "null"})
    assert status == 403
    assert api.client.get("/v1/profiles")[1]["total"] == 0          # and nothing was created


def test_a_foreign_host_header_is_refused_dns_rebinding(api):
    for host in ("evil.example", f"evil.example:{api.client.port}", "127.0.0.1:1", "192.168.1.5"):
        status, body, _ = api.client.get("/v1/profiles", headers={"Host": host})
        assert status == 403 and body["error"]["code"] == "forbidden_host", host
    for host in (f"localhost:{api.client.port}", f"127.0.0.1:{api.client.port}"):
        assert api.client.get("/v1/profiles", headers={"Host": host})[0] == 200


def test_no_cors_headers_are_ever_sent(api):
    status, _, headers = api.client.request("OPTIONS", "/v1/profiles")
    assert status == 405
    assert not any(key.startswith("access-control-") for key in headers)
    _, _, headers = api.client.get("/v1/status")
    assert not any(key.startswith("access-control-") for key in headers)


def test_regenerating_the_token_locks_out_the_old_one_at_once(api):
    old = api.manager.settings.token
    new = api.manager.regenerate_token()
    assert new != old and new.startswith("ad_")
    assert api.client.get("/v1/status", token=old)[0] == 401
    assert api.client.get("/v1/status", token=new)[0] == 200


def test_unknown_paths_and_wrong_methods_answer_in_json(api):
    status, body, _ = api.client.get("/v1/nope")
    assert status == 404 and body["error"]["code"] == "not_found"
    status, body, headers = api.client.request("PUT", "/v1/profiles")
    assert status == 405 and body["error"]["code"] == "method_not_allowed"
    assert set(headers["allow"].split(", ")) == {"GET", "POST"}


def test_a_trailing_slash_is_fine(api):
    assert api.client.get("/v1/profiles/")[0] == 200


def test_bad_json_and_oversize_bodies_are_rejected(api):
    status, body, _ = api.client.post("/v1/profiles", raw=b"{not json")
    assert status == 400 and body["error"]["code"] == "bad_json"
    status, body, _ = api.client.post("/v1/profiles", [1, 2])
    assert status == 400 and "object" in body["error"]["message"]
    status, body, _ = api.client.post("/v1/profiles", headers={"Content-Length": str(50 * 1024 * 1024)}, raw=b"")
    assert status == 413


def test_the_responses_are_utf8_json_and_never_cached(api):
    api.client.post("/v1/profiles", {"name": "Магазин №1"})
    status, body, headers = api.client.get("/v1/profiles")
    assert body["items"][0]["name"] == "Магазин №1"
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["cache-control"] == "no-store"
    assert "python" not in headers.get("server", "").lower()


def test_an_idle_connection_does_not_block_other_requests(api):
    idle = socket.create_connection(("127.0.0.1", api.client.port))
    try:
        assert api.client.get("/v1/status")[0] == 200
    finally:
        idle.close()


def test_status_reports_counts_and_browser(api, fake_chromium):
    status, body, _ = api.client.get("/v1/status")
    assert status == 200
    assert body["profiles"] == 0 and body["running"] == 0
    assert body["browser"]["path"] == str(fake_chromium)
