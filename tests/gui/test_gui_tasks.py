"""Task factories map cleanly onto the application services.

They are plain callables (no Qt), so they run synchronously here:
``factory(container, ...)(progress)`` and assert on the domain result.
"""

from __future__ import annotations

import pytest

from antidetect.domain.errors import ProfileNotFoundError, ProfileNotRunningError, ProxyNotFoundError
from antidetect.gui.models import ProfileRow, ProxyRow
from antidetect.gui.models.specs import ProfileSpec
from antidetect.gui.workers import tasks


def _run(task):
    return task(lambda done, total: None)


def _spec(name="alpha", **overrides) -> ProfileSpec:
    values = dict(name=name, platform="windows", geo_auto=False)
    values.update(overrides)
    return ProfileSpec(**values)


def test_profile_rows_start_empty(gui_container):
    assert _run(tasks.list_profile_rows(gui_container)) == []


def test_create_profile_gets_its_own_fingerprint_and_metadata(gui_container):
    profile = _run(tasks.create_profile(gui_container, _spec(notes="n", tags=["a", "B"])))
    rows = _run(tasks.list_profile_rows(gui_container))
    assert len(rows) == 1 and isinstance(rows[0], ProfileRow)
    row = rows[0]
    assert row.id == profile.id and row.name == "alpha"
    assert row.platform == "windows" and row.browser.startswith("Chrome ")
    assert row.screen and "×" in row.screen
    assert row.gpu and "Direct3D" not in row.gpu and "ANGLE" not in row.gpu
    assert row.notes == "n" and row.tags == ("a", "B") and row.geo_auto is False
    assert row.running is False and row.last_started_at is None


def test_two_profiles_never_share_a_fingerprint(gui_container):
    _run(tasks.create_profile(gui_container, _spec("one")))
    _run(tasks.create_profile(gui_container, _spec("two")))
    first, second = _run(tasks.list_profile_rows(gui_container))
    assert first.configuration_id != second.configuration_id


def test_create_profile_with_a_pasted_proxy_adds_and_assigns_it(gui_container):
    profile = _run(tasks.create_profile(
        gui_container, _spec(proxy_text="203.0.113.7:8080:user:pw", proxy_protocol="SOCKS5")
    ))
    (row,) = _run(tasks.list_profile_rows(gui_container))
    assert row.proxy_id == profile.proxy_id and row.proxy_endpoint == "203.0.113.7:8080"
    assert row.proxy_protocol == "SOCKS5"
    (proxy,) = _run(tasks.list_proxy_rows(gui_container)).rows
    assert proxy.is_manual and proxy.username == "user" and proxy.used_by == ("alpha",)


def test_create_profile_rejects_an_unreadable_proxy(gui_container):
    with pytest.raises(ValueError):
        _run(tasks.create_profile(gui_container, _spec(proxy_text="not a proxy")))
    assert _run(tasks.list_profile_rows(gui_container)) == []  # nothing half-created


def test_update_profile_changes_metadata_and_fingerprint_fields(gui_container):
    _run(tasks.create_profile(gui_container, _spec()))
    (row,) = _run(tasks.list_profile_rows(gui_container))
    spec = _spec("renamed", notes="x", tags=["t"], fingerprint={"timezone": "Europe/Berlin", "locale": "de-DE", "language": "de"})
    _run(tasks.update_profile(gui_container, row.id, spec, row))
    (after,) = _run(tasks.list_profile_rows(gui_container))
    assert after.name == "renamed" and after.notes == "x" and after.tags == ("t",)
    assert after.timezone == "Europe/Berlin" and after.locale == "de-DE"
    assert after.configuration_id == row.configuration_id  # edited in place


def test_changing_the_system_generates_a_matching_fingerprint(gui_container):
    _run(tasks.create_profile(gui_container, _spec()))
    (row,) = _run(tasks.list_profile_rows(gui_container))
    _run(tasks.update_profile(gui_container, row.id, _spec(platform="macos"), row))
    (after,) = _run(tasks.list_profile_rows(gui_container))
    assert after.platform == "macos" and "Apple" in after.gpu or "M" in after.gpu
    assert after.timezone == row.timezone  # geo is kept across a system change


