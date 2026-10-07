"""Country label consensus: no single geo database decides on its own."""

from __future__ import annotations

from antidetect.infrastructure.proxy import ip_providers as ip_prov


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


def test_slow_provider_does_not_stall_consensus() -> None:
    """A hanging database is abandoned at the shared deadline; fast votes win.

    Sequential code would block ~5s on the slow provider; parallel code
    finishes at the deadline with the fast provider's opinion.
    """
    import time

    class SlowAgree(StubGeo):
        def lookup(self, ip, timeout, transport):
            time.sleep(5.0)
            return ("Sweden", "SE")

    started = time.monotonic()
    result = ip_prov.resolve_country_consensus(
        "203.0.113.7",
        providers=[SlowAgree("slow", None), StubGeo("fast", ("Sweden", "SE"))],
        timeout=1.0,
    )
    elapsed = time.monotonic() - started
    assert result == ("Sweden", "SE")
    assert elapsed < 2.0


def test_direct_ip_takes_first_valid_not_first_finished() -> None:
    """Parallel race: a slow ip-api answer must lose to a fast ipify one.

    Sequential code always prefers ip-api (tried first); parallel code takes
    whichever valid answer arrives first.
    """
    import time

    from antidetect.infrastructure.proxy.transport import HttpReply

    class RoutingTransport:
        def __init__(self, routes) -> None:
            self._routes = routes

        def get(self, url, timeout):
            for substring, delay, outcome in self._routes:
                if substring in url:
                    if delay:
                        time.sleep(delay)
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome
            raise AssertionError(f"unexpected url {url}")

    def _reply(body: str):
        return HttpReply(status=200, headers={}, body=body)

    transport = RoutingTransport(
        [
            ("ip-api.com", 0.5, _reply('{"status":"success","query":"1.1.1.1"}')),
            ("api.ipify.org", 0.05, _reply("5.6.7.8\n")),
            ("42.pl", 0.0, RuntimeError("down")),
        ]
    )
    started = time.monotonic()
    assert ip_prov.fetch_direct_ip(timeout=5.0, transport=transport) == "5.6.7.8"
    assert time.monotonic() - started < 1.0


def test_direct_ip_none_when_everything_fails() -> None:
    class DeadTransport:
        def get(self, url, timeout):
            raise RuntimeError("offline")

    assert ip_prov.fetch_direct_ip(timeout=1.0, transport=DeadTransport()) is None