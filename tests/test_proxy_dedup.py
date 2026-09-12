from __future__ import annotations

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.models.proxy_entry import ProxyEntry
from app.infrastructure.proxy.proxy_parser import dedupe


def _entry(protocol, host, port) -> ProxyEntry:
    return ProxyEntry(protocol=protocol, host=host, port=port)


def test_dedupe_exact_duplicates_keep_first() -> None:
    entries = [
        _entry(ProxyProtocol.HTTP, "1.2.3.4", 8080),
        _entry(ProxyProtocol.HTTP, "1.2.3.4", 8080),
    ]
    result = dedupe(entries)
    assert len(result) == 1
    assert result[0] is entries[0]


def test_dedupe_case_insensitive_host() -> None:
    entries = [
        _entry(ProxyProtocol.HTTP, "1.2.3.4", 8080),
        _entry(ProxyProtocol.HTTP, "1.2.3.4", 8080),
    ]
    assert len(dedupe(entries)) == 1


def test_dedupe_distinguishes_protocol() -> None:
    entries = [
        _entry(ProxyProtocol.HTTP, "1.2.3.4", 8080),
        _entry(ProxyProtocol.SOCKS5, "1.2.3.4", 8080),
    ]
    result = dedupe(entries)
    assert len(result) == 2


def test_dedupe_distinguishes_ports() -> None:
    entries = [
        _entry(ProxyProtocol.HTTP, "1.2.3.4", 8080),
        _entry(ProxyProtocol.HTTP, "1.2.3.4", 8081),
    ]
    assert len(dedupe(entries)) == 2


def test_dedupe_preserves_order() -> None:
    entries = [
        _entry(ProxyProtocol.HTTP, "a.com", 80),
        _entry(ProxyProtocol.HTTP, "b.com", 80),
        _entry(ProxyProtocol.HTTP, "a.com", 80),
        _entry(ProxyProtocol.HTTP, "c.com", 80),
    ]
    assert [e.host for e in dedupe(entries)] == ["a.com", "b.com", "c.com"]


def test_dedupe_empty() -> None:
    assert dedupe([]) == []