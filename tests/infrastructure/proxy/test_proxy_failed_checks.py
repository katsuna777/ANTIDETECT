"""Failed-check handling: batch-level server-style checks against a fake checker."""

from __future__ import annotations

from tests.support.fakes import StubChecker

from antidetect.application.proxy_service import ProxyService
from antidetect.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from antidetect.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from antidetect.infrastructure.proxy.checker import CheckOutcome
from antidetect.infrastructure.proxy.collector import ProxyCollector


def _build_service(db, checker, **kw) -> ProxyService:
    return ProxyService(
        proxies=SqliteProxyRepository(db),
        checks=SqliteProxyCheckRepository(db),
        collector=ProxyCollector([]),
        checker=checker,
        dead_policy=kw.pop("dead_policy", "disable"),
        max_failures=kw.pop("max_failures", 3),
        **kw,
    )


def _seed(db, hosts) -> list:
    repo = SqliteProxyRepository(db)
    repo.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host=host, port=8080) for host in hosts]
    )
    return repo.list()


def test_check_all_survives_mixed_success_and_failure(db) -> None:
    repo = SqliteProxyRepository(db)
    proxies = _seed(db, ["1.1.1.1", "2.2.2.2", "3.3.3.3"])
    outcomes = {
        proxies[0].id: CheckOutcome(proxy=proxies[0], ok=True, latency_ms=10),
        proxies[1].id: CheckOutcome(proxy=proxies[1], ok=False, error="timeout"),
        proxies[2].id: CheckOutcome(proxy=proxies[2], ok=False, error="refused"),
    }
    service = _build_service(db, StubChecker(by_id={k: v for k, v in outcomes.items()}))
    summary = service.check_all(workers=3, timeout=2)
    assert summary.checked == 3
    assert summary.working == 1
    assert summary.failed == 2
    assert repo.get(proxies[0].id).status is ProxyStatus.WORKING  # type: ignore[union-attr]
    assert repo.get(proxies[2].id) is not None  # one failure does not delete


def test_error_recorded_with_check_per_proxy(db) -> None:
    proxies = _seed(db, ["1.1.1.1", "2.2.2.2"])
    service = _build_service(
        db,
        StubChecker(
            by_id={
                proxies[0].id: CheckOutcome(proxy=proxies[0], ok=True),
                proxies[1].id: CheckOutcome(proxy=proxies[1], ok=False, error="conn reset"),
            }
        ),
    )
    service.check_all(workers=2)
    checks = SqliteProxyCheckRepository(db)
    ok_check = checks.latest_for(proxies[0].id)
    bad_check = checks.latest_for(proxies[1].id)
    assert ok_check is not None and ok_check.status.value == "WORKING"
    assert bad_check is not None
    assert bad_check.status.value == "ERROR"
    assert bad_check.error == "conn reset"


def test_empty_batch_is_noop(db) -> None:
    service = _build_service(db, StubChecker())
    summary = service.check_all()
    assert summary.checked == 0
    assert summary.working == 0


def test_check_all_forwards_progress_to_gui(db) -> None:
    _seed(db, ["1.1.1.1", "2.2.2.2", "3.3.3.3"])
    counts: list[tuple[int, int]] = []

    def on_progress(done: int, total: int) -> None:
        counts.append((done, total))

    service = _build_service(db, StubChecker())
    service.check_all(workers=3, on_progress=on_progress)
    assert counts == [(3, 3)]

    counts.clear()
    summary = service.refresh(
        collect=False, force=True, on_progress=on_progress
    )
    assert summary.checked == 3
    assert counts == [(3, 3)]