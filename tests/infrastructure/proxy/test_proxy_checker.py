from __future__ import annotations

import time

from antidetect.infrastructure.proxy.checker import (
    ProxyChecker,
    classify_anonymity,
)
from antidetect.infrastructure.proxy.ip_providers import IPProbeResult
from tests.support.fakes import (
    FakeReply,
    FakeTransport,
    StubProber,
    StubProviders,
    make_proxy,
)


def _ok_result(ip="203.0.113.7", country="Germany", country_code="DE"):
    return IPProbeResult(
        external_ip=ip, country=country, country_code=country_code
    )


def _build_checker(
    providers=None,
    transport_result=None,
    prober_headers=None,
    direct_ip="198.51.100.9",
    **kwargs,
) -> ProxyChecker:
    transport_factory = lambda proxy: (  # noqa: E731
        transport_result
        if transport_result is not None
        else FakeTransport()
    )
    if providers is None:
        providers = StubProviders(result=_ok_result())
    prober = StubProber(headers=prober_headers)
    return ProxyChecker(
        providers=providers,
        transport_factory=transport_factory,
        anonymity_prober=prober,
        resolve_direct_ip=True,
        direct_ip_provider=lambda: direct_ip,
        **kwargs,
    )


def test_check_success_populates_outcome() -> None:
    checker = _build_checker(transport_result=FakeTransport())
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is True
    assert outcome.external_ip == "203.0.113.7"
    assert outcome.country_code == "DE"
    assert outcome.latency_ms is not None and outcome.latency_ms >= 0
    assert outcome.error is None


def test_check_replaces_provider_country_based_on_independent_review() -> None:
    """A wrong-but-cached opinion (e.g. ip-api labels a Swedish exit as HK) is
    corrected when the independent reviewer disagrees."""

    def reviewer(ip, known_code=None, timeout=6.0):
        assert ip == "203.0.113.7"
        assert known_code == "HK"
        return ("Ukraine", "UA")

    checker = ProxyChecker(
        providers=StubProviders(
            result=_ok_result(country="Hong Kong", country_code="HK")
        ),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers={}),
        resolve_direct_ip=False,
        geo_reviewer=reviewer,
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is True
    assert outcome.country_code == "UA"
    assert outcome.country == "Ukraine"


def test_check_keeps_provider_country_when_review_is_empty() -> None:
    """A silent reviewer (all databases down) must not wipe the label."""

    def reviewer(ip, known_code=None, timeout=6.0):
        return None, None

    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers={}),
        resolve_direct_ip=False,
        geo_reviewer=reviewer,
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.country_code == "DE"
    assert outcome.country == "Germany"


def test_country_review_is_cached_per_exit_ip() -> None:
    """Many proxies share one exit IP; the review must run once for all of them."""

    seen: list[str] = []

    def reviewer(ip, known_code=None, timeout=6.0):
        seen.append(ip)
        return ("Ukraine", "UA")

    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result(country_code="HK")),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers={}),
        resolve_direct_ip=False,
        geo_reviewer=reviewer,
    )
    first = checker.check_one(make_proxy(1))
    second = checker.check_one(make_proxy(2))
    assert first.country_code == "UA"
    assert second.country_code == "UA"
    assert seen == ["203.0.113.7"]


def test_check_failure_when_no_provider_result() -> None:
    checker = _build_checker(
        providers=StubProviders(result=None),
        transport_result=FakeTransport(),
    )
    outcome = checker.check_one(make_proxy(2))
    assert outcome.ok is False
    assert outcome.error is not None


def test_check_failure_when_transport_raises() -> None:
    checker = _build_checker(
        transport_result=FakeTransport(raise_error=RuntimeError("refused"))
    )
    outcome = checker.check_one(make_proxy(3))
    assert outcome.ok is False
    assert outcome.error is not None


def test_check_all_isolates_broken_proxies() -> None:
    proxies = [
        make_proxy(1, host="1.1.1.1"),
        make_proxy(2, host="2.2.2.2"),
        make_proxy(3, host="3.3.3.3"),
    ]
    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: FakeTransport(
            raise_error=RuntimeError("timeout") if proxy.id == 2 else None
        ),
        anonymity_prober=StubProber(headers=None),
        resolve_direct_ip=True,
        direct_ip_provider=lambda: "198.51.100.9",
        workers=3,
    )
    outcomes = checker.check_all(proxies, timeout=2.0)
    ok = [o for o in outcomes if o.ok]
    failed = [o for o in outcomes if not o.ok]
    assert len(outcomes) == 3
    assert len(ok) == 2
    assert len(failed) == 1
    assert failed[0].proxy.id == 2


