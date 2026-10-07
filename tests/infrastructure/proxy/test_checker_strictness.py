"""Strict pool quality: country requirement + latency ceiling.

Both gates are opt-in (production enables them via di.py); defaults keep the
historic lenient behavior so existing tests stay green.
"""

from __future__ import annotations

from antidetect.infrastructure.proxy.checker import ProxyChecker
from antidetect.infrastructure.proxy.ip_providers import IPProbeResult
from tests.support.fakes import FakeTransport, StubProber, StubProviders, make_proxy


def _build_checker(providers=None, transport=None, **kwargs) -> ProxyChecker:
    transport = transport if transport is not None else FakeTransport()
    return ProxyChecker(
        providers=providers or StubProviders(result=_ok_result()),
        transport_factory=lambda proxy: transport,
        anonymity_prober=StubProber(headers={}),
        resolve_direct_ip=False,
        **kwargs,
    )


def _ok_result(ip="203.0.113.7", country="Germany", country_code="DE"):
    return IPProbeResult(
        external_ip=ip, country=country, country_code=country_code
    )


def _no_country_result(ip="203.0.113.7"):
    return IPProbeResult(external_ip=ip)


# ------------------------------------------------------- require_country


def test_countryless_proxy_fails_when_required() -> None:
    checker = _build_checker(
        providers=StubProviders(result=_no_country_result()),
        geo_reviewer=lambda ip, known_code=None, timeout=6.0: (None, None),
        require_country=True,
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is False
    assert "country" in (outcome.error or "")


def test_countryless_proxy_passes_when_not_required() -> None:
    checker = _build_checker(
        providers=StubProviders(result=_no_country_result()),
        geo_reviewer=lambda ip, known_code=None, timeout=6.0: (None, None),
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is True


def test_country_from_review_satisfies_requirement() -> None:
    checker = _build_checker(
        providers=StubProviders(result=_no_country_result()),
        geo_reviewer=lambda ip, known_code=None, timeout=6.0: ("Germany", "DE"),
        require_country=True,
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is True
    assert outcome.country_code == "DE"


# ------------------------------------------------------- max_latency_ms


def test_sluggish_proxy_fails_latency_ceiling() -> None:
    checker = _build_checker(
        transport=FakeTransport(delay=0.05),
        max_latency_ms=10,
    )
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is False
    assert "slow" in (outcome.error or "")
    assert outcome.latency_ms is not None and outcome.latency_ms >= 10


def test_responsive_proxy_passes_latency_ceiling() -> None:
    checker = _build_checker(max_latency_ms=5000)
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is True


def test_no_ceiling_by_default() -> None:
    checker = _build_checker(transport=FakeTransport(delay=0.05))
    outcome = checker.check_one(make_proxy(1))
    assert outcome.ok is True


# ------------------------------------------------------- production wiring


def test_production_container_enables_strict_checks(gui_container) -> None:
    checker = gui_container.proxies._checker
    assert checker._require_country is True
    assert checker._max_latency_ms == 4000
