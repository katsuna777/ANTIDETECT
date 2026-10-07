from __future__ import annotations

from datetime import datetime, timezone

import pytest

from antidetect.domain.enums.proxy_status import Anonymity, ProxyProtocol, ProxyStatus
from antidetect.domain.errors import (
    ProxyNotFoundError,
    ProxyNotUsableError,
)
from antidetect.domain.models.proxy_check import ProxyCheck
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from antidetect.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from tests.conftest import build_service


@pytest.fixture()
def ctx(config, fake_chromium):
    svc, db = build_service(config, fake_chromium)
    yield svc, db
    for profile in svc.list_profiles():
        if profile.status.value == "RUNNING":
            svc.stop_profile(profile.id)
    db.close()


def _add_proxy(svc, db, host="1.2.3.4", port=8080, status=ProxyStatus.UNKNOWN):
    repo = svc._proxies or SqliteProxyRepository(db)
    repo.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host=host, port=port, source="test")])
    proxy = repo.list()[0]
    if status is not ProxyStatus.UNKNOWN:
        repo.apply_outcomes([(proxy.id, status, 0, datetime.now(timezone.utc))])
    return repo.get(proxy.id)


def test_assign_and_remove_proxy(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db, status=ProxyStatus.WORKING)
    profile = svc.create_profile("ProxyOne")
    assert profile.proxy_id is None

    assigned = svc.assign_proxy(profile.id, proxy.id)
    assert assigned.proxy_id == proxy.id

    removed = svc.remove_proxy(profile.id)
    assert removed.proxy_id is None


def test_assign_unknown_proxy_raises(ctx):
    svc, _ = ctx
    profile = svc.create_profile("NoProxy")
    with pytest.raises(ProxyNotFoundError):
        svc.assign_proxy(profile.id, 999_999)


def test_create_profile_with_proxy(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db)
    profile = svc.create_profile("WithProxy", proxy_id=proxy.id)
    assert profile.proxy_id == proxy.id


def test_update_profile_changes_proxy(ctx):
    svc, db = ctx
    a = _add_proxy(svc, db, host="5.5.5.5")
    b = _add_proxy(svc, db, host="6.6.6.6")
    profile = svc.create_profile("Switch")
    svc.update_profile(profile.id, proxy_id=a.id)
    svc.update_profile(profile.id, proxy_id=b.id)
    assert svc.get_profile(profile.id).proxy_id == b.id


def test_get_profile_details_joins_latest_check(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db, host="203.0.113.7", status=ProxyStatus.WORKING)
    SqliteProxyCheckRepository(db).insert_many(
        [
            ProxyCheck(
                id=0,
                proxy_id=proxy.id,
                checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                status=ProxyStatus.WORKING,
                latency_ms=123,
                external_ip="198.51.100.44",
                country="Germany",
                country_code="DE",
                anonymity=Anonymity.ELITE,
            )
        ]
    )
    profile = svc.create_profile("Detailed", proxy_id=proxy.id)
    details = svc.get_profile_details(profile.id)
    assert details.proxy_check is not None
    assert details.proxy_check.external_ip == "198.51.100.44"
    assert details.proxy_check.country_code == "DE"
    assert details.proxy_check.latency_ms == 123
    assert details.proxy_check.anonymity is Anonymity.ELITE
    assert details.profile.proxy_id == proxy.id


def test_get_profile_details_includes_configuration(ctx):
    svc, _ = ctx
    profile = svc.create_profile("CfgDetails")
    details = svc.get_profile_details(profile.id)
    assert details.configuration is not None
    assert details.configuration.id == svc.get_profile(profile.id).configuration_id

    svc.remove_configuration(profile.id)
    assert svc.get_profile_details(profile.id).configuration is None


def test_list_profiles_details_mixed(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db)
    with_proxy = svc.create_profile("Joined", proxy_id=proxy.id)
    without_proxy = svc.create_profile("Plain")

    details_list = {d.profile.id: d for d in svc.list_profiles_details()}
    assert details_list[with_proxy.id].proxy_check is not None
    assert details_list[with_proxy.id].proxy_check.proxy.id == proxy.id
    assert details_list[without_proxy.id].proxy_check is None
    assert details_list[without_proxy.id].configuration is None  # listings skip config


def test_start_without_configuration_generates_one(ctx):
    svc, _ = ctx
    profile = svc.create_profile("Detached")
    svc.remove_configuration(profile.id)
    assert svc.get_profile(profile.id).configuration_id is None
    started = svc.start_profile(profile.id)
    assert started.configuration_id is not None  # repaired automatically at launch
    svc.stop_profile(profile.id)


def test_start_blocks_dead_proxy(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db, host="10.0.0.9", status=ProxyStatus.DEAD)
    profile = svc.create_profile("DeadProxy", proxy_id=proxy.id)
    with pytest.raises(ProxyNotUsableError):
        svc.start_profile(profile.id)


def test_start_profile_with_proxy_forwards_proxy_to_browser(ctx, tmp_path):
    svc, db = ctx
    proxy = _add_proxy(svc, db, host="203.0.113.5", port=3128, status=ProxyStatus.WORKING)
    profile = svc.create_profile("Proxied", proxy_id=proxy.id)
    started = svc.start_profile(profile.id)
    try:
        assert started.pid and started.pid > 0
        args = tmp_path.joinpath("fake_chromium.args").read_text(encoding="utf-8")
        assert "--proxy-server=http://203.0.113.5:3128" in args
        assert svc.get_profile(profile.id).status.value == "RUNNING"
    finally:
        svc.stop_profile(profile.id)


def test_start_profile_without_proxy_has_no_proxy_flag(ctx, tmp_path):
    svc, _ = ctx
    profile = svc.create_profile("Direct")
    svc.start_profile(profile.id)
    try:
        args = tmp_path.joinpath("fake_chromium.args").read_text(encoding="utf-8")
        assert "--proxy-server" not in args
    finally:
        svc.stop_profile(profile.id)


def test_duplicate_profile_copies_proxy(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db)
    original = svc.create_profile("Original", proxy_id=proxy.id)
    copy = svc.duplicate_profile(original.id)
    assert copy.proxy_id == proxy.id
    assert copy.id != original.id


def test_duplicate_profile_copies_configuration(ctx):
    svc, _ = ctx
    original = svc.create_profile("CfgOrig")
    copy = svc.duplicate_profile(original.id)
    # a dedicated fingerprint is cloned: same values, independent record
    assert copy.configuration_id != original.configuration_id
    a = svc._configurations.get(original.configuration_id)
    b = svc._configurations.get(copy.configuration_id)
    assert (a.user_agent, a.platform, a.timezone, a.screen_width) == (
        b.user_agent, b.platform, b.timezone, b.screen_width)