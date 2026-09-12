"""Default proxy pool: every source URL is known-alive and typed correctly.

Source URLs were verified one by one (plain ``IP:PORT`` lines over HTTPS).
If a list dies upstream, this suite does not catch it — but it does catch
typos, wrong branches and protocol-detection regressions.
"""

from __future__ import annotations

from app.domain.enums.proxy_status import ProxyProtocol
from app.infrastructure.proxy.sources import DEFAULT_SOURCE_URLS, build_sources


def test_default_pool_has_eleven_unique_https_sources() -> None:
    assert len(DEFAULT_SOURCE_URLS) == 11
    assert len(set(DEFAULT_SOURCE_URLS)) == 11
    for url in DEFAULT_SOURCE_URLS:
        assert url.startswith("https://raw.githubusercontent.com/")


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
