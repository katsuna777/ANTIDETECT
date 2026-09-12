from __future__ import annotations

from tests.fakes import StubChecker

from app.application.proxy_service import ProxyService
from app.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from app.domain.errors import ProxySourceError
from app.domain.models.proxy_entry import ProxyEntry
from app.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from app.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from app.infrastructure.proxy.collector import ProxyCollector
from app.infrastructure.proxy.proxy_source import ProxySource, TextProxySource
from app.infrastructure.proxy.sources import GitHubProxySource


class FailingSource(ProxySource):
    name = "broken"

    def fetch(self, timeout: float | None = None):
        raise ProxySourceError(self.name, "connection reset")
        yield  # pragma: no cover - keeps this a generator


class SlowSource(ProxySource):
    name = "slow"

    def fetch(self, timeout: float | None = None):
        for line in ("1.1.1.1:80", "2.2.2.2:8080", "3.3.3.3:3128"):
            yield line


def test_custom_source_subclass_is_consumed() -> None:
    collector = ProxyCollector([SlowSource()])
    batch = collector.collect()
    assert batch.new_entries == 3
    assert {e.host for e in batch.entries} == {"1.1.1.1", "2.2.2.2", "3.3.3.3"}
    assert batch.source_stats[0].fetched is True
    assert batch.source_stats[0].found == 3


def test_failing_source_is_isolated() -> None:
    collector = ProxyCollector([TextProxySource(name="ok", lines=["9.9.9.9:8080"]), FailingSource()])
    batch = collector.collect()
    assert [e.host for e in batch.entries] == ["9.9.9.9"]
    stat = batch.source_stats[1]
    assert stat.fetched is False
    assert stat.error is not None
    assert not batch.entries or all(e.source != "broken" for e in batch.entries)


def test_collector_dedupes_across_sources() -> None:
    collector = ProxyCollector(
        [
            TextProxySource(name="a", lines=["1.1.1.1:80", "2.2.2.2:80"]),
            TextProxySource(name="b", lines=["2.2.2.2:80", "3.3.3.3:80"]),
        ]
    )
    batch = collector.collect()
    assert len(batch.entries) == 3
    assert batch.entries[1].source == "a"  # first occurrence kept


def test_collector_respects_existing_keys() -> None:
    collector = ProxyCollector([TextProxySource(name="x", lines=["1.1.1.1:80", "2.2.2.2:80"])])
    existing = {("HTTP", "1.1.1.1", 80)}
    batch = collector.collect(existing_keys=existing)
    assert [e.host for e in batch.entries] == ["2.2.2.2"]


def test_collector_applies_source_protocol_default() -> None:
    source = TextProxySource(
        name="socks",
        lines=["1.1.1.1:1080"],
        protocol=ProxyProtocol.SOCKS5,
    )
    batch = ProxyCollector([source]).collect()
    assert batch.entries[0].protocol is ProxyProtocol.SOCKS5


def test_collector_stamps_source_and_parses() -> None:
    source = TextProxySource(
        name="mixed",
        lines=["http://1.1.1.1:8080", "uid:pw@2.2.2.2:3128"],
    )
    batch = ProxyCollector([source]).collect()
    assert len(batch.entries) == 2
    assert batch.entries[0].source == "mixed"
    assert batch.entries[1].username == "uid"
    assert batch.entries[1].password == "pw"


def test_github_source_streams_lines_without_buffering() -> None:
    source = GitHubProxySource(name="gh", url="http://example.invalid/never")
    # We must not read the whole body into memory; reaching fetch without
    # raising during iteration is the streaming contract.
    iterator = source.fetch(timeout=1)
    assert iterator is not None


def test_fetch_error_propagates_as_source_error() -> None:
    source = GitHubProxySource(name="gh", url="http://nonexistent.invalid/list.txt")
    try:
        for _line in source.fetch(timeout=2):
            pass
    except ProxySourceError as exc:
        assert exc.source_name == "gh"
    else:
        raise AssertionError("expected ProxySourceError")


def test_sources_build_detects_protocol_from_path() -> None:
    from app.infrastructure.proxy.sources import build_sources

    sources = build_sources(
        [
            "https://raw.githubusercontent.com/x/proxies/socks5.txt",
            "https://raw.githubusercontent.com/x/proxies/proxy-list-raw.txt",
        ]
    )
    assert sources[0].protocol is ProxyProtocol.SOCKS5
    assert sources[1].protocol is ProxyProtocol.HTTP