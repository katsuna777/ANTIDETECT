"""Proxies page: aggregate counts, IP lookup and long-running operations.

``REFRESH POOL`` forgets every stored proxy and collects a brand-new pool from
the configured sources, then checks each one end-to-end and streams every
working proxy into the live list in real time (via a queued Qt signal, so no
widget is ever touched from a pool thread).
"""

from __future__ import annotations

import bisect
import threading
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QListWidget, QProgressBar, QPushButton

from app.domain.enums.proxy_status import ProxyStatus
from app.gui import workers
from app.gui.dialogs.error_dialog import show_error
from app.gui.utils.flags import country_label
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container
    from app.gui.workers.task_runner import TaskRunner

# Network callbacks are emitted on the checker's caller thread (a GUI worker),
# so they only enqueue Qt signals; the actual widget work happens on the GUI
# thread below. High concurrency is what keeps a 6000+ proxy pool fast.
_PROXY_CHECK_WORKERS = 400
_PROXY_CHECK_TIMEOUT = 5.0


class ProxiesPage(PlaceholderPage):
    proxy_checked = Signal(object)

    def __init__(
        self, container: "Container", runner: "TaskRunner", parent=None
    ) -> None:
        super().__init__("Proxies", kicker="SECTION 02")
        self._container = container
        self._runner = runner

        self._total, self._working, self._dead = self.add_metrics(
            "TOTAL", "WORKING", "DEAD"
        )

        self._refresh = QPushButton("REFRESH POOL")
        self._refresh.setObjectName("PrimaryButton")
        self._refresh.setToolTip("Wipe the pool and check a fresh one (destructive)")
        self._lookup = QPushButton("LOOKUP IP")
        self._lookup.setToolTip("Show the current public exit IP")
        self._stop = QPushButton("STOP")
        self._stop.setToolTip("Stop the running check")
        self._stop.setEnabled(False)
        self.add_control_row(self._refresh, self._lookup, self._stop)
        self.add_widget(
            self.make_hint("REFRESH POOL wipes stored proxies and re-checks them live. Dead ones are purged automatically.")
        )

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

        self._result = QLabel("Idle.")
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
        self.reload()

    # ------------------------------------------------------------ actions

    def reload(self) -> None:
        self._runner.submit(
            workers.tasks.summary(self._container),
            on_result=self._apply_summary,
            on_error=lambda exc: show_error(self, exc),
        )

    def _run(self) -> None:
        """REFRESH POOL: wipe the pool, collect a fresh one, check it live."""
        import os

        from PySide6.QtWidgets import QMessageBox

        from app.gui.utils.preferences import Preferences

        prefs = Preferences(self._container.settings)
        headless = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        if not headless and prefs.get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, default=True):
            answer = QMessageBox.question(
                self,
                "Refresh pool",
                "Wipe all stored proxies and check a fresh pool?",
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
            self._result.setText("Stopping…")

    def _lookup_ip(self) -> None:
        self._lookup.setEnabled(False)
        self._result.setText("Resolving public IP…")
        self._runner.submit(
            workers.tasks.lookup_ip(self._container),
            on_result=lambda ip: self._result.setText(
                f"Public IP: {ip}" if ip else "Public IP could not be resolved."
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._lookup.setEnabled(True),
        )

    # ------------------------------------------------------------ results

    def _apply_summary(self, summary: object) -> None:
        self._total.set_value(summary.proxies)
        self._working.set_value(summary.working_proxies)
        self._dead.set_value(summary.proxies - summary.working_proxies)

    def _show_progress(self, done: int, total: int) -> None:
        self._batch_total = total
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        pct = int(done * 100 / total) if total else 0
        self._progress_label.setText(f"{done} / {total} ({pct}%)")
        self._result.setText(f"Checked {done} / {total}")
        self._refresh_live_metrics()

    def _refresh_live_metrics(self) -> None:
        """Keep the metric strip in sync with the in-flight batch.

        Updated on every streamed result so TOTAL / WORKING / DEAD reflect the
        run in real time instead of holding the previous database snapshot.
        """
        total = self._batch_total or (self._live_working + self._live_dead)
        self._total.set_value(total)
        self._working.set_value(self._live_working)
        self._dead.set_value(self._live_dead)

    def _append_proxy(self, outcome: object) -> None:
        """GUI thread: a working proxy finished checking — insert it into the
        live list right away, keeping the list sorted by latency (lowest ping
        first). Non-working proxies are never shown here; DEAD ones are removed
        from the database by the backend, so the table ends up working-only.
        """
        proxy = outcome.proxy
        if not outcome.ok:
            self._live_dead += 1
            self._refresh_live_metrics()
            return
        self._live_working += 1
        latency = outcome.latency_ms
        if latency is None:
            latency = 10 ** 9
        latency_ms_str = (
            f"{outcome.latency_ms}ms" if outcome.latency_ms is not None else "—"
        )
        country = country_label(outcome.country_code, outcome.country)
        rows = self._live_working
        idx = bisect.bisect_left(self._live_latencies, latency)
        self._live_latencies.insert(idx, latency)
        row = f"#{rows:04d} · {proxy.id:05d} · {proxy.host_port} · WORKING · {latency_ms_str} · {country}"
        self._live.insertItem(idx, row)
        self._refresh_live_metrics()

    def _apply_check_summary(self, summary: object) -> None:
        removed = getattr(summary, "removed", 0)
        stopped = self._stop_event is not None and self._stop_event.is_set()
        prefix = "Stopped" if stopped else "Checked"
        self._result.setText(
            f"{prefix} {summary.checked} · working {summary.working} · "
            f"failed {summary.failed} · removed {removed} "
            f"({summary.elapsed_seconds:.1f}s)"
        )
        self.reload()

    def _reset_busy(self) -> None:
        self._refresh.setEnabled(True)
        self._lookup.setEnabled(True)
        self._stop.setEnabled(False)
        self._stop_event = None
        self._progress.hide()
        self._progress_label.hide()