"""A free-list refresh writes only the proxies that passed a check.

Collected proxies are candidates held in memory; whatever fails, or is never reached because the
run was stopped, must not leave a row behind.
"""

from __future__ import annotations

import threading

import pytest

from antidetect.application.proxy_service import ProxyService
from antidetect.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.database.repositories.proxy_check_repository import SqliteProxyCheckRepository
from antidetect.infrastructure.database.repositories.proxy_repository import SqliteProxyRepository
from antidetect.infrastructure.proxy.checker import CheckOutcome
from antidetect.infrastructure.proxy.collector import ProxyCollector
from tests.support.fakes import TextProxySource


class HostChecker:
    """Passes the proxies whose host is in ``ok``; can raise a stop request after N checks."""

    def __init__(self, ok=(), stop_after: int | None = None, stream: bool = True) -> None:
        self.ok = set(ok)
        self.stop_after = stop_after
        self.stream = stream
        self.seen: list[str] = []

    def check_all(self, proxies, workers=None, timeout=None, on_progress=None, on_proxy=None, stop_event=None):
        outcomes = []
        for proxy in proxies:
            if stop_event is not None and stop_event.is_set():
                break
            self.seen.append(proxy.host)
            outcome = CheckOutcome(
                proxy=proxy, ok=proxy.host in self.ok, latency_ms=80,
                external_ip="198.51.100.1", country="Germany", country_code="DE",
            )
            outcomes.append(outcome)
            if self.stream and on_proxy is not None:
                on_proxy(outcome)
            if on_progress is not None:
                on_progress(len(outcomes), len(proxies))
            if self.stop_after is not None and len(outcomes) >= self.stop_after and stop_event is not None:
                stop_event.set()
        return outcomes


def _service(db, checker, lines=(), max_failures=3) -> ProxyService:
    return ProxyService(
        proxies=SqliteProxyRepository(db),
        checks=SqliteProxyCheckRepository(db),
        collector=ProxyCollector([TextProxySource(name="free", lines=list(lines))]),
        checker=checker,
        dead_policy="disable",
        max_failures=max_failures,
    )


def _hosts(db) -> set[str]:
    return {p.host for p in SqliteProxyRepository(db).list()}


def _check_rows(db) -> int:
    return db.execute("SELECT COUNT(*) AS c FROM proxy_checks").fetchone()["c"]


def test_only_candidates_that_passed_reach_the_table(db):
    lines = [f"10.0.0.{i}:8080" for i in range(1, 6)]
    service = _service(db, HostChecker(ok={"10.0.0.2", "10.0.0.4"}), lines)
    summary = service.refresh(force=True, purge_failed=True)
    assert _hosts(db) == {"10.0.0.2", "10.0.0.4"}
    assert (summary.collected, summary.created, summary.checked) == (5, 2, 5)
    assert (summary.working, summary.failed) == (2, 3)
    for row in service.list_proxies():
        assert row.proxy.status is ProxyStatus.WORKING and row.country_code == "DE" and row.latency_ms == 80
        assert row.proxy.source == "free"


def test_failed_candidates_leave_no_rows_and_no_check_history(db):
    service = _service(db, HostChecker(ok=set()), [f"10.0.1.{i}:3128" for i in range(1, 30)])
    service.refresh(force=True, purge_failed=False)  # even without the GUI's purge
    assert _hosts(db) == set() and _check_rows(db) == 0


def test_a_stopped_run_keeps_what_was_checked_and_nothing_else(db):
    lines = [f"10.0.2.{i}:8080" for i in range(1, 11)]
    checker = HostChecker(ok={f"10.0.2.{i}" for i in range(1, 11)}, stop_after=4)
    service = _service(db, checker, lines)
    stop = threading.Event()
    summary = service.refresh(force=True, purge_failed=True, stop_event=stop)
    assert _hosts(db) == {f"10.0.2.{i}" for i in range(1, 5)}  # the 6 never checked are not in the table
    assert summary.checked == 4 and summary.created == 4 and summary.collected == 10


