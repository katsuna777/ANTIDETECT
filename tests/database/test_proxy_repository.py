from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from antidetect.domain.enums.proxy_status import Anonymity, ProxyProtocol, ProxyStatus
from antidetect.domain.models.proxy_check import ProxyCheck
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from antidetect.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def proxy_repo(db):
    return SqliteProxyRepository(db)


@pytest.fixture()
def check_repo(db):
    return SqliteProxyCheckRepository(db)


def _entry(protocol=ProxyProtocol.HTTP, host="1.2.3.4", port=8080):
    return ProxyEntry(protocol=protocol, host=host, port=port, source="test")


def test_upsert_creates_rows_and_counts_only_new(proxy_repo: SqliteProxyRepository) -> None:
    created = proxy_repo.upsert_many(
        [_entry(host="1.1.1.1"), _entry(host="2.2.2.2"), _entry(host="3.3.3.3")]
    )
    assert created == 3
    again = proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="4.4.4.4")])
    assert again == 1
    assert len(proxy_repo.list()) == 4


def test_unique_constraint_on_protocol_host_port(db) -> None:
    repo = SqliteProxyRepository(db)
    repo.upsert_many([_entry(), _entry()])
    assert len(repo.list()) == 1


def test_keys_returns_existing_endpoints(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2")])
    keys = proxy_repo.keys()
    assert ("HTTP", "1.1.1.1", 8080) in keys
    assert ("HTTP", "2.2.2.2", 8080) in keys


def test_get_roundtrip(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry(host="9.9.9.9", port=3128, protocol=ProxyProtocol.SOCKS5)])
    proxy = proxy_repo.list()[0]
    fetched = proxy_repo.get(proxy.id)
    assert fetched is not None
    assert fetched.protocol is ProxyProtocol.SOCKS5
    assert fetched.host == "9.9.9.9"
    assert fetched.port == 3128
    assert fetched.status is ProxyStatus.UNKNOWN


def test_get_missing_returns_none(proxy_repo: SqliteProxyRepository) -> None:
    assert proxy_repo.get(4242) is None


def test_apply_outcomes_updates_status_and_failures(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry()])
    proxy = proxy_repo.list()[0]
    proxy_repo.apply_outcomes([(proxy.id, ProxyStatus.WORKING, 0, _now())])
    updated = proxy_repo.get(proxy.id)
    assert updated is not None
    assert updated.status is ProxyStatus.WORKING
    assert updated.consecutive_failures == 0
    assert updated.last_checked_at is not None


