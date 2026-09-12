"""Business operations over proxies.

Orchestrates the collector, checker and repositories. Owns the status
state-machine, the resilient dead-proxy policy and the staleness rules used by
``refresh``. Knows nothing about SQLite, sockets or the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

from app.application.ports import ProxyCheckRepository, ProxyRepository
from app.domain.enums.proxy_status import Anonymity, ProxyStatus
from app.domain.errors import ProxyNotFoundError
from app.domain.models.proxy import Proxy, ProxyWithCheck
from app.domain.models.proxy_check import ProxyCheck
from app.infrastructure.proxy.checker import CheckOutcome, ProxyChecker
from app.infrastructure.proxy.collector import ProxyCollector

if TYPE_CHECKING:
    from app.application.ports import LogSink

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
    ) -> None:
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
    ) -> list[ProxyWithCheck]:
        parsed_status: ProxyStatus | None = None
        if status:
            parsed_status = ProxyStatus.from_string(status.upper())
        rows = self._proxies.list_with_latest_check(status=parsed_status, limit=None)
        rows = self._sort_rows(rows, sort)
        if reverse:
            rows = list(reversed(rows))
        if limit is not None and limit >= 0:
            rows = rows[:limit]
        return rows

    # --------------------------------------------------------------- checks

    def lookup_ip(self) -> str | None:
        """Resolve the machine's current public IP through the proxy pipeline.

        The indirect IP provider performs network I/O on first resolution, so
        GUI callers must run this on a background worker, never on the UI
        thread. ``None`` means the resolver failed (e.g. offline).
        """
        self._checker.ensure_direct_ip()
        return self._checker.direct_ip

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
    ) -> CheckBatchSummary:
        started = utcnow()
        proxies = self._targets(force=force, stale_minutes=stale_minutes)
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
        """collect -> parse -> normalize -> dedupe -> check -> update -> cleanup.

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

        created = 0
        collected = 0
        source_errors: list[str] = []
        if collect:
            if reset:
                self._proxies.delete_all()
            existing = self._proxies.keys()
            batch = self._collector.collect(
                existing_keys=existing, timeout=timeout
            )
            collected = batch.new_entries
            created = self._proxies.upsert_many(batch.entries)
            source_errors = [
                f"{stat.name}: {stat.error}"
                for stat in batch.source_stats
                if not stat.fetched
            ]

        proxies = self._targets(
            force=force, stale_minutes=stale_minutes or 60
        )
        outcomes = self._checker.check_all(
            proxies,
            workers=workers,
            timeout=timeout,
            on_progress=on_progress,
            on_proxy=on_proxy,
            stop_event=stop_event,
        )
        self.apply_outcomes(outcomes)

        removed = self._cleanup(outcomes, purge_failed=purge_failed)
        self._log_outcomes(outcomes)
        summary = RefreshSummary(
            collected=collected,
            created=created,
            checked=len(outcomes),
            working=sum(1 for o in outcomes if o.ok),
            failed=sum(1 for o in outcomes if not o.ok),
            dead=sum(1 for o in outcomes if self._is_dead_after(o)),
            removed=removed,
            source_errors=source_errors,
            elapsed_seconds=(utcnow() - started).total_seconds(),
        )
        self._log_refresh_summary(summary)
        return summary

    def remove_dead(self) -> int:
        return self._proxies.delete_dead()

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
        failed_ids = [o.proxy.id for o in outcomes if not o.ok]
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