"""Creating many profiles at once."""

from __future__ import annotations

import pytest

from antidetect.application.bulk_service import MAX_COUNT, BulkRequest, numbered_names


@pytest.fixture()
def bulk(gui_container):
    return gui_container.bulk


def _names(container) -> list[str]:
    return [p.name for p in container.profiles.list_profiles()]


# ------------------------------------------------------------------ naming

def test_names_are_numbered_from_one():
    assert numbered_names("Shop", 3, set()) == ["Shop 1", "Shop 2", "Shop 3"]


def test_the_number_goes_where_the_template_says():
    assert numbered_names("Acc #{n} (EU)", 2, set()) == ["Acc #1 (EU)", "Acc #2 (EU)"]


def test_taken_names_are_skipped_not_reused_and_the_comparison_ignores_case():
    assert numbered_names("Shop", 3, {"shop 1", "Shop 3"}) == ["Shop 2", "Shop 4", "Shop 5"]


def test_extra_spaces_in_the_name_are_tidied_and_an_empty_name_is_refused():
    assert numbered_names("  My   shop ", 1, set()) == ["My shop 1"]
    with pytest.raises(ValueError):
        numbered_names("   ", 1, set())


# ----------------------------------------------------------------- validation

@pytest.mark.parametrize("count", [0, -1, MAX_COUNT + 1, "5", None])
def test_the_count_must_be_a_sensible_number(bulk, count):
    with pytest.raises(ValueError, match="between 1 and"):
        bulk.create(BulkRequest(name="X", count=count))


def test_an_unknown_system_or_switch_is_refused_before_anything_is_created(bulk, gui_container):
    with pytest.raises(ValueError):
        bulk.create(BulkRequest(name="X", count=2, platform="beos"))
    with pytest.raises(ValueError):
        bulk.create(BulkRequest(name="X", count=2, privacy_settings={"webrtc": "sideways"}))
    assert _names(gui_container) == []


# ------------------------------------------------------------------- creating

def test_it_creates_the_requested_number_each_with_its_own_fingerprint(bulk, gui_container):
    result = bulk.create(BulkRequest(name="Shop", count=5, platform="windows"))
    assert result.created == 5 and result.failed == []
    assert _names(gui_container) == [f"Shop {i}" for i in range(1, 6)]
    configs = {gui_container.profiles.get_profile(i).configuration_id for i in result.profile_ids}
    assert len(configs) == 5                                          # never one fingerprint shared by all
    assert {gui_container.configurations.get_configuration(c).platform for c in configs} == {"windows"}


def test_the_common_settings_reach_every_profile(bulk, gui_container):
    workspace = gui_container.workspaces.create_workspace("Clients")
    result = bulk.create(BulkRequest(
        name="Acc", count=3, platform="windows", workspace_id=workspace.id, tags=("eu", "shop"),
        start_url="https://example.com/", geo_auto=False, privacy_settings={"webrtc": "block", "noise_audio": False},
    ))
    for pid in result.profile_ids:
        profile = gui_container.profiles.get_profile(pid)
        assert profile.workspace_id == workspace.id and sorted(profile.tags) == ["eu", "shop"]
        assert profile.start_url == "https://example.com/" and profile.geo_auto is False
        config = gui_container.configurations.get_configuration(profile.configuration_id)
        assert config.privacy_settings == {"webrtc": "block", "noise_audio": False}


def test_numbering_continues_after_profiles_that_already_exist(bulk, gui_container):
    bulk.create(BulkRequest(name="Shop", count=2))
    bulk.create(BulkRequest(name="Shop", count=2))
    assert _names(gui_container) == ["Shop 1", "Shop 2", "Shop 3", "Shop 4"]