def test_check_all_reports_progress() -> None:
    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers=None),
        resolve_direct_ip=False,
        workers=4,
    )
    proxies = [make_proxy(i, host=f"10.0.0.{i}") for i in range(1, 5)]
    seen: list[tuple[int, int]] = []
    outcomes = checker.check_all(
        proxies, timeout=5.0, on_progress=lambda done, total: seen.append((done, total))
    )
    assert len(outcomes) == 4
    assert sorted(seen) == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert seen[-1] == (4, 4)


def test_check_all_honours_stop_event() -> None:
    """A set stop_event aborts the batch: fewer outcomes and no new progress."""
    import threading

    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers=None),
        resolve_direct_ip=False,
        workers=4,
    )
    proxies = [make_proxy(i, host=f"10.0.0.{i}") for i in range(1, 11)]
    stop = threading.Event()
    stop.set()
    outcomes = checker.check_all(proxies, timeout=5.0, stop_event=stop)
    assert len(outcomes) == 0
    assert checker.check_all(proxies, timeout=5.0, stop_event=None) is not None


def test_check_all_runs_concurrently() -> None:
    """Prove the pool overlaps work by observing peak concurrency directly.

    Wall-clock timing is intentionally avoided: thread spawn/scheduling noise
    made the old ``elapsed < 0.5`` assertion flaky on loaded machines. Counting
    concurrently-executing provider calls is deterministic and still fails if
    the checks were serialized.
    """
    import threading

    lock = threading.Lock()
    active = 0
    peak = 0

    def tracking_provider(_t, _d):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _ok_result()

    fast_checker = ProxyChecker(
        providers=StubProviders(result_factory=tracking_provider),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers=None),
        resolve_direct_ip=False,
        workers=4,
    )
    proxies = [make_proxy(i, host=f"10.0.0.{i}") for i in range(1, 5)]
    outcomes = fast_checker.check_all(proxies, timeout=5.0)
    assert len(outcomes) == 4
    assert peak >= 2, f"checks ran serially (peak concurrency={peak})"


def test_latency_is_recorded() -> None:
    def slow(_t, _d):
        time.sleep(0.05)
        return _ok_result()

    checker = ProxyChecker(
        providers=StubProviders(result_factory=slow),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers=None),
        resolve_direct_ip=False,
    )
    outcome = checker.check_one(make_proxy(9))
    assert outcome.ok
    assert outcome.latency_ms >= 40


def test_anonymity_elite_when_no_forwarded_headers() -> None:
    checker = _build_checker(prober_headers={})
    outcome = checker.check_one(make_proxy(1))
    assert outcome.anonymity.value == "elite"


