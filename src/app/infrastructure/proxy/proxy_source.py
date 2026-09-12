"""Source abstraction for the proxy collector.

A :class:`ProxySource` streams raw lines of a public proxy list. New sources
(single GitHub raw files, aggregator APIs, exported text lists, ...) can be
added by subclassing without touching the collector or the rest of the
pipeline. ``fetch`` yields lines lazily so an entire large list is never kept
in memory at once.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.errors import ProxySourceError


class ProxySource(ABC):
    """Abstract contract every source must satisfy."""

    name: str = "unnamed"
    protocol: Optional[ProxyProtocol] = None

    @abstractmethod
    def fetch(self, timeout: float | None = None) -> Iterable[str]:
        """Yield raw, unparsed lines of the proxy list.

        Must raise :class:`app.domain.errors.ProxySourceError` when the source
        cannot be reached or read, so the collector records per-source failure
        instead of aborting the whole refresh.
        """
        raise NotImplementedError


class TextProxySource(ProxySource):
    """In-memory source over a preloaded string or an iterable of lines.

    Used by tests and prototypes; also useful for piping data exported by an
    external process.
    """

    def __init__(
        self,
        name: str = "text",
        lines: Iterable[str] = (),
        protocol: ProxyProtocol | None = None,
    ) -> None:
        self.name = name
        self._lines = lines
        self.protocol = protocol

    def fetch(self, timeout: float | None = None) -> Iterable[str]:
        yield from self._lines