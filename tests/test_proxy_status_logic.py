from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.fakes import StubChecker

from app.application.proxy_service import ProxyService
from app.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from app.domain.models.proxy import Proxy
from app.domain.models.proxy_entry import ProxyBatch, ProxyEntry
from app.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from app.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from app.infrastructure.proxy.checker import CheckOutcome
from app.infrastructure.proxy.collector import ProxyCollector


def _proxy(pid=1, host="1.1.1.1", status=ProxyStatus.UNKNOWN, failures=0) -> Proxy:
    return Proxy(
        id=pid,
        protocol=ProxyProtocol.HTTP,
        host=host,
        port=8080,
        status=status,
        consecutive_failures=failures,
    )


def _build_service(db, checker, dead_policy="disable", max_failures=3) -> ProxyService:
    return ProxyService(
        proxies=SqliteProxyRepository(db),
        checks=SqliteProxyCheckRepository(db),
        collector=ProxyCollector([]),
        checker=checker,
        dead_policy=dead_policy,
        max_failures=max_failures,
    )


def _seed(db, entries) -> list[Proxy]:
    repo = SqliteProxyRepository(db)
    repo.upsert_many(entries)
    return repo.list()


def test_success_moves_unknown_to_working(db) -> None:
    service = _build_service(db, StubChecker())
    proxies = _seed(
        db, [ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)]
    )
    outcome = CheckOutcome(proxy=proxies[0], ok=True, latency_ms=42)
    service.apply_outcomes([outcome])
    stored = service.get_proxy(proxies[0].id)
    assert stored.status is ProxyStatus.WORKING
    assert stored.consecutive_failures == 0
    assert stored.last_checked_at is not None
    check = SqliteProxyCheckRepository(db).latest_for(proxies[0].id)
    assert check is not None
    assert check.status.value == "WORKING"
    assert check.latency_ms == 42


def test_single_failure_does_not_kill_fresh_proxy(db) -> None:
    service = _build_service(db, StubChecker())
    proxies = _seed(
        db, [ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)]
    )
    outcome = CheckOutcome(proxy=proxies[0], ok=False, error="timeout")
    service.apply_outcomes([outcome])
    stored = service.get_proxy(proxies[0].id)
    assert stored.status is ProxyStatus.UNKNOWN
    assert stored.consecutive_failures == 1
    assert SqliteProxyRepository(db).get(proxies[0].id) is not None  # not deleted


def test_transient_failure_keeps_working_status(db) -> None:
    service = _build_service(db, StubChecker())
    proxies = _seed(
        db, [ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)]
    )
    SqliteProxyRepository(db).apply_outcomes(
        [(proxies[0].id, ProxyStatus.WORKING, 0, datetime.now(timezone.utc))]
    )
    proxy = service.get_proxy(proxies[0].id)
    service.apply_outcomes([CheckOutcome(proxy=proxy, ok=False, error="timeout")])
    stored = service.get_proxy(proxies[0].id)
    assert stored.status is ProxyStatus.WORKING
    assert stored.consecutive_failures == 1


def test_consecutive_failures_eventually_mark_dead(db) -> None:
    service = _build_service(db, StubChecker(), max_failures=3)
    proxies = _seed(
        db, [ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)]
    )
    proxy = service.get_proxy(proxies[0].id)
    for expected_failures in (1, 2, 3):
        service.apply_outcomes([CheckOutcome(proxy=proxy, ok=False, error="timeout")])
        proxy = service.get_proxy(proxies[0].id)
        assert proxy.consecutive_failures == expected_failures
    assert proxy.status is ProxyStatus.DEAD


def test_success_resets_failure_counter(db) -> None:
    service = _build_service(db, StubChecker(), max_failures=3)
    proxies = _seed(
        db, [ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)]
    )
    proxy = service.get_proxy(proxies[0].id)
    service.apply_outcomes([CheckOutcome(proxy=proxy, ok=False, error="1")])
    proxy = service.get_proxy(proxies[0].id)
    service.apply_outcomes([CheckOutcome(proxy=proxy, ok=False, error="2")])
    proxy = service.get_proxy(proxies[0].id)
    service.apply_outcomes([CheckOutcome(proxy=proxy, ok=True)])
    stored = service.get_proxy(proxies[0].id)
    assert stored.status is ProxyStatus.WORKING
    assert stored.consecutive_failures == 0