def test_progress_is_reported_for_every_profile(bulk):
    seen: list[tuple[int, int]] = []
    bulk.create(BulkRequest(name="P", count=4), on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


# -------------------------------------------------------------------- proxies

PROXIES = "203.0.113.1:8080\n203.0.113.2:8080\n203.0.113.3:8080"


def test_each_profile_gets_the_next_proxy_and_none_is_shared(bulk, gui_container):
    result = bulk.create(BulkRequest(name="P", count=3, proxy_text=PROXIES))
    used = [gui_container.profiles.get_profile(i).proxy_id for i in result.profile_ids]
    assert None not in used and len(set(used)) == 3
    assert (result.with_proxy, result.without_proxy) == (3, 0)
    hosts = [gui_container.proxies.get_proxy(i).host for i in used]
    assert hosts == ["203.0.113.1", "203.0.113.2", "203.0.113.3"]       # in the order they were given


def test_profiles_beyond_the_proxies_get_none_rather_than_a_shared_one(bulk, gui_container):
    result = bulk.create(BulkRequest(name="P", count=5, proxy_text=PROXIES))
    used = [gui_container.profiles.get_profile(i).proxy_id for i in result.profile_ids]
    assert used[3:] == [None, None] and None not in used[:3]
    assert (result.with_proxy, result.without_proxy) == (3, 2)


def test_spare_proxies_are_still_added_to_the_list(bulk, gui_container):
    bulk.create(BulkRequest(name="P", count=1, proxy_text=PROXIES))
    assert len(gui_container.proxies.list_proxies()) == 3


def test_proxies_already_in_the_list_come_first_then_pasted_ones(bulk, gui_container):
    first = gui_container.proxies.import_text("198.51.100.9:3128").ids[0]
    result = bulk.create(BulkRequest(name="P", count=3, proxy_ids=(first,), proxy_text="203.0.113.1:8080\n203.0.113.2:8080"))
    hosts = [gui_container.proxies.get_proxy(gui_container.profiles.get_profile(i).proxy_id).host for i in result.profile_ids]
    assert hosts == ["198.51.100.9", "203.0.113.1", "203.0.113.2"]


def test_a_proxy_named_twice_is_used_once(bulk, gui_container):
    result = bulk.create(BulkRequest(name="P", count=3, proxy_text="203.0.113.1:8080\n203.0.113.1:8080"))
    assert (result.with_proxy, result.without_proxy) == (1, 2)


def test_unreadable_proxy_lines_are_reported_and_the_rest_are_used(bulk):
    result = bulk.create(BulkRequest(name="P", count=2, proxy_text="not a proxy\n203.0.113.1:8080"))
    assert result.invalid_proxies == ["not a proxy"]
    assert (result.with_proxy, result.without_proxy) == (1, 1)


def test_the_proxy_protocol_applies_to_lines_that_do_not_say(bulk, gui_container):
    result = bulk.create(BulkRequest(name="P", count=2, proxy_text="203.0.113.1:1080\nhttp://203.0.113.2:8080", proxy_protocol="SOCKS5"))
    protocols = [gui_container.proxies.get_proxy(gui_container.profiles.get_profile(i).proxy_id).protocol.value for i in result.profile_ids]
    assert protocols == ["SOCKS5", "HTTP"]


# ---------------------------------------------------------------- failures

def test_one_failing_profile_is_reported_and_the_rest_are_still_created(bulk, gui_container, monkeypatch):
    real = gui_container.profiles.create_profile

    def flaky(name, *args, **kwargs):
        if name == "P 2":
            raise RuntimeError("disk full")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(gui_container.profiles, "create_profile", flaky)
    result = bulk.create(BulkRequest(name="P", count=3))
    assert result.created == 2 and result.failed == ["P 2: disk full"]
    assert _names(gui_container) == ["P 1", "P 3"]


# -------------------------------------------------------------------- settle

def test_settling_checks_unmeasured_proxies_once_then_aligns_every_profile(bulk, gui_container, monkeypatch):
    result = bulk.create(BulkRequest(name="P", count=3, proxy_text=PROXIES))
    checked: list[list[int]] = []
    monkeypatch.setattr(gui_container.proxies, "check_all", lambda **kw: checked.append(list(kw["ids"])))
    synced: list[int] = []
    monkeypatch.setattr(gui_container.profiles, "sync_geo", lambda pid: synced.append(pid))

    progress: list[tuple[int, int]] = []
    aligned = bulk.settle(result.profile_ids, on_progress=lambda a, b: progress.append((a, b)))

    assert len(checked) == 1 and len(checked[0]) == 3                  # one concurrent pass, not three
    assert synced == result.profile_ids and aligned == 3
    assert progress[-1] == (3, 3)


def test_settling_leaves_profiles_with_geo_matching_off_alone(bulk, gui_container, monkeypatch):
    result = bulk.create(BulkRequest(name="P", count=2, geo_auto=False))
    synced: list[int] = []
    monkeypatch.setattr(gui_container.profiles, "sync_geo", lambda pid: synced.append(pid))
    assert bulk.settle(result.profile_ids) == 0 and synced == []


def test_a_failing_proxy_check_does_not_stop_the_alignment(bulk, gui_container, monkeypatch):
    result = bulk.create(BulkRequest(name="P", count=2, proxy_text=PROXIES))
    monkeypatch.setattr(gui_container.proxies, "check_all", lambda **kw: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(gui_container.profiles, "sync_geo", lambda pid: None)
    assert bulk.settle(result.profile_ids) == 2



def test_the_colour_scheme_reaches_every_profile_and_defaults_to_light(bulk, gui_container):
    dark = bulk.create(BulkRequest(name="Dark", count=2, privacy_settings={"theme": "dark"}))
    plain = bulk.create(BulkRequest(name="Plain", count=1))
    for pid in dark.profile_ids:
        config = gui_container.configurations.get_configuration(gui_container.profiles.get_profile(pid).configuration_id)
        assert config.privacy_settings == {"theme": "dark"}
    config = gui_container.configurations.get_configuration(gui_container.profiles.get_profile(plain.profile_ids[0]).configuration_id)
    assert config.privacy_settings is None                                  # light is the default: nothing stored