def test_list_for_check_respects_staleness(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2")])
    first, second = proxy_repo.list()
    old = _now() - timedelta(hours=5)
    proxy_repo.apply_outcomes([(first.id, ProxyStatus.WORKING, 0, old)])
    proxy_repo.apply_outcomes([(second.id, ProxyStatus.WORKING, 0, _now())])
    stale_before = _now() - timedelta(minutes=60)
    candidates = proxy_repo.list_for_check(stale_before=stale_before)
    ids = {p.id for p in candidates}
    assert first.id in ids
    assert second.id not in ids


def test_list_for_check_includes_unknown_and_dead_always(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2")])
    first, second = proxy_repo.list()
    proxy_repo.apply_outcomes([(first.id, ProxyStatus.WORKING, 0, _now())])
    proxy_repo.apply_outcomes([(second.id, ProxyStatus.DEAD, 3, _now())])
    stale_before = _now() - timedelta(seconds=1)
    candidates = proxy_repo.list_for_check(stale_before=stale_before)
    assert {p.id for p in candidates} == {second.id}  # dead re-checked, working is fresh


def test_delete_removes_proxy(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry()])
    proxy = proxy_repo.list()[0]
    assert proxy_repo.delete(proxy.id) is True
    assert proxy_repo.get(proxy.id) is None
    assert proxy_repo.delete(proxy.id) is False


def test_deleting_all_proxies_restarts_ids(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many(
        [_entry(host="1.1.1.1"), _entry(host="2.2.2.2"), _entry(host="3.3.3.3")]
    )
    for proxy in proxy_repo.list():
        proxy_repo.delete(proxy.id)
    proxy_repo.upsert_many([_entry(host="9.9.9.9")])
    assert proxy_repo.list()[0].id == 1


def test_deleting_dead_restarts_ids(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2")])
    first, _ = proxy_repo.list()
    proxy_repo.apply_outcomes([(first.id, ProxyStatus.DEAD, 3, _now())])
    assert proxy_repo.delete_dead() == 1
    proxy_repo.delete(proxy_repo.list()[0].id)
    proxy_repo.upsert_many([_entry(host="9.9.9.9")])
    assert proxy_repo.list()[0].id == 1


def test_delete_many_resets_sequence(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2")])
    ids = [proxy.id for proxy in proxy_repo.list()]
    assert proxy_repo.delete_many(ids) == 2
    assert proxy_repo.list() == []
    proxy_repo.upsert_many([_entry(host="9.9.9.9")])
    assert proxy_repo.list()[0].id == 1


def test_delete_many_empty_or_unknown_is_noop(proxy_repo: SqliteProxyRepository) -> None:
    assert proxy_repo.delete_many([]) == 0
    assert proxy_repo.delete_many([4242]) == 0


def test_delete_all_empties_pool_and_resets_sequence(
    proxy_repo: SqliteProxyRepository,
) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2")])
    assert proxy_repo.delete_all() == 2
    assert proxy_repo.list() == []
    proxy_repo.upsert_many([_entry(host="9.9.9.9")])
    assert proxy_repo.list()[0].id == 1


def test_delete_dead_only_removes_dead(
    proxy_repo: SqliteProxyRepository, check_repo: SqliteProxyCheckRepository
) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2"), _entry(host="3.3.3.3")])
    proxies = proxy_repo.list()
    proxy_repo.apply_outcomes([(proxies[0].id, ProxyStatus.DEAD, 3, _now())])
    proxy_repo.apply_outcomes([(proxies[1].id, ProxyStatus.WORKING, 0, _now())])
    assert proxy_repo.delete_dead() == 1
    remaining = {p.host for p in proxy_repo.list()}
    assert remaining == {"2.2.2.2", "3.3.3.3"}


def test_deleting_proxy_cascades_to_checks(db) -> None:
    proxy_repo = SqliteProxyRepository(db)
    check_repo = SqliteProxyCheckRepository(db)
    proxy_repo.upsert_many([_entry()])
    proxy = proxy_repo.list()[0]

    check_repo.insert_many(
        [
            ProxyCheck(
                id=0, proxy_id=proxy.id, checked_at=_now(),
                status=ProxyStatus.ERROR, latency_ms=None, error="boom",
            )
        ]
    )
    assert check_repo.latest_for(proxy.id) is not None
    proxy_repo.delete(proxy.id)
    assert check_repo.latest_for(proxy.id) is None


def test_list_with_latest_check_joins_rows(
    proxy_repo: SqliteProxyRepository, check_repo: SqliteProxyCheckRepository
) -> None:
    proxy_repo.upsert_many([_entry()])
    proxy = proxy_repo.list()[0]
    check_repo.insert_many(
        [
            ProxyCheck(
                id=0, proxy_id=proxy.id, checked_at=_now(), status=ProxyStatus.WORKING,
                latency_ms=47, external_ip="5.5.5.5", country="Germany",
                country_code="DE", anonymity=Anonymity.ANONYMOUS,
            )
        ]
    )
    rows = proxy_repo.list_with_latest_check()
    assert len(rows) == 1
    row = rows[0]
    assert row.latency_ms == 47
    assert row.country_code == "DE"
    assert row.anonymity is not None
    assert row.anonymity.value == "anonymous"


def test_upsert_rejects_unsupported_protocol(db) -> None:
    repo = SqliteProxyRepository(db)
    with pytest.raises(AttributeError):
        repo.upsert_many(
            [ProxyEntry(protocol="SOCKS4", host="1.2.3.4", port=1080)]  # type: ignore[arg-type]
        )

def test_ids_for_keys_finds_only_the_endpoints_that_exist(proxy_repo: SqliteProxyRepository) -> None:
    proxy_repo.upsert_many([_entry(host="1.1.1.1"), _entry(host="2.2.2.2", protocol=ProxyProtocol.SOCKS5)])
    stored = {(p.protocol.value, p.host, p.port): p.id for p in proxy_repo.list()}
    wanted = [("HTTP", "1.1.1.1", 8080), ("SOCKS5", "2.2.2.2", 8080), ("HTTP", "2.2.2.2", 8080), ("HTTP", "9.9.9.9", 1)]
    assert proxy_repo.ids_for_keys(wanted) == {k: stored[k] for k in wanted[:2]}
    assert proxy_repo.ids_for_keys([]) == {}
