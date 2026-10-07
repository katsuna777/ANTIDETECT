"""Business operations over proxies.

Orchestrates the collector, checker and repositories. Owns the status
state-machine, the resilient dead-proxy policy and the staleness rules used by
``refresh``. Knows nothing about SQLite, sockets or the CLI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

from antidetect.application.ports import ProxyCheckRepository, ProxyRepository
from antidetect.domain.enums.proxy_status import Anonymity, ProxyProtocol, ProxyStatus
from antidetect.domain.errors import ProxyNotFoundError
from antidetect.domain.models.proxy import Proxy, ProxyWithCheck
from antidetect.domain.models.proxy_check import ProxyCheck
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.proxy.checker import CheckOutcome, ProxyChecker
from antidetect.infrastructure.proxy.collector import ProxyCollector
from antidetect.infrastructure.proxy.proxy_parser import parse_line, stamp_source

if TYPE_CHECKING:
    from antidetect.application.ports import ActivitySink, LogSink

#: Proxies the user typed or pasted themselves. They are never purged by the
#: automatic dead-proxy cleanup (that is meant for the collected free pool).
MANUAL_SOURCE = "manual"

#: Id carried by a collected free proxy while it is being checked. Such a candidate is not a
#: database row yet: it only becomes one if it passes (see ``_PassedSink``).
CANDIDATE_ID = 0
_STORE_BATCH = 25         # write once this many passed...
_STORE_INTERVAL_S = 1.5   # ...or once the oldest waiting one has waited this long

DEAD_POLICY_DISABLE = "disable"
DEAD_POLICY_DELETE = "delete"
_VALID_DEAD_POLICIES = (DEAD_POLICY_DISABLE, DEAD_POLICY_DELETE)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RefreshSummary:
    collected: int
    created: int
    checked: int
    working: int
    failed: int
    dead: int
    removed: int
    source_errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass(frozen=True)
class ImportSummary:
    added: int
    existing: int
    invalid: list[str] = field(default_factory=list)
    ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class CheckBatchSummary:
    checked: int
    working: int
    failed: int
    dead: int
    removed: int = 0
    elapsed_seconds: float = 0.0


class ProxyService:
    def __init__(
        self,
        proxies: ProxyRepository,
        checks: ProxyCheckRepository,
        collector: ProxyCollector,
        checker: ProxyChecker,
        dead_policy: str = DEAD_POLICY_DISABLE,
        max_failures: int = 3,
        log_sink: "LogSink | None" = None,
        activity: "ActivitySink | None" = None,
    ) -> None:
        self._activity = activity
        self._proxies = proxies
        self._checks = checks
        self._collector = collector
        self._checker = checker
        if dead_policy not in _VALID_DEAD_POLICIES:
            raise ValueError(f"Unknown dead policy: {dead_policy!r}")
        self._dead_policy = dead_policy
        self._max_failures = max(1, max_failures)
        self._log = log_sink

    # ---------------------------------------------------------------- reads

    def get_proxy(self, proxy_id: int) -> Proxy:
        proxy = self._proxies.get(proxy_id)
        if proxy is None:
            raise ProxyNotFoundError(proxy_id)
        return proxy

    def list_proxies(
        self,
        *,
        status: str | None = None,
        sort: str = "latency",
        reverse: bool = False,
        limit: int | None = None,
        ids: list[int] | None = None,
    ) -> list[ProxyWithCheck]:
        """Proxies with their latest check; ``ids`` narrows the query (``[]`` means none)."""
        if ids is not None and not ids:
            return []
        parsed_status: ProxyStatus | None = None
        if status:
            parsed_status = ProxyStatus.from_string(status.upper())
        rows = self._proxies.list_with_latest_check(status=parsed_status, limit=None, proxy_ids=ids)
        rows = self._sort_rows(rows, sort)
        if reverse:
            rows = list(reversed(rows))
        if limit is not None and limit >= 0:
            rows = rows[:limit]
        return rows

    # --------------------------------------------------------------- checks

    def check_proxy(self, proxy_id: int) -> tuple[Proxy, ProxyCheck]:
        """Check a single proxy and persist both the check and its outcome."""
        proxy = self.get_proxy(proxy_id)
        outcome = self._checker.check_one(proxy)
        self.apply_outcomes([outcome])
        check = self._checks.latest_for(proxy_id)
        self._log_outcomes([outcome])
        return proxy, check  # type: ignore[return-value]

    def check_all(
        self,
        workers: int | None = None,
        timeout: float | None = None,
        force: bool = True,
        stale_minutes: int = 60,
        on_progress: Callable[[int, int], None] | None = None,
        on_proxy: Callable[[object], None] | None = None,
        stop_event=None,
        purge_failed: bool = False,
        ids: list[int] | None = None,
    ) -> CheckBatchSummary:
        """Check every stored proxy, or only ``ids`` (concurrently either way)."""
        started = utcnow()
        if ids is None:
            proxies = self._targets(force=force, stale_minutes=stale_minutes)
        else:
            proxies = [p for p in (self._proxies.get(i) for i in ids) if p is not None]
        outcomes = self._checker.check_all(
            proxies,
            workers=workers,
            timeout=timeout,
            on_progress=on_progress,
            on_proxy=on_proxy,
            stop_event=stop_event,
        )
        self.apply_outcomes(outcomes)
        dead = sum(1 for o in outcomes if o.proxy.status is not None and self._is_dead_after(o))
        removed = self._cleanup(outcomes, purge_failed=purge_failed)
        self._log_outcomes(outcomes)
        summary = CheckBatchSummary(
            checked=len(outcomes),
            working=sum(1 for o in outcomes if o.ok),
            failed=sum(1 for o in outcomes if not o.ok),
            dead=dead,
            removed=removed,
            elapsed_seconds=(utcnow() - started).total_seconds(),
        )
        self._log_batch_summary(summary)
        if summary.checked > 1:       # one proxy re-checked from a row is not an event
            self._report("act.proxy.checked", checked=summary.checked, working=summary.working, failed=summary.failed)
        return summary

    def refresh(
        self,
        *,
        timeout: float | None = None,
        workers: int | None = None,
        max_failures: int | None = None,
        stale_minutes: int | None = None,
        collect: bool = True,
        force: bool = False,
        reset: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
        on_proxy: Callable[[object], None] | None = None,
        stop_event=None,
        purge_failed: bool = False,
    ) -> RefreshSummary:
        """collect -> parse -> normalize -> dedupe -> check -> store the passing -> cleanup.

        Collected proxies are *candidates*, not rows: only those that pass the check are
        written, so nothing unchecked ever sits in the table (stopping a run midway keeps
        exactly what was verified so far).

        ``collect=False`` skips downloading new sources and only re-checks the
        database (equivalent to ``check-all`` but honouring staleness).

        ``reset=True`` forgets the whole pool first (deletes every row) before
        collecting again, so the database ends up containing only what the new
        run produced and validated.

        ``purge_failed=True`` deletes every proxy that failed this run instead
        of keeping it around for the next resilience cycle, so the working list
        reflects the latest check exactly (used by the GUI).
        """
        started = utcnow()
        if max_failures is not None:
            self._max_failures = max(1, max_failures)

        collected = 0
        candidates: list[Proxy] = []
        source_errors: list[str] = []
        if collect:
            if reset:
                self._proxies.delete_all()
            existing = self._proxies.keys()
            batch = self._collector.collect(
                existing_keys=existing, timeout=timeout, stop_event=stop_event
            )
            collected = batch.new_entries
            candidates = [_candidate(entry) for entry in batch.entries]
            source_errors = [
                f"{stat.name}: {stat.error}"
                for stat in batch.source_stats
                if not stat.fetched
            ]

        stored = self._targets(
            force=force, stale_minutes=stale_minutes or 60
        )
        # Collected proxies are checked straight from memory and written only once they pass:
        # whatever was not checked (a stopped run, a closed app) or failed never reaches the
        # database, so the table holds nothing but verified proxies.
        sink = _PassedSink(self)

        def on_outcome(outcome: CheckOutcome) -> None:
            if outcome.proxy.id == CANDIDATE_ID and outcome.ok:
                sink.add(outcome)
            else:
                sink.tick()
            if on_proxy is not None:
                on_proxy(outcome)

        try:
            outcomes = self._checker.check_all(
                stored + candidates,
                workers=workers,
                timeout=timeout,
                on_progress=on_progress,
                on_proxy=on_outcome,
                stop_event=stop_event,
            )
        finally:
            sink.flush()
        # A checker that does not stream results still reports them all at the end.
        sink.add_all(o for o in outcomes if o.proxy.id == CANDIDATE_ID and o.ok)
        sink.flush()

        known = [o for o in outcomes if o.proxy.id != CANDIDATE_ID]
        self.apply_outcomes(known)
        removed = self._cleanup(known, purge_failed=purge_failed)
        self._log_outcomes(known + [o for o in outcomes if o.proxy.id == CANDIDATE_ID and o.ok])
        summary = RefreshSummary(
            collected=collected,
            created=sink.created,
            checked=len(outcomes),
            working=sum(1 for o in outcomes if o.ok),
            failed=sum(1 for o in outcomes if not o.ok),
            dead=sum(1 for o in known if self._is_dead_after(o)),
            removed=removed,
            source_errors=source_errors,
            elapsed_seconds=(utcnow() - started).total_seconds(),
        )
        self._log_refresh_summary(summary)
        self._report("act.proxy.refreshed", collected=summary.collected, added=summary.created, working=summary.working)
        return summary

    def remove_dead(self) -> int:
        return self._proxies.delete_dead()

    def delete_proxies(self, proxy_ids: list[int]) -> int:
        """Delete the given proxies (profiles using them lose the proxy)."""
        removed = self._proxies.delete_many(list(proxy_ids))
        if removed:
            self._report("act.proxy.deleted", count=removed)
        return removed

    def import_text(
        self, text: str, default_protocol: ProxyProtocol | None = None
    ) -> ImportSummary:
        """Add the user's own proxies from pasted text (one per line).

        Accepts ``host:port``, ``host:port:user:pass``, ``user:pass@host:port``
        and scheme-prefixed forms. Lines that cannot be parsed are returned in
        ``invalid`` instead of aborting the batch.
        """
        entries = []
        invalid: list[str] = []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            entry = parse_line(line, default_protocol)
            if entry is None:
                invalid.append(line[:80])
            else:
                entries.append(stamp_source(entry, MANUAL_SOURCE))
        if not entries:
            return ImportSummary(added=0, existing=0, invalid=invalid)
        wanted = list(dict.fromkeys(entry.dedupe_key() for entry in entries))
        known = self._proxies.ids_for_keys(wanted)
        added = self._proxies.upsert_many(entries)
        found = self._proxies.ids_for_keys(wanted)
        ids = [found[key] for key in wanted if key in found]
        existing = sum(1 for entry in entries if entry.dedupe_key() in known)
        if self._log is not None:
            self._log.info(
                "proxies",
                f"Imported {len(entries)} proxies: {added} new, {existing} already known, "
                f"{len(invalid)} unreadable",
                {"added": added, "existing": existing, "invalid": len(invalid)},
            )
        self._report("act.proxy.imported", added=added, existing=existing, invalid=len(invalid))
        return ImportSummary(added=added, existing=existing, invalid=invalid, ids=ids)

    # ----------------------------------------------------------- persistence

    def apply_outcomes(self, outcomes: list[CheckOutcome]) -> None:
        if not outcomes:
            return
        now = utcnow()
        check_rows: list[ProxyCheck] = []
        proxy_updates: list[tuple[int, ProxyStatus, int, datetime]] = []
        for outcome in outcomes:
            proxy = outcome.proxy
            if outcome.ok:
                status = ProxyStatus.WORKING
                failures = 0
            else:
                failures = proxy.consecutive_failures + 1
                status = ProxyStatus.DEAD if failures >= self._max_failures else (
                    proxy.status if proxy.status is ProxyStatus.WORKING
                    else ProxyStatus.UNKNOWN
                )
            check_rows.append(
                self._make_check(proxy.id, now, outcome, status)
            )
            proxy_updates.append((proxy.id, status, failures, now))
        self._checks.insert_many(check_rows)
        self._proxies.apply_outcomes(proxy_updates)

    @staticmethod
    def _make_check(
        proxy_id: int, now: datetime, outcome: CheckOutcome, status: ProxyStatus,
    ) -> ProxyCheck:
        return ProxyCheck(
            id=0,
            proxy_id=proxy_id,
            checked_at=now,
            status=ProxyStatus.WORKING if outcome.ok else (
                status if status is ProxyStatus.DEAD else ProxyStatus.ERROR
            ),
            latency_ms=outcome.latency_ms,
            external_ip=outcome.external_ip,
            country=outcome.country,
            country_code=outcome.country_code,
            anonymity=outcome.anonymity or Anonymity.UNKNOWN,
            error=outcome.error,
        )

    # --------------------------------------------------------------- helpers

    def _store_passed(self, outcomes: list[CheckOutcome]) -> int:
        """Persist candidates that passed the check, each with its check result.

        Returns how many rows were new (a candidate already known from another list is only
        refreshed).
        """
        if not outcomes:
            return 0
        entries = [
            ProxyEntry(
                protocol=o.proxy.protocol, host=o.proxy.host, port=o.proxy.port,
                username=o.proxy.username, password=o.proxy.password, source=o.proxy.source,
            )
            for o in outcomes
        ]
        created = self._proxies.upsert_many(entries)
        ids = self._proxies.ids_for_keys([entry.dedupe_key() for entry in entries])
        self.apply_outcomes([
            replace(o, proxy=o.proxy.replace(id=ids[entry.dedupe_key()]))
            for o, entry in zip(outcomes, entries)
            if entry.dedupe_key() in ids
        ])
        return created

    def _targets(self, *, force: bool, stale_minutes: int) -> list[Proxy]:
        if force:
            return self._proxies.list()
        stale_before = utcnow() - timedelta(minutes=max(0, stale_minutes))
        return self._proxies.list_for_check(stale_before=stale_before)

    def _is_dead_after(self, outcome: CheckOutcome) -> bool:
        return (
            not outcome.ok
            and outcome.proxy.consecutive_failures + 1 >= self._max_failures
        )

    def _cleanup(self, outcomes: list[CheckOutcome], *, purge_failed: bool) -> int:
        if purge_failed:
            return self._purge_failed(outcomes)
        return self._apply_dead_policy()

    def _purge_failed(self, outcomes: list[CheckOutcome]) -> int:
        """Delete every proxy that failed in this run.

        The pool is re-collected on every fresh check, so a proxy that failed
        now has no value sitting in the database: removing it keeps the stored
        working list identical to what the GUI just validated.
        """
        failed_ids = [
            o.proxy.id for o in outcomes
            if o.proxy.id != CANDIDATE_ID and not o.ok and (o.proxy.source or "") != MANUAL_SOURCE
        ]
        if not failed_ids:
            return 0
        return self._proxies.delete_many(failed_ids)

    def _apply_dead_policy(self) -> int:
        if self._dead_policy != DEAD_POLICY_DELETE:
            return 0
        return self._proxies.delete_dead()

    # --------------------------------------------------------------- logging

    def _log_outcomes(self, outcomes: list[CheckOutcome]) -> None:
        if self._log is None:
            return
        for outcome in outcomes:
            proxy = outcome.proxy
            label = f"{proxy.protocol.value}://{proxy.host}:{proxy.port}"
            if outcome.ok:
                details = f"latency={outcome.latency_ms}ms ip={outcome.external_ip}"
                if outcome.country_code:
                    details += f" country={outcome.country_code}"
                self._log.info("proxy", f"Proxy {label} WORKING — {details}")
            else:
                dead = self._is_dead_after(outcome)
                message = f"Proxy {label} failed: {outcome.error or 'unknown error'}"
                if dead:
                    self._log.error("proxy", message)
                else:
                    self._log.warn("proxy", message)

    def _report(self, kind: str, **data) -> None:
        if self._activity is not None:
            self._activity.record(kind, "", **data)

    def _log_batch_summary(self, summary: CheckBatchSummary) -> None:
        if self._log is None:
            return
        self._log.info(
            "proxy",
            "Proxy check finished",
            extra={
                "checked": summary.checked,
                "working": summary.working,
                "failed": summary.failed,
                "dead": summary.dead,
                "removed": summary.removed,
                "elapsed_seconds": round(summary.elapsed_seconds, 2),
            },
        )

    def _log_refresh_summary(self, summary: RefreshSummary) -> None:
        if self._log is None:
            return
        extra = {
            "collected": summary.collected,
            "created": summary.created,
            "checked": summary.checked,
            "working": summary.working,
            "failed": summary.failed,
            "dead": summary.dead,
            "removed": summary.removed,
            "elapsed_seconds": round(summary.elapsed_seconds, 2),
        }
        if summary.source_errors:
            extra["source_errors"] = summary.source_errors
        self._log.info("proxy", "Proxy refresh finished", extra=extra)

    @staticmethod
    def _sort_rows(
        rows: list[ProxyWithCheck], sort: str
    ) -> list[ProxyWithCheck]:
        def latency_key(row: ProxyWithCheck) -> tuple[int, int]:
            never = 10 ** 9
            working = 0 if row.proxy.status is ProxyStatus.WORKING else 1
            latency = row.latency_ms if row.latency_ms is not None else never
            return (working, latency)

        if sort == "latency":
            rows = sorted(rows, key=latency_key)
        elif sort == "id":
            rows = sorted(rows, key=lambda r: r.id)
        elif sort == "status":
            rows = sorted(rows, key=lambda r: r.proxy.status.value)
        elif sort == "country":
            rows = sorted(
                rows,
                key=lambda r: (r.country_code or r.country or "").lower(),
            )
        else:
            raise ValueError(
                "Unknown sort; expected one of: latency, id, status, country"
            )
        return rows


def _candidate(entry: ProxyEntry) -> Proxy:
    """A collected proxy as the checker sees it: a proxy with no database row yet."""
    return Proxy(
        id=CANDIDATE_ID, protocol=entry.protocol, host=entry.host, port=entry.port,
        username=entry.username, password=entry.password, source=entry.source,
    )


class _PassedSink:
    """Writes passing candidates in small batches while a check is still running.

    Small batches keep the write cost low and mean an aborted run loses at most the last few
    results instead of everything it verified; the time limit also lets a table that is open
    on screen fill in as proxies pass, even when passes are rare (a free list passes ~5%).
    """

    def __init__(self, service: ProxyService) -> None:
        self._service = service
        self._pending: list[CheckOutcome] = []
        self._seen: set[tuple[str, str, int]] = set()
        self._since = time.monotonic()
        self.created = 0

    def add(self, outcome: CheckOutcome) -> None:
        key = outcome.proxy.dedupe_key()
        if key in self._seen:
            return
        self._seen.add(key)
        if not self._pending:
            self._since = time.monotonic()
        self._pending.append(outcome)
        if len(self._pending) >= _STORE_BATCH:
            self.flush()
        else:
            self.tick()

    def add_all(self, outcomes) -> None:
        for outcome in outcomes:
            self.add(outcome)

    def tick(self) -> None:
        """Write what is waiting if it has waited long enough (called after every result)."""
        if self._pending and time.monotonic() - self._since >= _STORE_INTERVAL_S:
            self.flush()

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        self.created += self._service._store_passed(pending)