def test_anonymity_transparent_when_xff_leaks_direct_ip() -> None:
    checker = _build_checker(
        prober_headers={"x-forwarded-for": "198.51.100.9, 203.0.113.7"},
        direct_ip="198.51.100.9",
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.anonymity.value == "transparent"


def test_anonymity_anonymous_when_other_hop_visible() -> None:
    checker = _build_checker(
        prober_headers={"x-forwarded-for": "203.0.113.99"},
        direct_ip="198.51.100.9",
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.anonymity.value == "anonymous"


def test_anonymity_probe_failure_is_unknown_not_crash() -> None:
    class Flaky(FakeTransport):
        def __init__(self) -> None:
            self.count = 0

        def get(self, url, timeout):
            # Calls: IP probe (1), HTTPS gate (2,3), anonymity probe (4).
            self.count += 1
            if self.count >= 4:
                raise OSError("boom")
            return FakeReply()

    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: Flaky(),
        resolve_direct_ip=True,
        direct_ip_provider=lambda: "198.51.100.9",
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok
    assert outcome.anonymity.value == "unknown"


def test_check_fails_when_https_capability_missing() -> None:
    """HTTP-protocol proxies that cannot tunnel HTTPS (no CONNECT) are rejected
    so Chrome never spins on an HTTPS-only site like a search page."""

    class HttpOnly(FakeTransport):
        def get(self, url, timeout):
            if url.startswith("https://"):
                raise RuntimeError("CONNECT refused")
            return FakeReply()

    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: HttpOnly(),
        anonymity_prober=StubProber(headers={}),
        resolve_direct_ip=True,
        direct_ip_provider=lambda: "198.51.100.9",
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is False
    assert "HTTPS" in (outcome.error or "")


def test_check_fails_when_https_capability_gate_returns_error() -> None:
    class HttpsGated(ProxyChecker):
        def _supports_https(self, transport, timeout):
            raise RuntimeError("boom")

    checker = HttpsGated(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers=None),
        resolve_direct_ip=False,
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is False


def test_check_rejects_proxy_answering_only_one_https_host() -> None:
    """The HTTPS gate requires TWO different hosts: a proxy whose one lucky
    CONNECT succeeded must not be marked WORKING if it cannot reach another."""

    class OneHostOnly(FakeTransport):
        def get(self, url, timeout):
            if url.startswith("https://example.com"):
                raise RuntimeError("CONNECT refused")
            return FakeReply()

    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: OneHostOnly(),
        anonymity_prober=StubProber(headers={}),
        resolve_direct_ip=True,
        direct_ip_provider=lambda: "198.51.100.9",
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is False
    assert "HTTPS" in (outcome.error or "")


def test_probe_proxy_rejects_proxy_answering_only_one_https_host(monkeypatch) -> None:
    """Launch-time probe must also verify two hosts, so a flaky one-moment proxy
    cannot start Chromium only to leave it spinning on a dead tunnel."""

    class OneHostOnly(FakeTransport):
        def get(self, url, timeout):
            if url.startswith("https://example.com"):
                raise RuntimeError("CONNECT refused")
            return FakeReply()

    monkeypatch.setattr(
        "antidetect.infrastructure.proxy.transport.build_transport",
        lambda proxy: OneHostOnly(),
    )
    from antidetect.infrastructure.proxy.transport import probe_proxy

    assert probe_proxy(make_proxy(1), timeout=4.0) is False


def test_probe_proxy_socks_single_plain_http_probe(monkeypatch) -> None:
    """SOCKS5 keeps a single plain-HTTP probe: its tunnel is transparent to TLS
    and the browser performs the HTTPS handshake itself."""

    class SocksTransport(FakeTransport):
        def get(self, url, timeout):
            assert url.startswith("http://")
            return FakeReply()

    monkeypatch.setattr(
        "antidetect.infrastructure.proxy.transport.build_transport",
        lambda proxy: SocksTransport(),
    )
    from antidetect.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
    from antidetect.domain.models.proxy import Proxy
    from antidetect.infrastructure.proxy.transport import probe_proxy

    socks = Proxy(
        id=1,
        protocol=ProxyProtocol.SOCKS5,
        host="1.2.3.4",
        port=1080,
        status=ProxyStatus.UNKNOWN,
    )
    assert probe_proxy(socks, timeout=4.0) is True


def test_socks5_skips_https_capability_gate() -> None:
    """SOCKS5 tunnels are transparent to TLS, so HTTPS is verified by the
    browser itself and a working tunnel already qualifies the proxy."""

    class HttpOnly(FakeTransport):
        def get(self, url, timeout):
            if url.startswith("https://"):
                raise RuntimeError("CONNECT refused")
            return FakeReply()

    from antidetect.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
    from antidetect.domain.models.proxy import Proxy

    socks = Proxy(
        id=1,
        protocol=ProxyProtocol.SOCKS5,
        host="1.2.3.4",
        port=1080,
        status=ProxyStatus.UNKNOWN,
    )
    checker = ProxyChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: HttpOnly(),
        anonymity_prober=StubProber(headers={}),
        resolve_direct_ip=False,
    )
    outcome = checker.check_one(socks)
    assert outcome.ok is True


def test_classify_direct_ip_equal_is_transparent() -> None:
    assert classify_anonymity("203.0.113.7", "203.0.113.7", None).value == "transparent"


def test_classify_no_evidence_is_unknown() -> None:
    assert classify_anonymity("203.0.113.7", None, None).value == "unknown"


def test_classify_xff_absent_is_elite_when_proxied() -> None:
    assert classify_anonymity("203.0.113.7", "198.51.100.9", {}).value == "elite"

def test_a_stop_is_felt_at_once_even_when_every_check_is_slow() -> None:
    """Dead proxies make a check last seconds: the stop must not wait for one of them to finish."""
    import threading

    class SlowChecker(ProxyChecker):
        def _check_impl(self, proxy, timeout):
            time.sleep(4.0)
            return super()._check_impl(proxy, timeout)

    checker = SlowChecker(
        providers=StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: FakeTransport(),
        anonymity_prober=StubProber(headers=None),
        resolve_direct_ip=False,
        workers=8,
    )
    proxies = [make_proxy(i, host=f"10.0.0.{i}") for i in range(1, 201)]
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    started = time.monotonic()
    outcomes = checker.check_all(proxies, timeout=5.0, stop_event=stop)
    assert time.monotonic() - started < 1.5
    assert outcomes == []
    assert not [t for t in threading.enumerate() if t.name.startswith("proxy-check-") and not t.daemon]
