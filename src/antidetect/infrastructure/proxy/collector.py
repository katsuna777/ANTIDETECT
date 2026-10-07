"""Proxy collection: download -> parse -> normalize -> deduplicate.

The collector downloads the sources side by side (the defaults are ~45 lists, which one after the
other took half a minute), parses each list on its own thread, then deduplicates in *source order*
so the result is the same as a sequential run. A ``stop_event`` is honoured at once: the downloads
run on daemon threads that are simply abandoned (they end by themselves at the next line or
socket timeout), so a stop never waits for a slow server and never keeps the process alive.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import replace

from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.models.proxy_entry import ProxyBatch, ProxyEntry, SourceStatistics
from antidetect.infrastructure.proxy.proxy_parser import parse_line, stamp_source
from antidetect.infrastructure.proxy.proxy_source import ProxySource

_DOWNLOAD_THREADS = 8
_STOP_POLL_S = 0.05
_STOP_CHECK_EVERY = 256        # lines between looks at the stop event while a list is being read


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
        stop_event: threading.Event | None = None,
    ) -> ProxyBatch:
        """Download and normalize every configured source.

        ``existing_keys`` pre-seeds the dedup set with keys already stored in
        the database so already-known endpoints are not re-inserted. When ``stop_event`` is set
        the lists that were not finished are left out.
        """
        seen: set[tuple[str, str, int]] = set(existing_keys or ())
        protocols = default_protocols or {}
        fetched = self._download_all(protocols, timeout, stop_event)

        entries: list[ProxyEntry] = []
        stats: list[SourceStatistics] = []
        for source, result in zip(self._sources, fetched):
            if result is None:                       # stopped before this list was done
                continue
            stat, parsed = result
            batch: list[ProxyEntry] = []
            for entry in parsed:
                key = entry.dedupe_key()
                if key in seen:
                    continue
                seen.add(key)
                batch.append(entry)
            stats.append(replace(stat, found=len(batch)))
            entries.extend(batch)
        return ProxyBatch(entries=entries, source_stats=stats)

    # ------------------------------------------------------------------ download

    def _download_all(
        self,
        protocols: dict[str, ProxyProtocol | None],
        timeout: float | None,
        stop_event: threading.Event | None,
    ) -> list[tuple[SourceStatistics, list[ProxyEntry]] | None]:
        total = len(self._sources)
        results: list[tuple[SourceStatistics, list[ProxyEntry]] | None] = [None] * total
        if total == 0:
            return results
        todo: queue.Queue[int] = queue.Queue()
        for index in range(total):
            todo.put(index)
        finished: queue.Queue[int] = queue.Queue()

        def stopping() -> bool:
            return stop_event is not None and stop_event.is_set()

        def work() -> None:
            while not stopping():
                try:
                    index = todo.get_nowait()
                except queue.Empty:
                    return
                source = self._sources[index]
                results[index] = self._collect_source(
                    source, default_protocol=protocols.get(source.name), timeout=timeout, stopping=stopping
                )
                finished.put(index)

        for number in range(min(_DOWNLOAD_THREADS, total)):
            threading.Thread(target=work, name=f"proxy-source-{number}", daemon=True).start()

        done = 0
        while done < total and not stopping():
            try:
                finished.get(timeout=_STOP_POLL_S)
            except queue.Empty:
                continue
            done += 1
        if stopping():
            # a list that was cut off half-way is not "fetched": keep only the complete ones
            return [result if result is not None and result[0].fetched is not None else None for result in results]
        return results

    def _collect_source(
        self,
        source: ProxySource,
        *,
        default_protocol: ProxyProtocol | None = None,
        timeout: float | None = None,
        stopping=lambda: False,
    ) -> tuple[SourceStatistics, list[ProxyEntry]]:
        default_protocol = default_protocol or source.protocol
        lines = 0
        batch: list[ProxyEntry] = []
        try:
            iterator = source.fetch(timeout=timeout)
            path_protocol = source.protocol or default_protocol
            for raw_line in iterator:
                lines += 1
                if lines % _STOP_CHECK_EVERY == 0 and stopping():
                    break
                entry = self._parse_source_line(raw_line, source.name, path_protocol)
                if entry is not None:
                    batch.append(entry)
            return SourceStatistics(name=source.name, fetched=True, lines=lines, found=len(batch)), batch
        except Exception as exc:
            return (
                SourceStatistics(name=source.name, fetched=False, lines=lines, found=len(batch), error=str(exc)),
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