def test_delete_policy_removes_dead_on_refresh(db) -> None:
    service = _build_service(db, StubChecker(), dead_policy="delete", max_failures=2)
    proxies = _seed(
        db, [ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)]
    )
    proxy = service.get_proxy(proxies[0].id)
    service.apply_outcomes([CheckOutcome(proxy=proxy, ok=False, error="1")])
    proxy = service.get_proxy(proxies[0].id)
    service.apply_outcomes([CheckOutcome(proxy=proxy, ok=False, error="2")])
    assert service._proxies.get(proxies[0].id) is not None  # still DEAD row
    removed = service._apply_dead_policy()
    assert removed == 1
    assert service._proxies.get(proxies[0].id) is None


def test_disable_policy_keeps_dead_rows(db) -> None:
    service = _build_service(db, StubChecker(), dead_policy="disable", max_failures=1)
    proxies = _seed(
        db, [ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080)]
    )
    proxy = service.get_proxy(proxies[0].id)
    service.apply_outcomes([CheckOutcome(proxy=proxy, ok=False, error="x")])
    assert service._proxies.get(proxies[0].id) is not None
    assert service._apply_dead_policy() == 0


def test_check_all_purge_failed_removes_failed_proxies(db) -> None:
    service = _build_service(db, StubChecker())
    proxies = _seed(
        db,
        [
            ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080),
            ProxyEntry(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=8080),
            ProxyEntry(protocol=ProxyProtocol.HTTP, host="3.3.3.3", port=8080),
        ],
    )
    outcomes = {
        proxies[0].id: CheckOutcome(proxy=proxies[0], ok=True, latency_ms=5),
        proxies[1].id: CheckOutcome(proxy=proxies[1], ok=False, error="timeout"),
        proxies[2].id: CheckOutcome(proxy=proxies[2], ok=False, error="refused"),
    }
    service._checker = StubChecker(by_id=outcomes)  # type: ignore[attr-defined]

    summary = service.check_all(purge_failed=True)

    remaining = {row.proxy.host for row in service.list_proxies()}
    assert remaining == {"1.1.1.1"}
    assert summary.working == 1
    assert summary.failed == 2
    assert summary.removed == 2


def test_check_all_without_purge_keeps_failed_proxies(db) -> None:
    service = _build_service(db, StubChecker())
    proxies = _seed(
        db,
        [
            ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080),
            ProxyEntry(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=8080),
        ],
    )
    outcomes = {
        proxies[0].id: CheckOutcome(proxy=proxies[0], ok=True, latency_ms=5),
        proxies[1].id: CheckOutcome(proxy=proxies[1], ok=False, error="timeout"),
    }
    service._checker = StubChecker(by_id=outcomes)  # type: ignore[attr-defined]

    summary = service.check_all(purge_failed=False)

    hosts = {row.proxy.host for row in service.list_proxies()}
    assert hosts == {"1.1.1.1", "2.2.2.2"}
    assert summary.removed == 0


def test_refresh_reset_forgets_old_pool_and_builds_fresh(db) -> None:
    class FakeCollector:
        def __init__(self, entries):
            self._entries = entries

        def collect(self, existing_keys=None, default_protocols=None, timeout=None):
            return ProxyBatch(entries=list(self._entries), source_stats=[])

    service = _build_service(db, StubChecker())
    _seed(
        db,
        [
            ProxyEntry(protocol=ProxyProtocol.HTTP, host="1.1.1.1", port=8080),
            ProxyEntry(protocol=ProxyProtocol.HTTP, host="2.2.2.2", port=8080),
        ],
    )
    fresh = [
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="9.9.9.9", port=8080),
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="8.8.8.8", port=8080),
    ]
    service._collector = FakeCollector(fresh)  # type: ignore[attr-defined]

    summary = service.refresh(reset=True, collect=True)

    hosts = {row.proxy.host for row in service.list_proxies()}
    assert hosts == {"9.9.9.9", "8.8.8.8"}
    assert all(
        row.proxy.status is ProxyStatus.WORKING for row in service.list_proxies()
    )
    assert summary.created == 2


def test_unknown_dead_policy_rejected(db) -> None:
    with pytest.raises(ValueError):
        _build_service(db, StubChecker(), dead_policy="nuke")