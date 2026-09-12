"""Live application log page.

Shows every entry the app records (session start, Chromium launch + its own
stdout/stderr stream, proxy checks) in real time. Rows are fetched
incrementally from ``LogService`` on the background pool, so the page never
touches SQLite from the UI thread. EXPORT writes the whole session to a UTF-8
text file for offline debugging; CLEAR wipes the current session's rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)

from app.gui import workers
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container
    from app.gui.workers.task_runner import TaskRunner

_MAX_ROWS = 4000
_POLL_MS = 1000


def _format_ts(value: datetime) -> str:
    """Render a stored UTC-naive timestamp in the user's local timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _render_entry(entry) -> str:
    try:
        ts = _format_ts(entry.ts)
    except (ValueError, OverflowError):
        ts = "?"
    suffix = ""
    if entry.extra:
        try:
            payload = json.dumps(entry.extra, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            payload = repr(entry.extra)
        if len(payload) > 240:
            payload = payload[:237] + "..."
        suffix = f"  {payload}"
    return f"{ts} | {entry.level:<5} | {entry.source:<12} | {entry.message}{suffix}"


class LogsPage(PlaceholderPage):
    def __init__(
        self, container: "Container", runner: "TaskRunner", parent=None
    ) -> None:
        super().__init__("Log", kicker="LIVE SESSION LOG")
        self._container = container
        self._runner = runner
        self._last_id = 0
        self._polling = False

        self._entries = QLabel("0 entries")
        self._entries.setObjectName("ResultLabel")
        self.add_control_row(self._entries)

        self._export = QPushButton("EXPORT")
        self._clear = QPushButton("CLEAR")
        self._pause = QPushButton("PAUSE")
        self.add_control_row(self._export, self._clear, self._pause)

        self._list = QListWidget()
        self._list.setObjectName("LogList")
        self.add_widget(self._list, 1)

        self._result = QLabel("Ready.")
        self._result.setObjectName("ResultLabel")
        self.add_control_row(self._result)

        self._export.clicked.connect(self._export_logs)
        self._clear.clicked.connect(self._clear_logs)
        self._pause.clicked.connect(self._toggle_pause)
        self._export.setToolTip("Write the whole session to a UTF-8 text file")
        self._clear.setToolTip("Wipe the current session's rows")
        self._pause.setToolTip("Pause live polling")

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._paused = False
        self._timer.start()

    # ------------------------------------------------------------ polling

    def _poll(self) -> None:
        if self._paused or self._polling:
            return
        self._polling = True
        self._runner.submit(
            workers.tasks.list_logs(self._container, after_id=self._last_id),
            on_result=self._append_logs,
            on_finished=self._poll_done,
            on_error=self._poll_error,
        )

    def _poll_done(self) -> None:
        self._polling = False

    def _poll_error(self, exc: object) -> None:
        self._polling = False
        self._result.setText(f"Log poll failed: {exc}")

    def _append_logs(self, entries: object) -> None:
        entries = list(entries or [])
        if not entries:
            self._refresh_count()
            return
        self._last_id = entries[-1].id
        for entry in entries:
            item = QListWidgetItem(_render_entry(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self._list.addItem(item)
        while self._list.count() > _MAX_ROWS:
            self._list.takeItem(0)
        self._refresh_count()
        self._list.scrollToBottom()

    def _refresh_count(self) -> None:
        self._entries.setText(f"{self._list.count()} entries · last id {self._last_id}")

    # ------------------------------------------------------------ actions

    def _export_logs(self) -> None:
        default_name = f"antidetect_log_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export log", default_name, "Text (*.txt)"
        )
        if not path:
            return
        self._export.setEnabled(False)
        self._result.setText("Exporting…")
        self._runner.submit(
            workers.tasks.export_logs(self._container, Path(path)),
            on_result=lambda p: self._result.setText(f"Exported {self._list.count()} rows → {p}"),
            on_error=lambda exc: self._result.setText(f"Export failed: {exc}"),
            on_finished=lambda: self._export.setEnabled(True),
        )

    def _clear_logs(self) -> None:
        self._result.setText("Clearing log…")
        self._runner.submit(
            workers.tasks.clear_logs(self._container),
            on_result=self._apply_clear,
            on_error=lambda exc: self._result.setText(f"Clear failed: {exc}"),
        )

    def _apply_clear(self, cleared: object) -> None:
        self._list.clear()
        self._last_id = 0
        self._result.setText(f"Cleared {cleared} entries.")
        self._refresh_count()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._pause.setText("RESUME" if self._paused else "PAUSE")