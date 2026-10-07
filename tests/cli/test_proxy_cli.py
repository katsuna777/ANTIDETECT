from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone

import pytest

from tests.support.fakes import StubChecker, TextProxySource, make_proxy

from antidetect.application.proxy_service import ProxyService
from antidetect.cli.main import build_parser, main
from antidetect.cli.commands import proxy_commands
from antidetect.domain.enums.proxy_status import Anonymity, ProxyProtocol, ProxyStatus
from antidetect.domain.models.proxy_check import ProxyCheck
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from antidetect.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from antidetect.infrastructure.proxy.collector import ProxyCollector


def _build_service(db, checker, dead_policy="disable") -> ProxyService:
    return ProxyService(
        proxies=SqliteProxyRepository(db),
        checks=SqliteProxyCheckRepository(db),
        collector=ProxyCollector([]),
        checker=checker,
        dead_policy=dead_policy,
        max_failures=3,
    )


def _seed(db, hosts):
    repo = SqliteProxyRepository(db)
    repo.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host=host, port=8080) for host in hosts]
    )
    return repo.list()


def test_proxy_group_has_expected_commands() -> None:
    parser = build_parser()
    proxy = parser._subparsers._group_actions[0].choices["proxy"]  # type: ignore[union-attr]
    names = set()
    for action in proxy._actions:
        if hasattr(action, "choices") and action.choices:
            names.update(action.choices)
    assert {"list", "refresh", "check", "check-all", "remove-dead"} <= names


def _args(**kw) -> Namespace:
    defaults = dict(
        status=None, sort="latency", reverse=False, limit=None,
        workers=None, timeout=None, max_failures=None, stale_minutes=None,
        force=False, no_collect=False, id=0,
    )
    defaults.update(kw)
    return Namespace(**defaults)


def test_cmd_list_renders_table(db, capsys) -> None:
    proxies = _seed(db, ["1.1.1.1", "2.2.2.2"])
    service = _build_service(db, StubChecker())
    check_repo = SqliteProxyCheckRepository(db)
    now = datetime.now(timezone.utc)
    check_repo.insert_many(
        [
            ProxyCheck(
                id=0, proxy_id=proxies[0].id, checked_at=now,
                status=ProxyStatus.WORKING, latency_ms=47,
                external_ip="77.88.8.8", country="Germany", country_code="DE",
                anonymity=Anonymity.ELITE, error=None,
            )
        ]
    )
    SqliteProxyRepository(db).apply_outcomes(
        [(proxies[0].id, ProxyStatus.WORKING, 0, now)]
    )
    proxy_commands.cmd_list(service, _args())
    captured = capsys.readouterr()
    assert "ID" in captured.out
    assert "1.1.1.1" in captured.out
    assert "DE" in captured.out
    assert "47ms" in captured.out


def test_default_list_orders_working_by_latency(db) -> None:
    proxies = _seed(db, ["a.com", "b.com", "c.com"])
    repo = SqliteProxyRepository(db)
    now = datetime.now(timezone.utc)
    repo.apply_outcomes(
        [
            (proxies[0].id, ProxyStatus.WORKING, 0, now),
            (proxies[1].id, ProxyStatus.WORKING, 0, now),
            (proxies[2].id, ProxyStatus.UNKNOWN, 0, now),
        ]
    )
    check_repo = SqliteProxyCheckRepository(db)
    check_repo.insert_many(
        [
            ProxyCheck(id=0, proxy_id=proxies[0].id, checked_at=now,
                       status=ProxyStatus.WORKING, latency_ms=200,
                       anonymity=None),
            ProxyCheck(id=0, proxy_id=proxies[1].id, checked_at=now,
                       status=ProxyStatus.WORKING, latency_ms=30,
                       anonymity=None),
        ]
    )
    service = _build_service(db, StubChecker())
    rows = service.list_proxies()
    working = [r for r in rows if r.proxy.status is ProxyStatus.WORKING]
    rest = [r for r in rows if r.proxy.status is not ProxyStatus.WORKING]
    assert [r.latency_ms for r in working] == [30, 200]
    assert rows[:2] == working
    assert rows[2:] == rest


def test_cmd_check_prints_working_line(db, capsys) -> None:
    proxies = _seed(db, ["1.2.3.4"])
    service = _build_service(db, StubChecker())
    proxy_commands.cmd_check(service, _args(id=proxies[0].id))
    out = capsys.readouterr().out
    assert "WORKING" in out
    assert "1.2.3.4:8080" in out


def test_cmd_remove_dead_reports_count(db, capsys) -> None:
    _seed(db, ["1.1.1.1"])
    proxy_commands.cmd_remove_dead(_build_service(db, StubChecker()), _args())
    assert "Removed 0" in capsys.readouterr().out


def test_cmd_refresh_collects_checks_and_reports(db, capsys) -> None:
    service = ProxyService(
        proxies=SqliteProxyRepository(db),
        checks=SqliteProxyCheckRepository(db),
        collector=ProxyCollector(
            [TextProxySource(name="local", lines=["7.7.7.7:8080", "8.8.8.8:3128"])]
        ),
        checker=StubChecker(),
        dead_policy="disable",
        max_failures=3,
    )
    proxy_commands.cmd_refresh(service, _args())
    out = capsys.readouterr().out
    assert "Collected 2 new candidate(-ies), 2 inserted." in out
    assert "working" in out


def test_cli_main_rejects_unknown_proxy_command() -> None:
    with pytest.raises(SystemExit):
        main(["proxy", "frobnicate"])


def test_make_proxy_helper_roundtrip() -> None:
    p = make_proxy(3, host="9.9.9.9")
    assert p.id == 3
    assert p.host_port == "9.9.9.9:8080"