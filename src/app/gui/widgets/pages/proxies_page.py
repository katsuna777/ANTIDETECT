"""Proxies page: aggregate counts, IP lookup and long-running operations."""

from __future__ import annotations

import bisect
import threading
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton

from app.domain.enums.proxy_status import ProxyStatus
from app.gui import workers
from app.gui.dialogs.error_dialog import show_error
from app.gui.i18n import tr
from app.gui.utils.flags import country_label
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container
    from app.gui.workers.task_runner import TaskRunner

# 400 threads thrashed the frozen .app: GIL/context-switch overhead, DNS and
# socket pressure plus upstream rate limits turned into mass false failures
# ("skipped" proxies) while tens of thousands of per-proxy widget updates
# froze the UI. 64 network-bound workers saturate throughput without that.
_PROXY_CHECK_WORKERS = 64
_PROXY_CHECK_TIMEOUT = 5.0
# Live-list rows are inserted in chunks with repaint disabled: a single
# QListWidget.insertItem() relayouts the whole list, so per-proxy inserts
# degrade to O(n^2) on pools of thousands. Progress widgets are refreshed at
# most ~8 times per second; the final (done == total) update always applies.
_LIVE_FLUSH_CHUNK = 100
_PROGRESS_MIN_INTERVAL_S = 0.12


