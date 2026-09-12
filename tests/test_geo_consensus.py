"""Country label consensus: no single geo database decides on its own."""

from __future__ import annotations

from app.infrastructure.proxy import ip_providers as ip_prov


class StubGeo:
    def __init__(self, name: str, result) -> None:
        self.name = name
        self._result = result

    def lookup(self, ip, timeout, transport):
        return self._result


def _resolve(*results, known_code=None):
    providers = [StubGeo(f"p{i}", r) for i, r in enumerate(results)]
    return ip_prov.resolve_country_consensus(
        "203.0.113.7", known_code=known_code, providers=providers, timeout=3.0
    )


def test_majority_of_two_overrides_known_opinion() -> None:
    # ip-api already said HK (stale), but ipwho.is + ipinfo.io both say SE.
    result = _resolve(("Sweden", "SE"), (None, "SE"), known_code="HK")
    assert result == ("Sweden", "SE")


def test_no_consensus_keeps_known_opinion() -> None:
    # One disagreeing source is not enough to override the primary lookup.
    result = _resolve((None, "SE"), (None, None), known_code="HK")
    assert result == (None, "HK")


def test_no_known_code_uses_consensus_when_two_agree() -> None:
    result = _resolve((None, "SE"), (None, "SE"), (None, "IN"))
    assert result == (None, "SE")


def test_no_known_code_no_consensus_takes_first_opinion() -> None:
    result = _resolve((None, "UK"), (None, None), (None, "IN"))
    assert result == (None, "UK")


def test_all_sources_silent_returns_none() -> None:
    assert _resolve((None, None), (None, None), known_code=None) == (None, None)


def test_failing_source_is_skipped_not_fatal() -> None:
    class Boom(StubGeo):
        def lookup(self, ip, timeout, transport):
            raise RuntimeError("down")

    providers = [Boom("boom", (None, None)), StubGeo("ok", (None, "SE"))]
    result = ip_prov.resolve_country_consensus(
        "203.0.113.7",
        known_code="HK",
        providers=providers,
        timeout=3.0,
    )
    assert result == (None, "HK")