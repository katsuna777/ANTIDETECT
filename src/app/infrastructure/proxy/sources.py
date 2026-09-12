"""Concrete public proxy sources.

The main production source is :class:`GitHubProxySource`, which streams raw
files of well-known public GitHub repositories. The defaults below are plain
text lists in the ``IP:PORT`` / ``protocol://IP:PORT`` formats; every one of
them can be overridden through ``ANTIDETECT_PROXY_SOURCES`` or replaced with a
subclass without any change to the collector.
"""

from __future__ import annotations

import urllib.request
from typing import Iterable

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.errors import ProxySourceError
from app.infrastructure.proxy.proxy_source import ProxySource

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class GitHubProxySource(ProxySource):
    """Streams a raw GitHub-hosted proxy list line by line.

    ``protocol`` is the assumed protocol for lines that omit the scheme (most
    public lists are ``IP:PORT`` only and declare their protocol in the path).
    """

    def __init__(
        self,
        name: str,
        url: str,
        protocol: ProxyProtocol | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.name = name
        self.url = url
        self.protocol = protocol
        self._user_agent = user_agent

    def fetch(self, timeout: float | None = None) -> Iterable[str]:
        request = urllib.request.Request(
            self.url,
            headers={"User-Agent": self._user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                for raw in response:
                    yield raw.decode("utf-8", errors="replace")
        except Exception as exc:
            raise ProxySourceError(self.name, str(exc)) from exc


def build_sources(urls: list[str]) -> list[ProxySource]:
    """Build proxy sources from bare URLs, detecting protocol from the path.

    Names are unique per URL (``<protocol>-<index>``) so per-source
    statistics never collide when several lists share one protocol.
    """
    sources: list[ProxySource] = []
    for index, url in enumerate(urls):
        protocol = _protocol_for_url(url)
        if protocol is not None:
            name = f"{protocol.value.lower()}-{index + 1}"
        else:
            name = f"github-{index + 1}"
        sources.append(
            GitHubProxySource(name=name, url=url, protocol=protocol)
        )
    return sources


def _protocol_for_url(url: str) -> ProxyProtocol | None:
    """Detect the default protocol for bare ``IP:PORT`` lines from the URL.

    The whole URL is scanned (not just the last segment) so sharded layouts
    like ``.../countries/ru/https/data.txt`` are typed correctly. Lines that
    carry an explicit scheme (``http://``/``https://``/``socks5://``) always
    win over this default during parsing.

    ``https``/``ssl`` in the path maps to :data:`ProxyProtocol.HTTP`: public
    ``https.txt`` lists contain plain-HTTP proxies verified for CONNECT
    tunneling to HTTPS targets, not TLS-to-proxy endpoints. They still have
    to pass the checker's HTTPS-CONNECT gate before entering the pool, so
    only genuinely HTTPS-capable proxies survive.
    """
    lowered = url.lower()
    if "socks5" in lowered:
        return ProxyProtocol.SOCKS5
    if "socks4" in lowered:
        return None
    if "https" in lowered or "ssl" in lowered:
        return ProxyProtocol.HTTP
    return ProxyProtocol.HTTP


# Countries whose exits matter most for users in RU: Russia itself, nearby
# CIS exits (BY/KZ/UA) and low-latency EU exits. Proxyscrape publishes
# per-country HTTPS shards (lowercase code + /https/ subpath); hproxy
# publishes per-country volume lists (uppercase code) that the checker
# promotes to HTTPS-capable when they pass the CONNECT gate.
_GEO_HTTPS_COUNTRIES = (
    "ru",
    "by",
    "kz",
    "ua",
    "de",
    "nl",
    "fr",
    "pl",
    "fi",
    "se",
    "ee",
    "lv",
    "cz",
    "at",
    "es",
    "it",
)

_GEO_VOLUME_COUNTRIES = ("RU", "KZ", "BY", "DE", "NL", "FR", "PL", "FI")

DEFAULT_SOURCE_URLS = [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
    # --- HTTPS-capable global pools: every entry is pre-verified upstream
    # for CONNECT tunneling, so the checker's HTTPS gate lets more of them
    # into the pool instead of rejecting plain-HTTP-only proxies.
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.txt",
    "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main/proxies/protocols/https/data.txt",
    "https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/https.txt",
    "https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_ssl.txt",
    "https://raw.githubusercontent.com/r00tee/Proxy-List/main/Https.txt",
    "https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/https.txt",
    # --- Per-country HTTPS shards (RU + CIS + EU): small but 100% geo- and
    # HTTPS-relevant, no client-side filtering needed.
    *[
        "https://cdn.jsdelivr.net/gh/proxyscrape/free-proxy-list@main"
        f"/proxies/countries/{code}/https/data.txt"
        for code in _GEO_HTTPS_COUNTRIES
    ],
    # --- Per-country volume lists (RU + CIS + EU): large bare IP:PORT
    # pools; the checker keeps whichever pass the HTTPS-CONNECT gate.
    *[
        "https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main"
        f"/by-country/{code}.txt"
        for code in _GEO_VOLUME_COUNTRIES
    ],
]


def default_sources() -> list[ProxySource]:
    return build_sources(DEFAULT_SOURCE_URLS)