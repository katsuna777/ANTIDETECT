from __future__ import annotations

from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.infrastructure.proxy.proxy_parser import parse_line, stamp_source


def test_host_is_normalized_to_lowercase() -> None:
    entry = parse_line("PROXY.Example.COM:8080")
    assert entry is not None
    assert entry.host == "proxy.example.com"


def test_ipv6_brackets_are_stripped() -> None:
    entry = parse_line("[2606:4700::1111]:443")
    assert entry is not None
    assert entry.host == "2606:4700::1111"


def test_default_port_applied_from_https_scheme() -> None:
    entry = parse_line("https://1.2.3.4")
    assert entry is None  # bare scheme without ``:port`` is not enough

    entry = parse_line("https://1.2.3.4:8443")
    assert entry is not None
    assert (entry.protocol, entry.port) == (ProxyProtocol.HTTPS, 8443)


def test_credentials_normalization_is_preserved() -> None:
    entry = parse_line("login:password@10.0.0.1:3128")
    assert entry is not None
    assert (entry.username, entry.password) == ("login", "password")


def test_stamp_source_attaches_and_keeps_first() -> None:
    entry = parse_line("1.2.3.4:80")
    assert entry is not None
    stamped = stamp_source(entry, "github-1")
    assert stamped.source == "github-1"
    assert stamp_source(stamped, "github-2").source == "github-1"
    assert stamp_source(stamped, "github-1") is stamped


def test_invalid_host_rejected() -> None:
    assert parse_line("..:8080") is None
    assert parse_line("bad host:8080") is None
    assert parse_line("http://:8080") is None
    assert parse_line("1.2.3.999:80") is None  # not a valid IP either