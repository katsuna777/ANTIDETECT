"""External-IP / country detection providers.

``IPCheckProvider`` is the abstraction that lets us discover the *actual*
external IP a proxy exits from, plus (when the endpoint provides it) the
country bind to that IP. Providers are interchangeable and can be chained in a
composite fallback, so a new provider can be dropped in by implementing
``probe()``.
"""

from __future__ import annotations

import ipaddress
import json
import queue
import threading
import time
from typing import Iterable, Protocol

from antidetect.infrastructure.proxy.transport import DirectTransport


class IPProbeResult:
    """Verified network facts discovered through a proxy."""

    __slots__ = ("external_ip", "country", "country_code", "headers")

    def __init__(
        self,
        external_ip: str,
        country: str | None = None,
        country_code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.external_ip = external_ip
        self.country = country
        self.country_code = country_code
        self.headers = headers

    def __repr__(self) -> str:
        return (
            f"IPProbeResult(external_ip={self.external_ip}, "
            f"country={self.country}, country_code={self.country_code})"
        )


class IPCheckProvider(Protocol):
    name: str

    def probe(self, transport, timeout: float) -> IPProbeResult | None: ...


class IpApiProvider:
    """ip-api.com single-call provider: external IP + country + country code.

    Plain HTTP so it works through HTTP and SOCKS5 transports alike.
    """

    name = "ip-api"

    def __init__(
        self,
        endpoint: str = "http://ip-api.com/json/?fields=status,message,country,countryCode,query",
    ) -> None:
        self._endpoint = endpoint

    def probe(self, transport, timeout: float) -> IPProbeResult | None:
        reply = transport.get(self._endpoint, timeout)
        if reply.status != 200:
            return None
        try:
            data = json.loads(reply.body)
        except ValueError:
            return None
        if data.get("status") != "success":
            return None
        external_ip = data.get("query")
        if not _valid_ip(external_ip):
            return None
        return IPProbeResult(
            external_ip=external_ip,
            country=data.get("country") or None,
            country_code=(data.get("countryCode") or None),
        )


class PlainIpProvider:
    """Fallback that only discovers the external IP from a plaintext service."""

    name = "plain-ip"

    def __init__(self, endpoints: Iterable[str] = ()) -> None:
        self._endpoints = list(endpoints) or [
            "http://api.ipify.org/",
            "http://ip.42.pl/raw",
        ]

    def probe(self, transport, timeout: float) -> IPProbeResult | None:
        for endpoint in self._endpoints:
            try:
                reply = transport.get(endpoint, timeout)
            except Exception:
                continue
            candidate = reply.body.strip()
            if _valid_ip(candidate):
                return IPProbeResult(external_ip=candidate)
        return None


class CompositeIpProvider:
    """Tries providers in order; the first successful result wins."""

    def __init__(self, providers: list[IPCheckProvider], name: str = "composite") -> None:
        self.providers = list(providers)
        self.name = name

    def probe(self, transport, timeout: float) -> IPProbeResult | None:
        for provider in self.providers:
            try:
                result = provider.probe(transport, timeout)
            except Exception:
                result = None
            if result is not None and _valid_ip(result.external_ip):
                return result
        return None


def default_providers() -> CompositeIpProvider:
    return CompositeIpProvider([IpApiProvider(), PlainIpProvider()])


def fetch_direct_ip(timeout: float = 6.0, transport=None) -> str | None:
    """Our own external IP as seen from the internet (no proxy).

    Providers race concurrently under one shared deadline: sequentially they
    could stall the whole batch (ip-api 6s, then ipify 6s, then 42.pl 6s)
    before a single proxy is checked. First *valid* result wins; a fast
    failure never beats a slower success.
    """
    transport = transport or DirectTransport()
    providers = [IpApiProvider(), PlainIpProvider()]
    found: queue.Queue[str] = queue.Queue()

    def attempt(provider) -> None:
        try:
            result = provider.probe(transport, timeout)
        except Exception:
            result = None
        if result is not None and _valid_ip(result.external_ip):
            found.put(result.external_ip)

    threads = [
        threading.Thread(target=attempt, args=(provider,), daemon=True)
        for provider in providers
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        try:
            return found.get(timeout=max(deadline - time.monotonic(), 0.0))
        except queue.Empty:
            return None


# ----------------------------------------------------------------- geo consensus

def _direct_json(url: str, timeout: float, transport=None) -> dict | None:
    transport = transport or DirectTransport()
    try:
        reply = transport.get(url, timeout)
    except Exception:
        return None
    if reply.status != 200:
        return None
    try:
        data = json.loads(reply.body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class _IpWhoIsGeo:
    """ipwho.is: full country name + 2-letter code; no key needed."""

    name = "ipwhois"

    def lookup(self, ip: str, timeout: float, transport) -> tuple[str | None, str | None]:
        data = _direct_json(f"https://ipwho.is/{ip}", timeout, transport)
        if not data or data.get("success") is not True:
            return None, None
        return data.get("country") or None, data.get("country_code") or None


class _IpInfoGeo:
    """ipinfo.io: returns a 2-letter country code only (no name)."""

    name = "ipinfo"

    def lookup(self, ip: str, timeout: float, transport) -> tuple[str | None, str | None]:
        data = _direct_json(f"https://ipinfo.io/{ip}/json", timeout, transport)
        if not data:
            return None, None
        return None, data.get("country") or None


class _IpApiGeo:
    """ip-api.com direct lookup of a specific IP (name + country code)."""

    name = "ipapi"

    def lookup(self, ip: str, timeout: float, transport) -> tuple[str | None, str | None]:
        data = _direct_json(
            f"http://ip-api.com/json/{ip}?fields=status,country,countryCode",
            timeout,
            transport,
        )
        if not data or data.get("status") != "success":
            return None, None
        return data.get("country") or None, data.get("countryCode") or None


def resolve_country_consensus(
    ip: str,
    known_code: str | None = None,
    timeout: float = 6.0,
    transport=None,
    providers=None,
) -> tuple[str | None, str | None]:
    """Country for ``ip`` agreed on by at least two independent databases.

    ``known_code`` is the country already reported by the primary (in-proxy)
    lookup — usually ip-api, which is stale for recently renumbered ranges. A
    single provider's answer is therefore no longer trusted on its own: ipwho.is
    and ipinfo.io are consulted as cross-checks and the code with ≥2 votes wins.
    With no agreement the known opinion is kept (better than guessing), and on
    total failure ``(None, None)`` is returned.

    ``providers`` is injectable for tests; defaults skip a *second* ip-api call
    when ``known_code`` is already its opinion (same database, would pollute the
    vote).
    """
    transport = transport or DirectTransport()
    if providers is None:
        providers = [_IpWhoIsGeo(), _IpInfoGeo()]
        if not known_code:
            providers.append(_IpApiGeo())
    opinions: list[tuple[str | None, str | None]] = []
    if known_code:
        opinions.append((None, known_code))
    share = timeout / max(len(providers), 1)
    # Cross-checks race concurrently under one shared deadline instead of
    # running back-to-back: same votes, a fraction of the wall time.
    # Results are re-sorted into provider order so ties break exactly like
    # the old sequential loop.
    found: queue.Queue[tuple[int, str | None, str | None]] = queue.Queue()

    def attempt(index: int, provider) -> None:
        try:
            name, code = provider.lookup(ip, share, transport)
        except Exception:
            return
        if code:
            found.put((index, name, code))

    threads = [
        threading.Thread(target=attempt, args=(index, provider), daemon=True)
        for index, provider in enumerate(providers)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + max(share, 0.0)
    for thread in threads:
        thread.join(timeout=max(deadline - time.monotonic(), 0.0))
    ranked: list[tuple[int, str | None, str | None]] = []
    while True:
        try:
            ranked.append(found.get_nowait())
        except queue.Empty:
            break
    for _, name, code in sorted(ranked):
        opinions.append((name, code))
    votes: dict[str, int] = {}
    for _, code in opinions:
        votes[code] = votes.get(code, 0) + 1
    best = max(votes, key=votes.get) if votes else None
    if best is not None and votes[best] >= 2:
        name = next((n for n, c in opinions if c == best and n), None)
        return name, best
    if known_code:
        name = next((n for n, c in opinions if n and c == known_code), None)
        return name, known_code
    for name, code in opinions:
        if code:
            return name, code
    return None, None


def _valid_ip(candidate: str | None) -> bool:
    if not candidate:
        return False
    try:
        ipaddress.ip_address(candidate.strip())
    except ValueError:
        return False
    return True