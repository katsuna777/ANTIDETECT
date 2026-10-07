"""ProxyChecker: concurrent availability / latency / IP / country / anonymity
verification.

Design notes
------------
* Workers are a bounded set of *daemon* threads that pull proxies from a queue — never
  one thread per proxy. Daemon, because a stop (or closing the app) must not wait for the
  checks still in flight: they finish by themselves and nobody joins them. The batch loop looks at
  the stop event every ~0.1 s, so a stop is felt at once, not after the next proxy happens to finish.
* Each proxy check is fully isolated; ``check_one`` catches every exception,
  so one dead proxy can never break the batch.
* Proxies perform network I/O only inside worker threads; the database stays on
  the caller thread and is updated from the collected outcomes afterwards.
* Dead handling is *resilient*: a single timeout never marks a proxy DEAD. The
  decision is based on ``consecutive_failures`` accumulated across runs and
  applied by :class:`ProxyService` against the configured threshold.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from antidetect.domain.enums.proxy_status import Anonymity, ProxyProtocol
from antidetect.domain.models.proxy import Proxy
from antidetect.infrastructure.proxy import ip_providers as ip_prov
from antidetect.infrastructure.proxy.transport import (
    HTTPS_CAPABILITY_ENDPOINT,
    HTTPS_HEALTH_ENDPOINT,
    build_transport,
)

ECHO_HEADERS_ENDPOINT = "http://httpbin.org/headers"
_STOP_POLL_S = 0.1


@dataclass
class CheckOutcome:
    proxy: Proxy
    ok: bool
    latency_ms: Optional[int] = None
    external_ip: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    anonymity: Optional[Anonymity] = None
    provider: Optional[str] = None
    error: Optional[str] = None
    echo_headers: Optional[dict[str, str]] = field(default=None, repr=False)


def classify_anonymity(
    external_ip: str | None,
    direct_ip: str | None,
    echo_headers: dict[str, str] | None,
) -> Anonymity:
    """Conservative anonymity classification from verified network facts.

    Rule order matters:
    * Our direct IP visible behind the proxy (same exit IP, or leaked via
      ``X-Forwarded-For``) ⇒ ``transparent``.
    * Echo server reports a forwarded client list not containing our IP
      ⇒ ``anonymous``.
    * Echo server saw nothing forwarded (empty/absent headers) and the exit IP
      differs from ours ⇒ ``elite``.
    * No evidence at all (``echo_headers is None``) ⇒ ``unknown``.
    """
    if (direct_ip and external_ip) and direct_ip == external_ip:
        return Anonymity.TRANSPARENT
    if echo_headers is None:
        return Anonymity.UNKNOWN
    forwarded = _header(echo_headers, "X-Forwarded-For")
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if direct_ip and any(hop == direct_ip for hop in hops):
            return Anonymity.TRANSPARENT
        return Anonymity.ANONYMOUS
    return Anonymity.ELITE


def _header(headers: dict[str, str], key: str) -> str | None:
    for name, value in headers.items():
        if name.lower() == key.lower():
            return value
    return None


class AnonymityProber:
    """Best-effort X-Forwarded-For echo used by the anonymity classifier."""

    def __init__(self, endpoint: str = ECHO_HEADERS_ENDPOINT) -> None:
        self._endpoint = endpoint

    def probe(self, transport, timeout: float) -> dict[str, str] | None:
        try:
            reply = transport.get(self._endpoint, timeout)
        except Exception:
            return None
        if reply.status != 200:
            return None
        import json

        try:
            data = json.loads(reply.body)
        except ValueError:
            return None
        headers = data.get("headers")
        return {str(k): str(v) for k, v in headers.items()} if headers else None


Runner = Callable[[Proxy, float], CheckOutcome]


def _noop_geo_reviewer(
    external_ip: str, known_code: str | None = None, timeout: float = 6.0
) -> tuple[str | None, str | None]:
    """Default country reviewer: trusts the provider (no network in tests)."""
    return None, None


class ProxyChecker:
    """Concurrent checker with injectable providers/transports for testing."""

    def __init__(
        self,
        providers=None,
        transport_factory=None,
        anonymity_prober: Optional[AnonymityProber] = None,
        timeout: float = 8.0,
        workers: int = 20,
        max_failures: int = 3,
        resolve_direct_ip: bool = True,
        direct_ip_provider: Optional[Callable[[], str | None]] = None,
        https_capability_endpoint: str = HTTPS_CAPABILITY_ENDPOINT,
        geo_reviewer: Optional[Callable[..., tuple[str | None, str | None]]] = None,
        require_country: bool = False,
        max_latency_ms: int | None = None,
    ) -> None:
        self._providers = providers or ip_prov.default_providers()
        self._transport_factory = transport_factory or build_transport
        self._anonymity_prober = anonymity_prober or AnonymityProber()
        self._default_timeout = timeout
        self._workers = workers
        self.max_failures = max_failures
        self._https_capability_endpoint = https_capability_endpoint
        # Strictness gates (opt-in; production enables both via di.py):
        # * require_country — a proxy whose exit country cannot be determined
        #   is useless for geo matching (autoconfig, doctor gate), so it fails
        #   instead of entering the pool as a country-less WORKING proxy;
        # * max_latency_ms — caps the provider-probe round trip; slower
        #   proxies make browsing painful and burn worker time.
        self._require_country = require_country
        self._max_latency_ms = max_latency_ms

        self._direct_ip_provider = direct_ip_provider or ip_prov.fetch_direct_ip
        self._direct_ip: str | None = None
        self._direct_ip_lock = threading.Lock()
        self._geo_cache: dict[str, tuple[str | None, str | None]] = {}
        self._geo_cache_lock = threading.Lock()
        # Optional independent country cross-check for an exit IP. Production
        # wires the multi-database consensus (ip_providers.resolve_country_consensus);
        # tests leave the no-op default so they never touch the network.
        self._geo_reviewer = geo_reviewer or _noop_geo_reviewer
        if resolve_direct_ip:
            self._resolve_direct_ip()

    # ---------------------------------------------------------------- public

    @property
    def direct_ip(self) -> str | None:
        return self._direct_ip

    def ensure_direct_ip(self) -> None:
        with self._direct_ip_lock:
            if self._direct_ip is None:
                self._resolve_direct_ip()

    def check_one(self, proxy: Proxy, timeout: float | None = None) -> CheckOutcome:
        self.ensure_direct_ip()
        timeout = timeout or self._default_timeout
        try:
            return self._check_impl(proxy, timeout)
        except Exception as exc:
            return CheckOutcome(proxy, ok=False, error=str(exc))

    def check_all(
        self,
        proxies: list[Proxy],
        workers: int | None = None,
        timeout: float | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_proxy: Callable[[CheckOutcome], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> list[CheckOutcome]:
        """Check every proxy concurrently; never raises on individual failure.

        ``on_progress(done, total)`` is invoked after each completed check so
        callers (e.g. a GUI progress bar) can react without polling the DB.
        ``on_proxy(outcome)`` streams each finished result as soon as that
        proxy's check completes, which lets a UI render a live list while the
        batch is still running. Both callbacks are entirely optional.

        ``stop_event`` (if given) lets a caller abort the batch: as soon as it
        is set the loop stops collecting further results and the already
        collected outcomes are returned. Proxies not started yet are dropped; any
        checks already in flight finish on their own daemon threads without being
        awaited.
        """
        if not proxies:
            return []
        if stop_event is not None and stop_event.is_set():
            return []
        self.ensure_direct_ip()
        workers = workers or self._workers
        timeout = timeout or self._default_timeout
        total = len(proxies)
        todo: "queue.SimpleQueue[Proxy]" = queue.SimpleQueue()
        for proxy in proxies:
            todo.put(proxy)
        finished: "queue.SimpleQueue[CheckOutcome]" = queue.SimpleQueue()
        halt = threading.Event()          # set when the batch is over (stopped or done): workers take no more work

        def work() -> None:
            while not halt.is_set():
                try:
                    proxy = todo.get_nowait()
                except queue.Empty:
                    return
                try:
                    outcome = self._check_impl(proxy, timeout)
                except Exception as exc:  # noqa: BLE001 - one proxy never breaks the batch
                    outcome = CheckOutcome(proxy, ok=False, error=str(exc))
                finished.put(outcome)

        for number in range(max(1, min(workers, total))):
            threading.Thread(target=work, name=f"proxy-check-{number}", daemon=True).start()

        outcomes: list[CheckOutcome] = []
        try:
            while len(outcomes) < total:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    outcome = finished.get(timeout=_STOP_POLL_S)
                except queue.Empty:
                    continue
                outcomes.append(outcome)
                if on_proxy is not None:
                    on_proxy(outcome)
                if on_progress is not None:
                    on_progress(len(outcomes), total)
        finally:
            halt.set()
        return outcomes

    # --------------------------------------------------------------- internal

    def _check_impl(self, proxy: Proxy, timeout: float) -> CheckOutcome:
        transport = self._transport_factory(proxy)
        started = time.perf_counter()
        result = self._providers.probe(transport, timeout)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if result is None or not result.external_ip:
            return CheckOutcome(
                proxy,
                ok=False,
                error="external IP discovery failed (timeout or refused)",
            )
        if (
            self._max_latency_ms is not None
            and elapsed_ms > self._max_latency_ms
        ):
            return CheckOutcome(
                proxy,
                ok=False,
                latency_ms=elapsed_ms,
                external_ip=result.external_ip,
                error=(
                    f"too slow ({elapsed_ms}ms > "
                    f"{self._max_latency_ms}ms limit)"
                ),
            )
        # HTTP(S)-protocol proxies must tunnel HTTPS end-to-end. Chrome spins
        # forever (endless search loading) on a proxy that forwards plain HTTP
        # but cannot CONNECT to 443, so such proxies are rejected here and
        # eventually filtered out of the pool as dead.
        if proxy.protocol in (ProxyProtocol.HTTP, ProxyProtocol.HTTPS):
            if not self._supports_https(transport, timeout):
                return CheckOutcome(
                    proxy,
                    ok=False,
                    error=(
                        "HTTPS through proxy failed (CONNECT refused/reset/"
                        "timeout or non-2xx reply)"
                    ),
                )
        country, country_code = result.country, result.country_code
        if result.external_ip:
            # Always have the independent reviewer look at the exit IP: a fresh
            # ip-api answer is not enough on its own (stale for renumbered
            # ranges, e.g. a Swedish range reported as Hong Kong), so the
            # country is cross-checked even when the provider already returned
            # one. The provider values are kept as a fallback on review failure.
            reviewed_country, reviewed_code = self._resolve_geo(
                result.external_ip, country_code, min(timeout, 6.0)
            )
            country = reviewed_country or country
            country_code = reviewed_code or country_code
        if self._require_country and not country_code:
            return CheckOutcome(
                proxy,
                ok=False,
                latency_ms=elapsed_ms,
                external_ip=result.external_ip,
                error="exit country could not be determined",
            )
        anonymity = self._probe_anonymity(transport, result.external_ip, timeout)
        return CheckOutcome(
            proxy,
            ok=True,
            latency_ms=elapsed_ms,
            external_ip=result.external_ip,
            country=country,
            country_code=country_code,
            anonymity=anonymity,
            provider=self._providers.name,
        )

    def _supports_https(self, transport, timeout: float) -> bool:
        # Two different hosts, so a proxy that only ever answers one target
        # (whitelisted CONNECT or a rate-limited endpoint) is not marked
        # WORKING just because its one lucky request came in.
        endpoints = (self._https_capability_endpoint, HTTPS_HEALTH_ENDPOINT)
        share = max(timeout / len(endpoints), 1.0)
        for endpoint in endpoints:
            try:
                reply = transport.get(endpoint, share)
            except Exception:
                return False
            if not 200 <= reply.status < 300:
                return False
        return True

    def _probe_anonymity(self, transport, external_ip: str, timeout: float) -> Anonymity:
        probe_timeout = min(timeout, 4.0)
        try:
            headers = self._anonymity_prober.probe(transport, probe_timeout)
        except Exception:
            headers = None
        return classify_anonymity(external_ip, self._direct_ip, headers)

    def _resolve_geo(
        self, external_ip: str, known_code: str | None, timeout: float
    ) -> tuple[str | None, str | None]:
        with self._geo_cache_lock:
            cached = self._geo_cache.get(external_ip)
        if cached is not None:
            return cached
        try:
            country, country_code = self._geo_reviewer(
                external_ip, known_code=known_code, timeout=timeout
            )
        except Exception:
            country, country_code = None, None
        with self._geo_cache_lock:
            self._geo_cache[external_ip] = (country, country_code)
        return country, country_code

    def _resolve_direct_ip(self) -> None:
        try:
            ip = self._direct_ip_provider()
        except Exception:
            ip = None
        self._direct_ip = ip