def test_update_proxy_can_attach_and_detach(gui_container):
    _run(tasks.create_profile(gui_container, _spec()))
    (row,) = _run(tasks.list_profile_rows(gui_container))
    _run(tasks.update_profile(gui_container, row.id, _spec(proxy_text="198.51.100.5:3128"), row))
    (attached,) = _run(tasks.list_profile_rows(gui_container))
    assert attached.proxy_endpoint == "198.51.100.5:3128"
    _run(tasks.update_profile(gui_container, row.id, _spec(proxy_id=None), attached))
    (detached,) = _run(tasks.list_profile_rows(gui_container))
    assert detached.proxy_id is None


def test_trashed_profiles_leave_the_table_and_deleting_them_for_good_frees_their_fingerprints(gui_container):
    _run(tasks.create_profile(gui_container, _spec("a")))
    _run(tasks.create_profile(gui_container, _spec("b")))
    before = len(gui_container.configurations.list_configurations())
    ids = [r.id for r in _run(tasks.list_profile_rows(gui_container))]
    assert _run(tasks.trash_profiles(gui_container, ids)) == ids
    assert _run(tasks.list_profile_rows(gui_container)) == []
    assert {r.name for r in _run(tasks.list_trash_rows(gui_container))} == {"a", "b"}
    assert all(r.deleted_at is not None for r in _run(tasks.list_trash_rows(gui_container)))
    assert len(gui_container.configurations.list_configurations()) == before      # still there: restorable
    assert _run(tasks.restore_profiles(gui_container, ids[:1])) == ["a"]
    assert [r.name for r in _run(tasks.list_profile_rows(gui_container))] == ["a"]
    assert _run(tasks.purge_profiles(gui_container, ids[1:])) == 1
    assert _run(tasks.list_trash_rows(gui_container)) == []
    assert len(gui_container.configurations.list_configurations()) == before - 1


def test_profile_lifecycle_tasks_raise_domain_errors(gui_container):
    for factory in (tasks.start_profile, tasks.stop_profile, tasks.restart_profile):
        with pytest.raises(ProfileNotFoundError):
            _run(factory(gui_container, 4242))


def test_open_url_in_a_stopped_profile_requires_a_running_one_via_service(gui_container):
    _run(tasks.create_profile(gui_container, _spec()))
    with pytest.raises(ProfileNotRunningError):
        gui_container.profiles.open_url(1, "https://example.com/")


def test_import_proxies_reports_added_existing_and_invalid(gui_container):
    summary = _run(tasks.import_proxies(gui_container, "1.1.1.1:80\n2.2.2.2:80:u:p\ngarbage", "HTTP", check=False))
    assert (summary.added, summary.existing, len(summary.invalid)) == (2, 0, 1)
    again = _run(tasks.import_proxies(gui_container, "1.1.1.1:80", "HTTP", check=False))
    assert (again.added, again.existing) == (0, 1)


def test_proxy_rows_expose_who_uses_each_proxy(gui_container):
    _run(tasks.import_proxies(gui_container, "9.9.9.9:80", "HTTP", check=False))
    (proxy,) = _run(tasks.list_proxy_rows(gui_container)).rows
    assert isinstance(proxy, ProxyRow) and proxy.address == "9.9.9.9:80" and proxy.used_by == ()


def test_manual_proxies_survive_the_dead_proxy_cleanup(gui_container):
    _run(tasks.import_proxies(gui_container, "7.7.7.7:80", "HTTP", check=False))
    (proxy,) = _run(tasks.list_proxy_rows(gui_container)).rows
    gui_container.proxies._proxies.apply_outcomes([(proxy.id, __import__("antidetect.domain.enums.proxy_status", fromlist=["x"]).ProxyStatus.DEAD, 5, __import__("datetime").datetime.now())])
    assert gui_container.proxies.remove_dead() == 0
    assert len(_run(tasks.list_proxy_rows(gui_container)).rows) == 1


def test_delete_proxies_task(gui_container):
    _run(tasks.import_proxies(gui_container, "5.5.5.5:80\n6.6.6.6:80", "HTTP", check=False))
    ids = [p.id for p in _run(tasks.list_proxy_rows(gui_container)).rows]
    assert _run(tasks.delete_proxies(gui_container, ids[:1])) == 1
    assert len(_run(tasks.list_proxy_rows(gui_container)).rows) == 1


