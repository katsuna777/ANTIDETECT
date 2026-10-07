"""Several access keys: each script or teammate gets its own and can lose it on its own."""

from __future__ import annotations

import pytest

from antidetect.api import ApiKeyError, ApiSettings
from tests.api.conftest import Client


@pytest.fixture()
def settings(container):
    return ApiSettings(container.settings)


def test_there_is_always_a_first_key_called_main(settings):
    (key,) = settings.keys()
    assert key.name == "Main" and key.token.startswith("ad_") and len(key.token) >= 40
    assert len(key.id) == 8 and key.created_at.endswith("+00:00")
    assert settings.keys()[0] == key and settings.token == key.token        # stable between calls


def test_the_token_of_the_first_version_becomes_the_main_key(container):
    container.settings.set("api.token", "ad_old_single_token_from_version_one")
    (key,) = ApiSettings(container.settings).keys()
    assert key.name == "Main" and key.token == "ad_old_single_token_from_version_one"


def test_keys_are_added_renamed_regenerated_and_deleted(settings):
    first = settings.keys()[0]
    second = settings.add_key("Parser")
    assert [k.name for k in settings.keys()] == ["Main", "Parser"] and second.token != first.token
    renamed = settings.rename_key(second.id, "Scraper")
    assert renamed.token == second.token and settings.get_key(second.id).name == "Scraper"
    fresh = settings.regenerate_key(second.id)
    assert fresh.id == second.id and fresh.name == "Scraper" and fresh.token != second.token
    assert settings.find(second.token) is None and settings.find(fresh.token) == fresh
    settings.delete_key(second.id)
    assert [k.name for k in settings.keys()] == ["Main"] and settings.find(fresh.token) is None


@pytest.mark.parametrize("name, reason", [("", "empty"), ("   ", "empty"), ("x" * 61, "long"), ("main", "duplicate"), (" MAIN ", "duplicate")])
def test_bad_key_names_say_why(settings, name, reason):
    with pytest.raises(ApiKeyError) as raised:
        settings.add_key(name)
    assert raised.value.reason == reason
    assert len(settings.keys()) == 1


def test_a_name_can_be_kept_when_renaming_to_itself_with_other_case(settings):
    key = settings.keys()[0]
    assert settings.rename_key(key.id, "MAIN").name == "MAIN"


def test_the_last_key_cannot_be_deleted(settings):
    with pytest.raises(ApiKeyError) as raised:
        settings.delete_key(settings.keys()[0].id)
    assert raised.value.reason == "last" and len(settings.keys()) == 1
    settings.add_key("Other")
    with pytest.raises(KeyError):
        settings.delete_key("nope")


def test_find_matches_only_exact_tokens(settings):
    key = settings.keys()[0]
    assert settings.find(key.token) == key
    for wrong in ("", "ad_", key.token + "x", key.token[:-1], key.token.upper()):
        assert settings.find(wrong) is None


def test_a_corrupt_key_list_starts_over_instead_of_locking_everyone_out(container):
    container.settings.set("api.keys", "{not json")
    (key,) = ApiSettings(container.settings).keys()
    assert key.name == "Main"


# --------------------------------------------------------------------- over HTTP

def test_every_key_works_and_a_deleted_one_stops_at_once(api):
    other = api.manager.add_key("Second script")
    first = Client(api.manager.port, api.manager.settings.keys()[0].token)
    second = Client(api.manager.port, other.token)
    assert first.get("/v1/status")[0] == 200 and second.get("/v1/status")[0] == 200
    api.manager.delete_key(other.id)
    assert second.get("/v1/status")[0] == 401 and first.get("/v1/status")[0] == 200


def test_regenerating_one_key_leaves_the_others_alone(api):
    other = api.manager.add_key("Other")
    old_main = api.manager.settings.keys()[0].token
    fresh = api.manager.regenerate_key(other.id)
    assert Client(api.manager.port, other.token).get("/v1/status")[0] == 401
    assert Client(api.manager.port, fresh.token).get("/v1/status")[0] == 200
    assert Client(api.manager.port, old_main).get("/v1/status")[0] == 200


def test_requests_are_counted_per_key(api):
    other = api.manager.add_key("Other")
    main_id = api.manager.settings.keys()[0].id
    mine, theirs = api.client, Client(api.manager.port, other.token)
    for _ in range(3):
        mine.get("/v1/status")
    theirs.get("/v1/profiles")
    mine.get("/v1/nope")                                          # unknown endpoint, but authenticated
    Client(api.manager.port, "ad_wrong").get("/v1/status")        # not a key: counted for nobody
    assert api.manager.usage(main_id).requests == 4
    assert api.manager.usage(other.id).requests == 1
    assert api.manager.usage(other.id).last_used is not None
    assert api.manager.usage("unknown").requests == 0 and api.manager.usage("unknown").last_used is None
    api.manager.delete_key(other.id)
    assert api.manager.usage(other.id).requests == 0


def test_the_log_names_the_key_that_did_it(api):
    other = api.manager.add_key("Parser")
    Client(api.manager.port, other.token).post("/v1/profiles", {"name": "ByParser"})
    api.client.post("/v1/profiles", {"name": "ByMain"})
    lines = [e.message for e in api.container.logs.list_logs() if e.source == "api"]
    assert any("API [Parser] POST /v1/profiles → 201" in line for line in lines)
    assert any("API [Main] POST /v1/profiles → 201" in line for line in lines)
    assert any("key “Parser” created" in line for line in lines)
