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
    """Build GitHub sources from bare URLs, detecting protocol from the path."""
    sources: list[ProxySource] = []
    for index, url in enumerate(urls):
        protocol = _protocol_for_url(url)
        name = f"github-{index + 1}"
        if protocol is not None:
            name = protocol.value.lower()
        sources.append(
            GitHubProxySource(name=name, url=url, protocol=protocol)
        )
    return sources


def _protocol_for_url(url: str) -> ProxyProtocol | None:
    last_segment = url.rstrip("/").split("/")[-1].lower()
    lowered_segment = last_segment.lower()
    if "socks5" in lowered_segment:
        return ProxyProtocol.SOCKS5
    if "socks4" in lowered_segment:
        return None
    if "https" in lowered_segment or "ssl" in lowered_segment:
        return ProxyProtocol.HTTPS
    return ProxyProtocol.HTTP


DEFAULT_SOURCE_URLS = [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
]


def default_sources() -> list[ProxySource]:
    return build_sources(DEFAULT_SOURCE_URLS)