"""ProxyService integration with the log sink: check outcomes get logged."""

from __future__ import annotations

import pytest

from tests.fakes import RecordingLogSink, StubChecker

from app.application.proxy_service import ProxyService
from app.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from app.domain.models.proxy_entry import ProxyEntry
from app.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from app.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from app.infrastructure.proxy.checker import CheckOutcome
from app.infrastructure.proxy.collector import ProxyCollector


def _seed(db, host="7.7.7.7"):
    repo = SqliteProxyRepository(db)
    repo.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host=host, port=8080)])
    return repo.list()[0]


def _service(db, sink):
    return ProxyService(
        proxies=SqliteProxyRepository(db),
        checks=SqliteProxyCheckRepository(db),
        collector=ProxyCollector([]),
        checker=StubChecker(),
        log_sink=sink,
    )


def test_check_proxy_logs_working_outcome(db):
    sink = RecordingLogSink()
    service = _service(db, sink)
    proxy = _seed(db)

    service.check_proxy(proxy.id)

    proxy_entries = [
        (level, msg)
        for level, source, msg, _e in sink.entries
        if source == "proxy" and "7.7.7.7:8080" in msg
    ]
    assert any("WORKING" in msg for _level, msg in proxy_entries)


def test_check_all_logs_failed_outcomes(db):
    sink = RecordingLogSink()
    service = _service(db, sink)
    proxy = _seed(db)

    class FailingChecker(StubChecker):
        def check_one(self, proxy, timeout=None):
            return CheckOutcome(proxy=proxy, ok=False, error="connection refused")

        def check_all(self, proxies, workers=None, timeout=None, on_progress=None,
                      on_proxy=None, stop_event=None):
            results = [CheckOutcome(p, ok=False, error="connection refused") for p in proxies]
            return results

    service._checker = FailingChecker()
    summary = service.check_all(force=True)

    assert any(
        source == "proxy" and "failed" in msg.lower()
        for _level, source, msg, _e in sink.entries
    )
    assert any(
        source == "proxy" and "Proxy check finished" in msg
        for _level, source, msg, _e in sink.entries
    )
    assert summary.failed == 1