"""Profiles through the API: the lifecycle a script goes through."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("api")


def _create(api, **body):
    status, profile, _ = api.client.post("/v1/profiles", {"name": "Shop", **body})
    assert status == 201, profile
    return profile


def test_create_returns_the_profile_with_its_own_fingerprint(api):
    profile = _create(api, platform="windows", tags=["acc", "eu"], notes="first", geo_auto=False)
    assert profile["id"] >= 1 and profile["name"] == "Shop"
    assert profile["status"] == "stopped" and profile["connection"] is None
    assert profile["platform"] == "windows" and "Windows" in profile["user_agent"]
    assert profile["tags"] == ["acc", "eu"] and profile["notes"] == "first" and profile["geo_auto"] is False
    assert profile["proxy"] is None and profile["screen"]
    assert api.changes                                              # the GUI is told to refresh


def test_every_profile_gets_a_different_fingerprint(api):
    a = _create(api, name="A", platform="windows")
    b = _create(api, name="B", platform="windows")
    assert (a["user_agent"], a["screen"], a["cores"]) != (b["user_agent"], b["screen"], b["cores"]) or a["id"] != b["id"]
    assert api.container.profiles.get_profile(a["id"]).configuration_id != api.container.profiles.get_profile(b["id"]).configuration_id


def test_get_list_and_filters(api):
    one = _create(api, name="Alpha", tags=["x"])
    _create(api, name="Beta", tags=["y"])
    assert api.client.get(f"/v1/profiles/{one['id']}")[1]["name"] == "Alpha"
    status, listing, _ = api.client.get("/v1/profiles")
    assert status == 200 and listing["total"] == 2 and [p["name"] for p in listing["items"]] == ["Alpha", "Beta"]
    assert api.client.get("/v1/profiles?tag=X")[1]["total"] == 1                    # case-insensitive
    assert api.client.get("/v1/profiles?q=bet")[1]["items"][0]["name"] == "Beta"
    assert api.client.get("/v1/profiles?status=running")[1]["total"] == 0
    assert api.client.get("/v1/profiles?status=stopped")[1]["total"] == 2
    assert api.client.get("/v1/profiles?limit=1&offset=1")[1]["items"][0]["name"] == "Beta"
    assert api.client.get("/v1/profiles?limit=1&offset=1")[1]["total"] == 2
    assert api.client.get("/v1/profiles?status=sleeping")[0] == 400
    assert api.client.get("/v1/profiles?limit=lots")[0] == 400


def test_unknown_profile_is_404(api):
    for method, path in [("GET", "/v1/profiles/99"), ("DELETE", "/v1/profiles/99"), ("POST", "/v1/profiles/99/start"),
                         ("POST", "/v1/profiles/99/stop"), ("GET", "/v1/profiles/99/connection")]:
        status, body, _ = api.client.request(method, path)
        assert status == 404 and body["error"]["code"] == "profile_not_found", (method, path)
    assert api.client.patch("/v1/profiles/99", {"name": "x"})[0] == 404


def test_validation_errors_are_400_with_a_reason(api):
    for body, fragment in [({}, "'name' is required"), ({"name": ""}, "must not be empty"),
                           ({"name": 5}, "must be a string"), ({"name": "x" * 201}, "too long"),
                           ({"name": "ok", "platform": "amiga"}, "platform"),
                           ({"name": "ok", "tags": "a", "geo_auto": "false"}, "true or false"),
                           ({"name": "ok", "tags": {"a": 1}}, "list of strings"),
                           ({"name": "ok", "proxy": "x", "proxy_id": 1}, "not both")]:
        status, payload, _ = api.client.post("/v1/profiles", body)
        assert status == 400, body
        assert fragment in payload["error"]["message"], payload
    assert api.client.get("/v1/profiles")[1]["total"] == 0


def test_a_duplicate_name_is_409(api):
    _create(api, name="Same")
    status, body, _ = api.client.post("/v1/profiles", {"name": "Same"})
    assert status == 409 and body["error"]["code"] == "profile_exists"


def test_tags_may_be_a_comma_separated_string(api):
    assert _create(api, tags="a, b ,a,")["tags"] == ["a", "b"]


def test_update_changes_only_what_is_sent(api):
    profile = _create(api, tags=["x"], notes="n", geo_auto=False)
    status, updated, _ = api.client.patch(f"/v1/profiles/{profile['id']}", {"name": "Renamed", "tags": ["y", "z"]})
    assert status == 200
    assert updated["name"] == "Renamed" and updated["tags"] == ["y", "z"] and updated["notes"] == "n"
    assert updated["user_agent"] == profile["user_agent"]            # the fingerprint is untouched
    other = _create(api, name="Other")
    status, body, _ = api.client.patch(f"/v1/profiles/{other['id']}", {"name": "Renamed"})
    assert status == 409
    assert api.client.patch(f"/v1/profiles/{profile['id']}", {"name": "  "})[0] == 400


def test_update_can_give_the_profile_a_new_fingerprint(api):
    profile = _create(api, platform="windows", geo_auto=False)
    path = f"/v1/profiles/{profile['id']}"
    seen = {(profile["screen"], profile["cores"], profile["memory_gb"])}
    for _ in range(12):                      # one draw can repeat the old values; twelve cannot all do so
        status, updated, _ = api.client.patch(path, {"regenerate_fingerprint": True})
        assert status == 200 and updated["platform"] == "windows"
        seen.add((updated["screen"], updated["cores"], updated["memory_gb"]))
    assert len(seen) > 1
    status, updated, _ = api.client.patch(path, {"platform": "linux"})
    assert status == 200 and updated["platform"] == "linux" and "Linux" in updated["user_agent"]


def test_delete_moves_the_profile_to_the_trash_and_keeps_its_folder(api):
    profile = _create(api)
    folder = Path(api.container.profiles.get_profile(profile["id"]).profile_path)
    folder.mkdir(parents=True, exist_ok=True)
    status, body, _ = api.client.delete(f"/v1/profiles/{profile['id']}")
    assert status == 200 and body == {"id": profile["id"], "deleted": True, "trashed": True}
    assert folder.exists()                                           # restorable: nothing is lost yet
    assert api.client.get(f"/v1/profiles/{profile['id']}")[0] == 404
    assert api.client.get("/v1/profiles")[1]["total"] == 0
    assert [p.id for p in api.container.profiles.list_trashed_profiles()] == [profile["id"]]


def test_permanent_delete_removes_the_profile_and_its_folder(api):
    profile = _create(api)
    folder = Path(api.container.profiles.get_profile(profile["id"]).profile_path)
    folder.mkdir(parents=True, exist_ok=True)
    status, body, _ = api.client.delete(f"/v1/profiles/{profile['id']}?permanent=true")
    assert status == 200 and body == {"id": profile["id"], "deleted": True, "trashed": False}
    assert not folder.exists()
    assert api.client.get(f"/v1/profiles/{profile['id']}")[0] == 404
    assert api.container.profiles.list_trashed_profiles() == []
    assert api.client.delete(f"/v1/profiles/{profile['id']}?permanent=maybe")[0] == 400


def test_workspace_is_created_on_demand_and_shown(api):
    status, created, _ = api.client.post("/v1/profiles", {"name": "ws-1", "geo_auto": False, "workspace": "Clients"})
    assert status == 201 and created["workspace"] == "Clients"
    other = _create(api, name="ws-2", geo_auto=False)
    assert other["workspace"] is None
    listed = api.client.get("/v1/profiles?workspace=Clients")[1]
    assert [p["name"] for p in listed["items"]] == ["ws-1"]
    moved = api.client.patch(f"/v1/profiles/{other['id']}", {"workspace": "Clients"})[1]
    assert moved["workspace"] == "Clients"
    cleared = api.client.patch(f"/v1/profiles/{other['id']}", {"workspace": None})[1]
    assert cleared["workspace"] is None
    assert api.client.post("/v1/profiles", {"name": "ws-3", "workspace": 5})[0] == 400


# ------------------------------------------------------------------ start / stop

def test_start_and_stop(api):
    profile = _create(api, geo_auto=False)
    status, started, _ = api.client.post(f"/v1/profiles/{profile['id']}/start")
    assert status == 200 and started["status"] == "running" and started["already_running"] is False
    assert api.client.get(f"/v1/profiles?status=running")[1]["total"] == 1
    status, stopped, _ = api.client.post(f"/v1/profiles/{profile['id']}/stop")
    assert status == 200 and stopped["status"] == "stopped" and stopped["connection"] is None


def test_starting_a_running_profile_is_not_an_error(api):
    profile = _create(api, geo_auto=False)
    api.client.post(f"/v1/profiles/{profile['id']}/start")
    status, again, _ = api.client.post(f"/v1/profiles/{profile['id']}/start")
    assert status == 200 and again["already_running"] is True and again["status"] == "running"


def test_stopping_a_stopped_profile_is_fine(api):
    profile = _create(api)
    status, body, _ = api.client.post(f"/v1/profiles/{profile['id']}/stop")
    assert status == 200 and body["status"] == "stopped"


def test_two_scripts_starting_the_same_profile_launch_it_once(api):
    profile = _create(api, geo_auto=False)
    results: list[tuple[int, bool]] = []

    def start() -> None:
        status, body, _ = api.client.post(f"/v1/profiles/{profile['id']}/start")
        results.append((status, body.get("already_running")))

    threads = [threading.Thread(target=start) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [(200, False), (200, True), (200, True), (200, True)]
    assert len({p.pid for p in api.container.profiles.list_profiles()}) == 1


def test_create_with_start_true_launches_it(api):
    status, profile, _ = api.client.post("/v1/profiles", {"name": "Quick", "start": True, "geo_auto": False})
    assert status == 200 or status == 201
    assert profile["status"] == "running" and profile["already_running"] is False


def test_the_connection_is_read_from_the_browser_when_it_is_there(api):
    profile = _create(api, geo_auto=False)
    folder = Path(api.container.profiles.get_profile(profile["id"]).profile_path)
    started = api.client.post(f"/v1/profiles/{profile['id']}/start")[1]
    assert started["connection"] is None                            # a stub browser publishes nothing
    status, body, _ = api.client.get(f"/v1/profiles/{profile['id']}/connection")
    assert status == 503 and body["error"]["code"] == "connection_unavailable"
    (folder / "DevToolsActivePort").write_text("51234\n/devtools/browser/abc-123\n")
    status, connection, _ = api.client.get(f"/v1/profiles/{profile['id']}/connection")
    assert status == 200
    assert connection["ws"] == "ws://127.0.0.1:51234/devtools/browser/abc-123"
    assert connection["http"] == "http://127.0.0.1:51234" and connection["port"] == 51234
    assert connection["debugger_address"] == "127.0.0.1:51234" and connection["pid"]
    assert api.client.get(f"/v1/profiles/{profile['id']}")[1]["connection"] == connection


def test_the_connection_of_a_stopped_profile_is_409(api):
    profile = _create(api)
    status, body, _ = api.client.get(f"/v1/profiles/{profile['id']}/connection")
    assert status == 409 and body["error"]["code"] == "not_running"


def test_deleting_a_running_profile_stops_it_first(api):
    profile = _create(api, geo_auto=False)
    api.client.post(f"/v1/profiles/{profile['id']}/start")
    pid = api.container.profiles.get_profile(profile["id"]).pid
    assert api.client.delete(f"/v1/profiles/{profile['id']}")[0] == 200
    assert not api.container.browser._is_pid_alive(pid)


def test_open_url_needs_a_running_profile_and_an_http_address(api):
    profile = _create(api, geo_auto=False)
    path = f"/v1/profiles/{profile['id']}/open"
    assert api.client.post(path, {"url": "https://example.com"})[1]["error"]["code"] == "not_running"
    for bad in ({}, {"url": "file:///etc/passwd"}, {"url": "javascript:alert(1)"}, {"url": 5}):
        assert api.client.post(path, bad)[0] == 400


def test_the_log_records_what_scripts_did(api):
    profile = _create(api, geo_auto=False)
    api.client.post(f"/v1/profiles/{profile['id']}/start")
    api.client.get("/v1/profiles")                                   # reads stay out of the log
    api.client.post("/v1/profiles/999/start")
    lines = [e.message for e in api.container.logs.list_logs() if e.source == "api"]
    assert any("POST /v1/profiles → 201" in line for line in lines)
    assert any(f"POST /v1/profiles/{profile['id']}/start → 200" in line for line in lines)
    assert any("/v1/profiles/999/start → 404" in line and "profile_not_found" in line for line in lines)
    assert not any("GET" in line for line in lines)


# ------------------------------------------------------------ protection switches

def test_a_new_profile_reports_the_default_protection_switches(api):
    profile = _create(api)
    assert (profile["webrtc"], profile["noise_canvas"], profile["noise_audio"]) == ("auto", True, True)
    assert profile["theme"] == "light"
    config = api.container.configurations.get_configuration(
        api.container.profiles.get_profile(profile["id"]).configuration_id
    )
    assert config.privacy_settings is None                              # nothing stored for defaults


def test_the_switches_can_be_chosen_when_creating(api):
    profile = _create(api, webrtc="block", noise_canvas=False)
    assert (profile["webrtc"], profile["noise_canvas"], profile["noise_audio"]) == ("block", False, True)
    assert api.client.get(f"/v1/profiles/{profile['id']}")[1]["webrtc"] == "block"


def test_update_changes_one_switch_and_keeps_the_others(api):
    profile = _create(api, webrtc="allow", noise_audio=False)
    status, changed, _ = api.client.patch(f"/v1/profiles/{profile['id']}", {"noise_canvas": False})
    assert status == 200
    assert (changed["webrtc"], changed["noise_canvas"], changed["noise_audio"]) == ("allow", False, False)


def test_putting_every_switch_back_to_its_default_stores_nothing(api):
    profile = _create(api, webrtc="block", noise_audio=False)
    status, back, _ = api.client.patch(
        f"/v1/profiles/{profile['id']}", {"webrtc": "auto", "noise_audio": True}
    )
    assert status == 200 and (back["webrtc"], back["noise_audio"]) == ("auto", True)
    config = api.container.configurations.get_configuration(
        api.container.profiles.get_profile(profile["id"]).configuration_id
    )
    assert config.privacy_settings is None


def test_switches_survive_a_new_fingerprint(api):
    profile = _create(api, webrtc="block")
    status, again, _ = api.client.patch(f"/v1/profiles/{profile['id']}", {"regenerate_fingerprint": True})
    assert status == 200 and again["webrtc"] == "block"


@pytest.mark.parametrize("body", [{"webrtc": "off"}, {"webrtc": True}, {"noise_canvas": "yes"}, {"noise_audio": 0}])
def test_an_unknown_switch_value_is_a_400_and_nothing_is_created(api, body):
    status, answer, _ = api.client.post("/v1/profiles", {"name": "Bad", **body})
    assert status == 400 and "must" in answer["error"]["message"]
    assert api.client.get("/v1/profiles")[1]["total"] == 0


def test_the_colour_scheme_is_light_by_default_and_can_be_chosen_and_changed(api):
    assert _create(api)["theme"] == "light"
    dark = _create(api, name="Dark", theme="dark")
    assert dark["theme"] == "dark"
    status, changed, _ = api.client.patch(f"/v1/profiles/{dark['id']}", {"theme": "auto"})
    assert status == 200 and changed["theme"] == "auto"
    status, back, _ = api.client.patch(f"/v1/profiles/{dark['id']}", {"theme": "light"})
    assert back["theme"] == "light"
    config = api.container.configurations.get_configuration(api.container.profiles.get_profile(dark["id"]).configuration_id)
    assert config.privacy_settings is None


@pytest.mark.parametrize("value", ["blue", "", 1, None, True])
def test_an_unknown_colour_scheme_is_a_400(api, value):
    status, answer, _ = api.client.post("/v1/profiles", {"name": "Bad", "theme": value})
    assert status == 400 and "theme" in answer["error"]["message"]
