"""Proxy collection: download -> parse -> normalize -> deduplicate.

The collector streams source lines lazily, stamps each source, normalizes and
deduplicates candidates, and reports per-source statistics. It never keeps the
full raw text of a list in memory; the only deduplication structure is a set of
``(protocol, host, port)`` keys, plus the final candidate list.
"""

from __future__ import annotations

from typing import Iterable

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.models.proxy_entry import ProxyBatch, ProxyEntry, SourceStatistics
from app.infrastructure.proxy.proxy_parser import parse_line, stamp_source
from app.infrastructure.proxy.proxy_source import ProxySource


class ProxyCollector:
    def __init__(self, sources: list[ProxySource]) -> None:
        self._sources = sources

    @property
    def sources(self) -> list[ProxySource]:
        return list(self._sources)

    def collect(
        self,
        existing_keys: set[tuple[str, str, int]] | None = None,
        default_protocols: dict[str, ProxyProtocol | None] | None = None,
        timeout: float | None = None,
    ) -> ProxyBatch:
        """Download and normalize every configured source.

        ``existing_keys`` pre-seeds the dedup set with keys already stored in
        the database so already-known endpoints are not re-inserted.
        """
        seen: set[tuple[str, str, int]] = set(existing_keys or ())
        entries: list[ProxyEntry] = []
        stats: list[SourceStatistics] = []

        protocols = default_protocols or {}
        for source in self._sources:
            stat, batch = self._collect_source(
                source,
                seen=seen,
                default_protocol=protocols.get(source.name),
                timeout=timeout,
            )
            stats.append(stat)
            entries.extend(batch)
        return ProxyBatch(entries=entries, source_stats=stats)

    def _collect_source(
        self,
        source: ProxySource,
        *,
        seen: set[tuple[str, str, int]],
        default_protocol: ProxyProtocol | None = None,
        timeout: float | None = None,
    ) -> tuple[SourceStatistics, list[ProxyEntry]]:
        default_protocol = default_protocol or source.protocol
        lines = 0
        found = 0
        batch: list[ProxyEntry] = []
        try:
            iterator = source.fetch(timeout=timeout)
            path_protocol = source.protocol or default_protocol
            for raw_line in iterator:
                lines += 1
                entry = self._parse_source_line(
                    raw_line, source.name, path_protocol
                )
                if entry is None:
                    continue
                key = entry.dedupe_key()
                if key in seen:
                    continue
                seen.add(key)
                batch.append(entry)
                found += 1
            return (
                SourceStatistics(
                    name=source.name, fetched=True, lines=lines, found=found
                ),
                batch,
            )
        except Exception as exc:
            return (
                SourceStatistics(
                    name=source.name,
                    fetched=False,
                    lines=lines,
                    found=found,
                    error=str(exc),
                ),
                batch,
            )

    @staticmethod
    def _parse_source_line(
        line: str, source_name: str, default_protocol: ProxyProtocol | None
    ) -> ProxyEntry | None:
        entry = parse_line(line, default_protocol=default_protocol)
        if entry is None:
            return None
        return stamp_source(entry, source_name)


def filter_new_entries(
    entries: Iterable[ProxyEntry], existing_keys: set[tuple[str, str, int]]
) -> list[ProxyEntry]:
    """Return entries not present in ``existing_keys`` (pure helper)."""
    output: list[ProxyEntry] = []
    for entry in entries:
        if entry.dedupe_key() not in existing_keys:
            output.append(entry)
    return output