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

from antidetect.domain.enums.proxy_status import ProxyProtocol


class ProxySource(ABC):
    """Abstract contract every source must satisfy."""

    name: str = "unnamed"
    protocol: Optional[ProxyProtocol] = None

    @abstractmethod
    def fetch(self, timeout: float | None = None) -> Iterable[str]:
        """Yield raw, unparsed lines of the proxy list.

        Must raise :class:`antidetect.domain.errors.ProxySourceError` when the source
        cannot be reached or read, so the collector records per-source failure
        instead of aborting the whole refresh.
        """
        raise NotImplementedError

