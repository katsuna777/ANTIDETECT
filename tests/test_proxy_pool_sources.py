"""Default proxy pool: every source URL is known-alive and typed correctly.

Source URLs were verified one by one (plain ``IP:PORT`` lines over HTTPS).
If a list dies upstream, this suite does not catch it — but it does catch
typos, wrong branches and protocol-detection regressions.
"""

from __future__ import annotations

from app.domain.enums.proxy_status import ProxyProtocol
from app.infrastructure.proxy.sources import DEFAULT_SOURCE_URLS, build_sources


def test_default_pool_has_unique_https_sources() -> None:
    assert len(DEFAULT_SOURCE_URLS) == 41
    assert len(set(DEFAULT_SOURCE_URLS)) == 41
    for url in DEFAULT_SOURCE_URLS:
        assert url.startswith(
            ("https://raw.githubusercontent.com/", "https://cdn.jsdelivr.net/gh/")
        )


def test_default_pool_covers_https_and_geo() -> None:
    joined = "\n".join(DEFAULT_SOURCE_URLS)
    # Global HTTPS-capable pools.
    assert "proxies/protocols/https/data.txt" in joined
    assert "hproxy-com/free-proxy-list/main/https.txt" in joined
    assert "http_ssl.txt" in joined
    # Per-country HTTPS shards for RU + CIS + EU.
    for code in ("ru", "de", "nl", "fr", "pl", "fi"):
        assert f"/countries/{code}/https/data.txt" in joined
    # Per-country volume lists for RU + CIS + EU.
    for code in ("RU", "DE", "NL", "FR", "PL", "FI"):
        assert f"/by-country/{code}.txt" in joined


def test_build_sources_detects_http_and_socks5() -> None:
    by_url = {source.url: source for source in build_sources(DEFAULT_SOURCE_URLS)}
    assert by_url[
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"
    ].protocol is ProxyProtocol.HTTP
    assert by_url[
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"
    ].protocol is ProxyProtocol.SOCKS5
    assert by_url[
        "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt"
    ].protocol is ProxyProtocol.HTTP
    assert by_url[
        "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt"
    ].protocol is ProxyProtocol.SOCKS5
    assert by_url[
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"
    ].protocol is ProxyProtocol.HTTP
    assert by_url[
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt"
    ].protocol is ProxyProtocol.SOCKS5
    assert by_url[
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
    ].protocol is ProxyProtocol.HTTP


def test_build_sources_types_https_lists_as_plain_http() -> None:
    # Public https.txt lists ship plain-HTTP proxies verified for CONNECT;
    # bare lines must default to HTTP so the transport does not attempt
    # TLS-to-proxy against hosts that do not speak it.
    by_url = {source.url: source for source in build_sources(DEFAULT_SOURCE_URLS)}
    assert by_url[
        "https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/https.txt"
    ].protocol is ProxyProtocol.HTTP
    assert by_url[
        "https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_ssl.txt"
    ].protocol is ProxyProtocol.HTTP
    assert by_url[
        "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/countries/ru/https/data.txt"
    ].protocol is ProxyProtocol.HTTP


def test_build_sources_names_are_unique() -> None:
    sources = build_sources(DEFAULT_SOURCE_URLS)
    names = [source.name for source in sources]
    assert len(set(names)) == len(names)