def test_results_are_written_while_the_run_is_still_going(db):
    seen_during: list[int] = []
    checker = HostChecker(ok={f"10.0.3.{i}" for i in range(1, 61)})
    original = checker.check_all

    def spy(proxies, **kwargs):
        on_proxy = kwargs["on_proxy"]

        def wrapped(outcome):
            on_proxy(outcome)
            seen_during.append(len(_hosts(db)))

        kwargs["on_proxy"] = wrapped
        return original(proxies, **kwargs)

    checker.check_all = spy
    _service(db, checker, [f"10.0.3.{i}:8080" for i in range(1, 61)]).refresh(force=True)
    assert max(seen_during) > 0 and seen_during[-1] >= 50  # filled in batches, not all at the very end
    assert len(_hosts(db)) == 60


def test_a_checker_that_does_not_stream_still_gets_its_passes_stored(db):
    checker = HostChecker(ok={"10.0.4.1"}, stream=False)
    _service(db, checker, ["10.0.4.1:80", "10.0.4.2:80"]).refresh(force=True)
    assert _hosts(db) == {"10.0.4.1"}


def test_known_proxies_are_rechecked_and_failed_free_ones_purged_but_manual_kept(db):
    repo = SqliteProxyRepository(db)
    repo.upsert_many([
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="10.0.5.1", port=80, source="free"),
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="10.0.5.2", port=80, source="free"),
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="10.0.5.3", port=80, source="manual"),
    ])
    service = _service(db, HostChecker(ok={"10.0.5.1"}))
    summary = service.refresh(collect=False, force=True, purge_failed=True)
    assert _hosts(db) == {"10.0.5.1", "10.0.5.3"}
    assert summary.checked == 3 and summary.removed == 1 and summary.created == 0


def test_a_candidate_already_stored_is_not_collected_again(db):
    repo = SqliteProxyRepository(db)
    repo.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host="10.0.6.1", port=80, source="manual")])
    checker = HostChecker(ok={"10.0.6.1", "10.0.6.2"})
    summary = _service(db, checker, ["10.0.6.1:80", "10.0.6.2:80"]).refresh(force=True)
    assert summary.collected == 1 and checker.seen.count("10.0.6.1") == 1  # checked once, as a stored row
    assert _hosts(db) == {"10.0.6.1", "10.0.6.2"}


def test_reset_forgets_the_old_pool_and_keeps_only_what_the_new_run_verified(db):
    repo = SqliteProxyRepository(db)
    repo.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host="10.0.7.9", port=80, source="free")])
    _service(db, HostChecker(ok={"10.0.7.1"}), ["10.0.7.1:80", "10.0.7.2:80"]).refresh(reset=True, force=True)
    assert _hosts(db) == {"10.0.7.1"}


def test_check_all_can_be_limited_to_some_ids(db):
    repo = SqliteProxyRepository(db)
    repo.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host=f"10.0.8.{i}", port=80, source="manual") for i in range(1, 5)])
    ids = {p.host: p.id for p in repo.list()}
    checker = HostChecker(ok={"10.0.8.2", "10.0.8.3"})
    summary = _service(db, checker).check_all(ids=[ids["10.0.8.2"], ids["10.0.8.3"], 9999])
    assert sorted(checker.seen) == ["10.0.8.2", "10.0.8.3"] and summary.checked == 2 and summary.working == 2


def test_import_reports_ids_in_input_order_and_counts_known_ones(db):
    service = _service(db, HostChecker())
    first = service.import_text("1.1.1.1:80\n2.2.2.2:80")
    assert (first.added, first.existing) == (2, 0) and len(first.ids) == 2
    again = service.import_text("2.2.2.2:80\n3.3.3.3:80\n2.2.2.2:80")
    assert (again.added, again.existing) == (1, 2)
    hosts = {p.id: p.host for p in SqliteProxyRepository(db).list()}
    assert [hosts[i] for i in again.ids] == ["2.2.2.2", "3.3.3.3"]


@pytest.mark.parametrize("count", [0, 1])
def test_import_of_nothing_readable_adds_nothing(db, count):
    summary = _service(db, HostChecker()).import_text("garbage\n" * count)
    assert summary.added == 0 and summary.ids == [] and len(summary.invalid) == count
