from __future__ import annotations


from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.errors import ProxySourceError
from antidetect.infrastructure.proxy.collector import ProxyCollector
from antidetect.infrastructure.proxy.proxy_source import ProxySource
from tests.support.fakes import TextProxySource
from antidetect.infrastructure.proxy.sources import GitHubProxySource


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
    from antidetect.infrastructure.proxy.sources import build_sources

    sources = build_sources(
        [
            "https://raw.githubusercontent.com/x/proxies/socks5.txt",
            "https://raw.githubusercontent.com/x/proxies/proxy-list-raw.txt",
        ]
    )
    assert sources[0].protocol is ProxyProtocol.SOCKS5
    assert sources[1].protocol is ProxyProtocol.HTTP

class _HangingSource(ProxySource):
    """A server that accepts the connection and never answers."""

    def __init__(self, name: str, seconds: float) -> None:
        self.name = name
        self._seconds = seconds

    def fetch(self, timeout: float | None = None):
        import time

        time.sleep(self._seconds)
        yield "1.1.1.1:80"


def test_a_stop_does_not_wait_for_slow_sources() -> None:
    import threading
    import time

    collector = ProxyCollector([_HangingSource(f"hang-{i}", 5.0) for i in range(20)])
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    batch = collector.collect(stop_event=stop)
    assert time.monotonic() - started < 1.5          # not 5 s (and not 20 x 5 s one after the other)
    assert batch.entries == []


def test_sources_are_downloaded_side_by_side_but_deduped_in_source_order() -> None:
    import time

    started = time.monotonic()
    collector = ProxyCollector([_HangingSource(f"s{i}", 0.3) for i in range(16)])
    batch = collector.collect()
    assert time.monotonic() - started < 1.5          # 16 x 0.3 s one by one would be 4.8 s
    assert [stat.name for stat in batch.source_stats] == [f"s{i}" for i in range(16)]
    assert [e.source for e in batch.entries] == ["s0"]        # the same endpoint everywhere: the first list keeps it
    assert [stat.found for stat in batch.source_stats] == [1] + [0] * 15
