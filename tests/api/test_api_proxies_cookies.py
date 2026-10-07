"""Proxies and cookies through the API."""

from __future__ import annotations

from pathlib import Path

import pytest

from antidetect.api import service as api_service

pytestmark = pytest.mark.usefixtures("api")


def _create(api, **body):
    status, profile, _ = api.client.post("/v1/profiles", {"name": "Shop", "geo_auto": False, **body})
    assert status == 201, profile
    return profile


# ------------------------------------------------------------------- proxies

def test_add_list_check_and_delete_proxies(api):
    status, added, _ = api.client.post("/v1/proxies", {
        "proxies": ["user:pass@1.2.3.4:8080", "socks5://5.6.7.8:1080", "garbage"], "check": True})
    assert status == 200 and added["added"] == 2 and added["invalid"] == ["garbage"]
    kinds = {(p["type"], p["host"], p["port"]) for p in added["items"]}
    assert kinds == {("http", "1.2.3.4", 8080), ("socks5", "5.6.7.8", 1080)}
    assert all(p["status"] == "working" for p in added["items"])
    first = next(p for p in added["items"] if p["host"] == "1.2.3.4")
    assert first["username"] == "user" and first["has_password"] is True and "password" not in first
    assert "pass" not in str(added).replace("has_password", "")      # the password never leaves the app

    assert api.client.get("/v1/proxies")[1]["total"] == 2
    assert api.client.get("/v1/proxies?status=dead")[1]["total"] == 0
    assert api.client.get("/v1/proxies?status=nonsense")[0] == 400
    assert api.client.post(f"/v1/proxies/{first['id']}/check")[1]["id"] == first["id"]
    assert api.client.delete(f"/v1/proxies/{first['id']}")[1] == {"id": first["id"], "deleted": True}
    assert api.client.get("/v1/proxies")[1]["total"] == 1
    assert api.client.delete(f"/v1/proxies/{first['id']}")[1]["error"]["code"] == "proxy_not_found"


def test_proxies_can_be_sent_as_text_or_objects(api):
    status, added, _ = api.client.post("/v1/proxies", {"proxies": "1.1.1.1:80\n\n2.2.2.2:81:me:pw"})
    assert status == 200 and added["added"] == 2
    status, added, _ = api.client.post("/v1/proxies", {"proxies": [
        {"type": "socks5", "host": "3.3.3.3", "port": 1080, "username": "u@x", "password": "p:w/d"}]})
    assert status == 200 and added["added"] == 1
    row = api.container.proxies.get_proxy(added["items"][0]["id"])
    assert (row.protocol.value, row.username, row.password) == ("SOCKS5", "u@x", "p:w/d")   # odd characters survive
    assert api.client.post("/v1/proxies", {"proxies": []})[0] == 400
    assert api.client.post("/v1/proxies", {"proxies": [5]})[0] == 400
    assert api.client.post("/v1/proxies", {"proxies": [{"host": "h"}]})[0] == 400
    assert api.client.post("/v1/proxies", {"proxies": ["1.1.1.1:80"], "type": "socks4"})[0] == 400


def test_adding_the_same_proxy_twice_reuses_it(api):
    first = api.client.post("/v1/proxies", {"proxies": ["1.1.1.1:80"]})[1]
    again = api.client.post("/v1/proxies", {"proxies": ["1.1.1.1:80"]})[1]
    assert again["added"] == 0 and again["existing"] == 1 and again["items"][0]["id"] == first["items"][0]["id"]


def test_a_profile_is_created_with_a_proxy_string(api):
    profile = _create(api, proxy="me:secret@9.9.9.9:3128")
    assert profile["proxy"]["host"] == "9.9.9.9" and profile["proxy"]["port"] == 3128
    assert profile["proxy"]["status"] == "working"                   # it was measured on the way in
    assert "secret" not in str(profile)
    again = _create(api, name="Second", proxy="me:secret@9.9.9.9:3128")
    assert again["proxy"]["id"] == profile["proxy"]["id"]            # the same proxy, not a duplicate


def test_a_profile_is_created_with_a_proxy_id_and_the_proxy_can_be_swapped_and_removed(api):
    proxy_id = api.client.post("/v1/proxies", {"proxies": ["1.1.1.1:80"]})[1]["items"][0]["id"]
    profile = _create(api, proxy_id=proxy_id)
    assert profile["proxy"]["id"] == proxy_id
    other = api.client.post("/v1/proxies", {"proxies": ["2.2.2.2:80"]})[1]["items"][0]["id"]
    path = f"/v1/profiles/{profile['id']}"
    assert api.client.patch(path, {"proxy_id": other})[1]["proxy"]["id"] == other
    assert api.client.patch(path, {"proxy": "3.3.3.3:80"})[1]["proxy"]["host"] == "3.3.3.3"
    assert api.client.patch(path, {"proxy": None})[1]["proxy"] is None
    assert api.client.patch(path, {"name": "Only a name"})[1]["proxy"] is None