class ProxiesPage(PlaceholderPage):
    proxy_checked = Signal(object)

    def __init__(
        self, container: "Container", runner: "TaskRunner", parent=None
    ) -> None:
        super().__init__(tr("proxies.title"), kicker=tr("proxies.kicker"))
        self._container = container
        self._runner = runner

        self._total, self._working, self._dead = self.add_metrics(
            tr("metric.total"), tr("metric.working"), tr("metric.dead")
        )

        self._refresh = QPushButton(tr("proxies.refresh"))
        self._refresh.setObjectName("PrimaryButton")
        self._refresh.setToolTip(tr("proxies.refresh.tip"))
        self._lookup = QPushButton(tr("proxies.lookup"))
        self._lookup.setToolTip(tr("proxies.lookup.tip"))
        self._stop = QPushButton(tr("proxies.stop"))
        self._stop.setToolTip(tr("proxies.stop.tip"))
        self._stop.setEnabled(False)
        self.add_control_row(self._refresh, self._lookup, self._stop)
        self._hint = self.make_hint(tr("proxies.hint"))
        self.add_widget(self._hint)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress_label = QLabel("")
        self._progress_label.setObjectName("ResultLabel")
        self.add_control_row(self._progress, self._progress_label)
        self._progress.hide()
        self._progress_label.hide()

        self._live = QListWidget()
        self._live.setObjectName("LiveList")
        self.add_widget(self._live, 1)

        self._result = QLabel(tr("proxies.idle"))
        self._result.setWordWrap(True)
        self._result.setObjectName("ResultLabel")
        self.add_control_row(self._result)

        self._refresh.clicked.connect(self._run)
        self._lookup.clicked.connect(self._lookup_ip)
        self._stop.clicked.connect(self._stop_check)
        self.proxy_checked.connect(self._append_proxy)

        self._stop_event: threading.Event | None = None
        self._batch_total = 0
        self._live_working = 0
        self._live_dead = 0
        self._live_latencies: list[int] = []
        self._pending: list[tuple[int, object]] = []
        self._last_progress_ts = 0.0
        self._last_metrics_ts = 0.0
        self.reload()

    # ------------------------------------------------------------ retranslate

    def retranslate(self) -> None:
        self.set_title(tr("proxies.title"), tr("proxies.kicker"))
        self._total._label.setText(tr("metric.total"))
        self._working._label.setText(tr("metric.working"))
        self._dead._label.setText(tr("metric.dead"))
        self._refresh.setText(tr("proxies.refresh"))
        self._refresh.setToolTip(tr("proxies.refresh.tip"))
        self._lookup.setText(tr("proxies.lookup"))
        self._lookup.setToolTip(tr("proxies.lookup.tip"))
        self._stop.setText(tr("proxies.stop"))
        self._stop.setToolTip(tr("proxies.stop.tip"))
        self._hint.setText(tr("proxies.hint"))
        if self._result.text() in ("Idle.", "Готов."):
            self._result.setText(tr("proxies.idle"))

    # ------------------------------------------------------------ actions

    def reload(self) -> None:
        self._runner.submit(
            workers.tasks.summary(self._container),
            on_result=self._apply_summary,
            on_error=lambda exc: show_error(self, exc),
        )
        self._runner.submit(
            workers.tasks.list_proxies(self._container),
            on_result=self._apply_stored_proxies,
            on_error=lambda exc: show_error(self, exc),
        )

    def _run(self) -> None:
        import os

        from PySide6.QtWidgets import QMessageBox

        from app.gui.utils.preferences import Preferences

        prefs = Preferences(self._container.settings)
        headless = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        if not headless and prefs.get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, default=True):
            answer = QMessageBox.question(
                self,
                tr("proxies.refresh.dialog"),
                tr("proxies.refresh.question"),
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
        stop_event = threading.Event()
        self._stop_event = stop_event
        task = workers.tasks.refresh_proxies(
            self._container,
            collect=True,
            reset=True,
            workers=_PROXY_CHECK_WORKERS,
            timeout=_PROXY_CHECK_TIMEOUT,
            on_proxy=self.proxy_checked.emit,
            stop_event=stop_event,
        )

        self._refresh.setEnabled(False)
        self._lookup.setEnabled(False)
        self._stop.setEnabled(True)
        self._progress.setValue(0)
        self._progress.show()
        self._progress_label.setText("")
        self._progress_label.show()

        self._live.clear()
        self._live_working = 0
        self._live_dead = 0
        self._live_latencies: list[int] = []
        self._pending = []
        self._last_progress_ts = 0.0
        self._last_metrics_ts = 0.0
        self._batch_total = 0
        self._total.set_value(0)
        self._working.set_value(0)
        self._dead.set_value(0)

        self._runner.submit(
            task,
            on_progress=lambda done, total: self._show_progress(done, total),
            on_result=self._apply_check_summary,
            on_error=lambda exc: show_error(self, exc),
            on_finished=self._reset_busy,
        )

    def _stop_check(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
            self._stop.setEnabled(False)
            self._container.logs.info("proxy", tr("log.proxy.stopped"))
            self._result.setText(tr("proxies.stopping"))

    def _lookup_ip(self) -> None:
        self._lookup.setEnabled(False)
        self._result.setText(tr("proxies.resolving"))
        self._runner.submit(
            workers.tasks.lookup_ip(self._container),
            on_result=self._apply_lookup_ip,
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._lookup.setEnabled(True),
        )

    def _apply_lookup_ip(self, ip: object) -> None:
        if ip:
            self._container.logs.info("proxy", tr("log.proxy.resolved"), extra={"ip": str(ip)})
            self._result.setText(tr("proxies.public.ip", ip=ip))
        else:
            self._container.logs.warn("proxy", tr("log.proxy.unresolved"))
            self._result.setText(tr("proxies.public.fail"))

    # ------------------------------------------------------------ results

    def _apply_summary(self, summary: object) -> None:
        self._total.set_value(summary.proxies)
        self._working.set_value(summary.working_proxies)
        self._dead.set_value(summary.proxies - summary.working_proxies)

    def _show_progress(self, done: int, total: int) -> None:
        self._batch_total = total
        final = total and done >= total
        now = time.monotonic()
        if not final and now - self._last_progress_ts < _PROGRESS_MIN_INTERVAL_S:
            return
        self._last_progress_ts = now
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        pct = int(done * 100 / total) if total else 0
        self._progress_label.setText(f"{done} / {total} ({pct}%)")
        self._result.setText(tr("proxies.checked", done=done, total=total))
        self._refresh_live_metrics()

    def _refresh_live_metrics(self) -> None:
        total = self._batch_total or (self._live_working + self._live_dead)
        self._total.set_value(total)
        self._working.set_value(self._live_working)
        self._dead.set_value(self._live_dead)

    def _append_proxy(self, outcome: object) -> None:
        if not outcome.ok:
            self._live_dead += 1
            now = time.monotonic()
            if now - self._last_metrics_ts >= _PROGRESS_MIN_INTERVAL_S:
                self._last_metrics_ts = now
                self._refresh_live_metrics()
            return
        self._live_working += 1
        # Sequence number is stamped at arrival so rows keep the original
        # order semantics even though widgets are inserted in chunks.
        self._pending.append((self._live_working, outcome))
        if len(self._pending) >= _LIVE_FLUSH_CHUNK:
            self._flush_pending()

    def _flush_pending(self) -> None:
        if not self._pending:
            return
        pending, self._pending = self._pending, []
        self._live.setUpdatesEnabled(False)
        try:
            for seq, outcome in pending:
                proxy = outcome.proxy
                latency = outcome.latency_ms
                if latency is None:
                    latency = 10 ** 9
                idx = bisect.bisect_left(self._live_latencies, latency)
                self._live_latencies.insert(idx, latency)
                self._live.insertItem(
                    idx,
                    self._format_row(
                        seq,
                        proxy,
                        outcome.latency_ms,
                        outcome.country_code,
                        outcome.country,
                    ),
                )
        finally:
            self._live.setUpdatesEnabled(True)
        self._refresh_live_metrics()

    @staticmethod
    def _format_row(seq: int, proxy, latency_ms, country_code, country) -> str:
        latency_ms_str = f"{latency_ms}ms" if latency_ms is not None else "—"
        location = country_label(country_code, country)
        return (
            f"#{seq:04d} · {proxy.id:05d} · {proxy.host_port} · "
            f"{tr('proxies.row.working')} · {latency_ms_str} · {location}"
        )

    def _apply_stored_proxies(self, rows: object) -> None:
        if not self._refresh.isEnabled():
            return
        stored = list(rows or [])
        working = [
            row for row in stored
            if row.proxy.status is ProxyStatus.WORKING
        ]
        working.sort(
            key=lambda row: (
                row.latency_ms if row.latency_ms is not None else 10 ** 9
            )
        )
        self._live.clear()
        self._live_latencies = []
        self._live_working = 0
        self._live_dead = 0
        self._batch_total = 0
        self._pending = []
        self._live.setUpdatesEnabled(False)
        try:
            for row in working:
                self._live_working += 1
                latency = (
                    row.latency_ms if row.latency_ms is not None else 10 ** 9
                )
                idx = bisect.bisect_left(self._live_latencies, latency)
                self._live_latencies.insert(idx, latency)
                self._live.insertItem(
                    idx,
                    self._format_row(
                        self._live_working,
                        row.proxy,
                        row.latency_ms,
                        row.country_code,
                        row.country,
                    ),
                )
        finally:
            self._live.setUpdatesEnabled(True)
        self._total.set_value(len(stored))
        self._working.set_value(self._live_working)
        self._dead.set_value(len(stored) - self._live_working)

    def _apply_check_summary(self, summary: object) -> None:
        self._flush_pending()
        removed = getattr(summary, "removed", 0)
        stopped = self._stop_event is not None and self._stop_event.is_set()
        prefix = tr("proxies.summary.stopped") if stopped else tr("proxies.summary.checked")
        line = tr(
            "proxies.summary",
            prefix=prefix,
            checked=summary.checked,
            working=summary.working,
            failed=summary.failed,
            removed=removed,
        )
        collected = getattr(summary, "collected", None)
        if collected is not None:
            line += tr("proxies.summary.collected", n=collected)
        line += tr("proxies.summary.elapsed", s=summary.elapsed_seconds)
        source_errors = list(getattr(summary, "source_errors", None) or [])
        if source_errors:
            line += tr("proxies.summary.sources", errs="; ".join(source_errors))
        self._result.setText(line)
        self.reload()

    def _reset_busy(self) -> None:
        self._flush_pending()
        self._refresh.setEnabled(True)
        self._lookup.setEnabled(True)
        self._stop.setEnabled(False)
        self._stop_event = None
        self._progress.hide()
        self._progress_label.hide()
