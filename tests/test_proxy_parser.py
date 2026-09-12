from __future__ import annotations

import pytest

from app.domain.enums.proxy_status import ProxyProtocol
from app.infrastructure.proxy.proxy_parser import parse_line


def test_parses_bare_ip_port() -> None:
    entry = parse_line("1.2.3.4:8080")
    assert entry is not None
    assert entry.protocol is ProxyProtocol.HTTP
    assert entry.host == "1.2.3.4"
    assert entry.port == 8080
    assert entry.username is None


def test_parses_protocol_scheme() -> None:
    entry = parse_line("socks5://1.2.3.4:1080")
    assert entry is not None
    assert entry.protocol is ProxyProtocol.SOCKS5
    assert entry.port == 1080


def test_parses_credentials_bare() -> None:
    entry = parse_line("user:secret@1.2.3.4:3128")
    assert entry is not None
    assert entry.username == "user"
    assert entry.password == "secret"
    assert entry.host == "1.2.3.4"


def test_parses_credentials_with_scheme() -> None:
    entry = parse_line("http://u:p@host.example.com:80")
    assert entry is not None
    assert entry.protocol is ProxyProtocol.HTTP
    assert entry.username == "u"
    assert entry.password == "p"


def test_parses_hostname() -> None:
    entry = parse_line("proxy.example.com:443")
    assert entry is not None
    assert entry.host == "proxy.example.com"


def test_parses_bracketed_ipv6() -> None:
    entry = parse_line("[2001:db8::1]:8080")
    assert entry is not None
    assert entry.host == "2001:db8::1"
    assert entry.port == 8080


def test_parses_lowercases_host() -> None:
    entry = parse_line("EXAMPLE.com:80")
    assert entry is not None
    assert entry.host == "example.com"


def test_parses_default_protocol_from_source() -> None:
    entry = parse_line("1.2.3.4:1080", default_protocol=ProxyProtocol.SOCKS5)
    assert entry is not None
    assert entry.protocol is ProxyProtocol.SOCKS5


def test_unknown_scheme_rejected() -> None:
    assert parse_line("socks4://1.2.3.4:1080") is None
    assert parse_line("ftp://1.2.3.4:21") is None


def test_socks5h_is_socks5() -> None:
    entry = parse_line("socks5h://1.2.3.4:1080")
    assert entry is not None
    assert entry.protocol is ProxyProtocol.SOCKS5


def test_comment_and_blank_lines_ignored() -> None:
    assert parse_line("# comment") is None
    assert parse_line("") is None
    assert parse_line("   ") is None


def test_invalid_lines_ignored() -> None:
    assert parse_line("not a proxy") is None
    assert parse_line("1.2.3.4") is None
    assert parse_line("1.2.3.4:99999") is None
    assert parse_line("1.2.3.4:0") is None
    assert parse_line("1.2.3.4:-1") is None
    assert parse_line("http://") is None


def test_percent_encoded_credentials_are_decoded() -> None:
    entry = parse_line("user%40x:p%40ss@1.2.3.4:8080")
    assert entry is not None
    assert entry.username == "user@x"
    assert entry.password == "p@ss"


def test_bare_ip_with_port_surrounding_whitespace() -> None:
    entry = parse_line("  9.9.9.9:8888  ")
    assert entry is not None
    assert entry.host == "9.9.9.9"
    assert entry.port == 8888