def test_a_bad_proxy_is_a_clear_error_and_creates_nothing(api):
    status, body, _ = api.client.post("/v1/profiles", {"name": "P", "proxy": "not a proxy"})
    assert status == 422 and body["error"]["code"] == "proxy_unreadable"
    status, body, _ = api.client.post("/v1/profiles", {"name": "P", "proxy_id": 12345})
    assert status == 404 and body["error"]["code"] == "proxy_not_found"
    assert api.client.post("/v1/profiles", {"name": "P", "proxy_id": "1"})[0] == 400
    assert api.client.get("/v1/profiles")[1]["total"] == 0


def test_a_proxy_can_be_taken_on_trust_without_measuring_it(api):
    checker = api.container.proxies._checker
    _create(api, proxy="4.4.4.4:80", check_proxy=False)
    assert checker.check_one_calls == []


# ------------------------------------------------------------------- cookies

def test_clean_cookies_reads_chrome_and_extension_exports():
    cleaned = api_service.clean_cookies([
        {"name": "a", "value": "1", "domain": ".example.com", "path": "/", "expires": -1, "size": 2,
         "session": True, "httpOnly": True, "secure": True, "sameSite": "None"},
        {"name": "b", "value": "2", "domain": "example.org", "expirationDate": 1893456000.5,
         "sameSite": "no_restriction", "hostOnly": True, "storeId": "0"},
        {"name": "c", "value": "3", "url": "https://example.net/", "sameSite": "unspecified"},
    ])
    assert cleaned[0] == {"name": "a", "value": "1", "domain": ".example.com", "path": "/",
                          "httpOnly": True, "secure": True, "sameSite": "None"}
    assert cleaned[1] == {"name": "b", "value": "2", "domain": "example.org", "expires": 1893456000.5, "sameSite": "None"}
    assert cleaned[2] == {"name": "c", "value": "3", "url": "https://example.net/"}


@pytest.mark.parametrize("bad", [
    "text", 5, [5], [{"value": "x", "domain": "a.com"}], [{"name": "a", "value": 1, "domain": "a.com"}],
    [{"name": "a", "value": "1"}], {"cookies": "x"},
])
def test_clean_cookies_rejects_nonsense(bad):
    with pytest.raises(api_service.ApiError) as raised:
        api_service.clean_cookies(bad)
    assert raised.value.status == 400


def test_cookies_need_a_running_profile(api):
    profile = _create(api)
    path = f"/v1/profiles/{profile['id']}/cookies"
    for call in (api.client.get(path), api.client.post(path, []), api.client.delete(path)):
        assert call[0] == 409 and call[1]["error"]["code"] == "not_running"


def test_cookies_are_read_set_and_cleared_through_the_browser(api, monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_cdp(ws, method, params=None, **_):
        calls.append((ws, method, params))
        return {"cookies": [{"name": "sid", "value": "42", "domain": "example.com"}]} if method == "Storage.getCookies" else {}

    monkeypatch.setattr(api_service, "cdp_call", fake_cdp)
    profile = _create(api)
    api.client.post(f"/v1/profiles/{profile['id']}/start")
    folder = Path(api.container.profiles.get_profile(profile["id"]).profile_path)
    (folder / "DevToolsActivePort").write_text("40000\n/devtools/browser/zzz\n")
    path = f"/v1/profiles/{profile['id']}/cookies"
    ws = "ws://127.0.0.1:40000/devtools/browser/zzz"

    status, body, _ = api.client.get(path)
    assert status == 200 and body["count"] == 1 and body["cookies"][0]["name"] == "sid"
    status, body, _ = api.client.post(path, {"cookies": [{"name": "x", "value": "y", "domain": ".a.com", "expires": -1}]})
    assert status == 200 and body == {"imported": 1}
    assert api.client.delete(path)[1] == {"cleared": True}
    assert calls == [
        (ws, "Storage.getCookies", None),
        (ws, "Storage.setCookies", {"cookies": [{"name": "x", "value": "y", "domain": ".a.com"}]}),
        (ws, "Storage.clearCookies", None),
    ]
    assert api.client.post(path, [{"name": "x"}])[0] == 400          # invalid cookies never reach the browser
    assert len(calls) == 3
    import re

    # a cookie's name and value must never be logged (a bare "42" inside a port or a pid number is not that)
    assert not any("sid" in e.message or re.search(r"\b42\b", e.message)
                   for e in api.container.logs.list_logs() if e.source == "api")