def test_check_proxy_task_raises_domain_errors(gui_container):
    with pytest.raises(ProxyNotFoundError):
        gui_container.proxies.check_proxy(4242)


def test_dialog_data_bundles_proxies_names_and_configuration(gui_container):
    _run(tasks.create_profile(gui_container, _spec()))
    data = _run(tasks.load_dialog_data(gui_container, 1))
    assert data["names"] == {"alpha"} and data["configuration"].platform == "windows"
    assert data["proxies"] == []


def test_browser_info_returns_path_and_version(gui_container):
    path, version = _run(tasks.browser_info(gui_container))
    assert path is None or path.exists()
    assert version is None or version.count(".") == 3


def test_log_tasks_round_trip(gui_container, tmp_path):
    gui_container.logs.info("t", "hello")
    entries = _run(tasks.list_logs(gui_container, 0))
    assert any(e.message == "hello" for e in entries)
    target = tmp_path / "out.log"
    assert _run(tasks.export_logs(gui_container, target)) == target and target.exists()
    _run(tasks.clear_logs(gui_container))
    assert _run(tasks.list_logs(gui_container, 0)) == []


def _add_proxies(container, count: int, source: str = "free-list") -> None:
    from antidetect.domain.enums.proxy_status import ProxyProtocol
    from antidetect.domain.models.proxy_entry import ProxyEntry

    container.proxies._proxies.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host=f"203.0.113.{i}", port=80, source=source) for i in range(count)]
    )


def test_proxy_listing_shows_everything_stored_with_its_counts(gui_container):
    from antidetect.domain.enums.proxy_status import ProxyStatus

    _run(tasks.import_proxies(gui_container, "5.5.5.5:80", "HTTP", check=False))
    _add_proxies(gui_container, 4)
    ids = [r.id for r in _run(tasks.list_proxy_rows(gui_container)).rows]
    gui_container.proxies._proxies.apply_outcomes(
        [(ids[0], ProxyStatus.WORKING, 0, __import__("datetime").datetime.now())]
    )
    listing = _run(tasks.list_proxy_rows(gui_container))
    assert len(listing.rows) == listing.total == 5 and listing.working == 1


def test_the_profile_dialog_offers_every_stored_proxy(gui_container):
    _run(tasks.import_proxies(gui_container, "5.5.5.5:80", "HTTP", check=False))
    _add_proxies(gui_container, 3)
    data = _run(tasks.load_dialog_data(gui_container))
    assert len(data["proxies"]) == 4 and "5.5.5.5:80" in {p.address for p in data["proxies"]}


def test_profile_rows_ask_the_database_only_for_assigned_proxies(gui_container, monkeypatch):
    _run(tasks.import_proxies(gui_container, "6.6.6.6:80", "HTTP", check=False))
    _add_proxies(gui_container, 25)
    proxy = next(r for r in tasks.build_proxy_rows(gui_container) if r.address == "6.6.6.6:80")
    _run(tasks.create_profile(gui_container, _spec("with-proxy", proxy_id=proxy.id)))
    seen = []
    real = gui_container.proxies.list_proxies
    monkeypatch.setattr(gui_container.proxies, "list_proxies", lambda **kw: (seen.append(kw.get("ids")), real(**kw))[1])
    (row,) = _run(tasks.list_profile_rows(gui_container))
    assert seen == [[proxy.id]] and row.proxy_endpoint == "6.6.6.6:80"


def test_running_ids_reports_only_what_is_really_running(gui_container):
    _run(tasks.create_profile(gui_container, _spec("idle")))
    assert _run(tasks.running_ids(gui_container)) == frozenset()


def test_proxy_service_filters_by_ids_and_an_empty_list_means_none(gui_container):
    _run(tasks.import_proxies(gui_container, "1.1.1.1:80\n2.2.2.2:80", "HTTP", check=False))
    first, second = [p.proxy.id for p in gui_container.proxies.list_proxies(sort="id")]
    assert [p.proxy.id for p in gui_container.proxies.list_proxies(ids=[second])] == [second]
    assert gui_container.proxies.list_proxies(ids=[]) == []
    assert len(gui_container.proxies.list_proxies()) == 2


