"""Shared test doubles for the proxy pipeline (no real network)."""

from __future__ import annotations

import time
from typing import Callable

from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.models.proxy import Proxy
from antidetect.infrastructure.proxy.checker import CheckOutcome
from antidetect.infrastructure.proxy.ip_providers import IPProbeResult
from antidetect.infrastructure.proxy.proxy_source import ProxySource


class TextProxySource(ProxySource):
    """In-memory proxy source over a list of raw lines."""

    def __init__(self, name: str = "text", lines=(), protocol: ProxyProtocol | None = None) -> None:
        self.name = name
        self._lines = lines
        self.protocol = protocol

    def fetch(self, timeout: float | None = None):
        yield from self._lines


class FakeReply:
    def __init__(self, status=200, headers=None, body="") -> None:
        self.status = status
        self.headers = headers or {"content-type": "application/json"}
        self.body = body

    def header(self, key: str) -> str | None:
        for name, value in self.headers.items():
            if name.lower() == key.lower():
                return value
        return None


class FakeTransport:
    """Returns a fixed reply or raises on the configured behavior."""

    def __init__(self, reply=None, raise_error: Exception | None = None, delay: float = 0.0) -> None:
        self._reply = reply if reply is not None else FakeReply()
        self._raise_error = raise_error
        self._delay = delay
        self.calls: list[str] = []

    def get(self, url: str, timeout: float):
        self.calls.append(url)
        if self._delay:
            time.sleep(self._delay)
        if self._raise_error is not None:
            raise self._raise_error
        return self._reply


class StubProviders:
    """IP provider double; ``probe`` returns a fixed result via a callable.

    The transport is exercised first (like real providers), so transport-level
    failures propagate and are converted into failed checks by the checker.
    """

    name = "stub"

    def __init__(
        self,
        result_factory: Callable[[object, float], IPProbeResult | None]
        | None = None,
        result: IPProbeResult | None = None,
    ) -> None:
        self._factory = result_factory
        self._result = result

    def probe(self, transport, timeout: float) -> IPProbeResult | None:
        if self._factory is not None:
            return self._factory(transport, timeout)
        transport.get("http://stub.invalid/probe", timeout)
        return self._result


class StubProber:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self._headers = headers

    def probe(self, transport, timeout: float) -> dict[str, str] | None:
        return self._headers


class StubChecker:
    """Stand-in for ProxyChecker: returns caller-supplied outcomes."""

    def __init__(self, by_id: dict[int, object] | None = None) -> None:
        self._by_id = by_id or {}
        self.check_one_calls: list[Proxy] = []
        self.check_all_calls: list[Proxy] = []

    def check_one(self, proxy: Proxy, timeout: float | None = None):
        self.check_one_calls.append(proxy)
        return self._by_id.get(proxy.id, CheckOutcome(proxy=proxy, ok=True))

    def check_all(
        self,
        proxies,
        workers=None,
        timeout=None,
        on_progress=None,
        on_proxy=None,
        stop_event=None,
    ):
        self.check_all_calls.extend(proxies)
        results = [
            self._by_id.get(p.id, CheckOutcome(proxy=p, ok=True)) for p in proxies
        ]
        if on_proxy is not None and results:
            for outcome in results:
                on_proxy(outcome)
        if on_progress is not None and results:
            on_progress(len(results), len(results))
        return results


def make_proxy(
    pid: int, host: str = "1.2.3.4", port: int = 8080, status="UNKNOWN", **kw
) -> Proxy:
    from antidetect.domain.enums.proxy_status import ProxyProtocol, ProxyStatus

    return Proxy(
        id=pid,
        protocol=ProxyProtocol.HTTP,
        host=host,
        port=port,
        status=ProxyStatus.from_string(status),
        **kw,
    )


class RecordingLogSink:
    """Collects ``LogSink`` calls for assertions without a real repository.

    Also fulfils the optional ``tail_file`` method the Chromium manager checks
    for, so callers can verify tailing is requested without starting threads.
    """

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, str, dict | None]] = []
        self.tailed: list[tuple[str, str]] = []

    def log(self, level: str, source: str, message: str, extra: dict | None = None) -> None:
        self.entries.append((level, source, message, extra))

    def info(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log("INFO", source, message, extra)

    def warn(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log("WARN", source, message, extra)

    def error(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log("ERROR", source, message, extra)

    def debug(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log("DEBUG", source, message, extra)

    def tail_file(self, source: str, path: str) -> None:
        self.tailed.append((source, str(path)))

    @property
    def messages(self) -> list[str]:
        return [message for *_rest, message, _extra in self.entries]

    def by_source(self, source: str) -> list[tuple[str, str, str, dict | None]]:
        return [e for e in self.entries if e[1] == source]