# ------------------------------------------------- creation: a fast row, then the network part


def _no_network(container, monkeypatch):
    """Creating must never wait on a proxy check or an own-IP lookup."""
    def boom(*_a, **_k):
        raise AssertionError("network work during create_profile")

    monkeypatch.setattr(container.proxies, "check_proxy", boom)
    monkeypatch.setattr(container.proxies, "check_all", boom)
    container.profiles._geo_lookup = boom


def test_create_profile_does_no_network_work_even_with_a_pasted_proxy_and_auto_geo(gui_container, monkeypatch):
    _no_network(gui_container, monkeypatch)
    spec = _spec("fast", geo_auto=True, proxy_text="203.0.113.9:8080:u:p")
    profile = _run(tasks.create_profile(gui_container, spec))
    assert profile.name == "fast" and profile.proxy_id is not None and profile.geo_auto is True


def test_needs_settling_only_when_the_network_is_still_needed():
    assert not tasks.needs_settling(_spec(geo_auto=False), start=False)
    assert not tasks.needs_settling(_spec(geo_auto=True, proxy_id=3), start=False)   # saved proxy: geo came from its stored country
    assert tasks.needs_settling(_spec(geo_auto=True), start=False)                  # no proxy: the own-IP country is looked up
    assert tasks.needs_settling(_spec(geo_auto=False, proxy_text="1.2.3.4:80"), start=False)
    assert tasks.needs_settling(_spec(geo_auto=False, proxy_id=3), start=True)


def test_settle_profile_measures_a_new_proxy_once_and_aligns_the_geo_to_its_country(gui_container):
    from antidetect.infrastructure.proxy.checker import CheckOutcome
    from tests.support.fakes import StubChecker

    profile = _run(tasks.create_profile(gui_container, _spec("geo", geo_auto=True, proxy_text="203.0.113.9:8080")))
    proxy = gui_container.proxies.get_proxy(profile.proxy_id)
    checker = StubChecker({proxy.id: CheckOutcome(proxy=proxy, ok=True, latency_ms=90, country="Germany", country_code="DE")})
    gui_container.proxies._checker = checker
    _run(tasks.settle_profile(gui_container, profile.id))
    (row,) = _run(tasks.list_profile_rows(gui_container))
    assert row.timezone == "Europe/Berlin" and row.locale == "de-DE" and row.proxy_country_code == "DE"
    assert len(checker.check_one_calls) == 1
    _run(tasks.settle_profile(gui_container, profile.id))
    assert len(checker.check_one_calls) == 1  # already measured: not checked again


def test_settle_profile_without_a_proxy_uses_the_country_of_the_own_ip(gui_container):
    gui_container.profiles._geo_lookup = lambda: "FR"
    profile = _run(tasks.create_profile(gui_container, _spec("home", geo_auto=True)))
    _run(tasks.settle_profile(gui_container, profile.id))
    (row,) = _run(tasks.list_profile_rows(gui_container))
    assert row.timezone == "Europe/Paris" and row.locale == "fr-FR"


def test_settle_profile_with_start_launches_the_browser(gui_container, fake_chromium):
    gui_container.browser.set_chromium_path(fake_chromium)
    profile = _run(tasks.create_profile(gui_container, _spec("go")))
    started = _run(tasks.settle_profile(gui_container, profile.id, start=True))
    try:
        assert started.status.value == "RUNNING" and started.pid
    finally:
        gui_container.profiles.stop_profile(profile.id)


def test_importing_proxies_with_check_checks_them_in_one_concurrent_batch(gui_container):
    from tests.support.fakes import StubChecker

    checker = StubChecker()
    gui_container.proxies._checker = checker
    progress = []
    summary = tasks.import_proxies(gui_container, "1.1.1.1:80\n2.2.2.2:80\n3.3.3.3:80", "HTTP", check=True)(
        lambda done, total: progress.append((done, total))
    )
    assert summary.added == 3
    assert len(checker.check_all_calls) == 3 and checker.check_one_calls == []  # not one by one
    assert progress and progress[-1] == (3, 3)
    assert all(r.status == "WORKING" for r in _run(tasks.list_proxy_rows(gui_container)).rows)
