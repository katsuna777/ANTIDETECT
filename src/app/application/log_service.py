"""Application-level log stream persisted to SQLite and read by the GUI.

The service is the single funnel through which every subsystem (Chromium
launch, proxy checks, profile lifecycle, GUI actions) reports what it is doing.
Entries are written to the repository immediately, so the Log page can poll new
records in real time instead of re-reading the whole history.

It also owns light background "tail" threads that stream a profile's Chromium
stdout/stderr into the same log, so errors raised inside the browser (GL
failures, proxy authentication problems, console errors) land in the same file
someone reads to debug a broken launch.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from app.domain.models.log_entry import LogEntry

if TYPE_CHECKING:
    from app.application.ports import LogRepository

LEVEL_DEBUG = "DEBUG"
LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"

_MAX_TAIL_LINE = 4000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _TailLoop(threading.Thread):
    """Appends new lines of one growing log file into the shared repository."""

    def __init__(self, source: str, path: Path, flush: "Callable[[str, list[str]], None]",
                 interval: float = 0.4, batch: int = 64, time_flush: float = 1.0) -> None:
        super().__init__(name=f"log-tail:{path.name}", daemon=True)
        self._source = source
        self._path = path
        self._flush = flush
        self._interval = interval
        self._batch = batch
        self._time_flush = time_flush
        self._stop = threading.Event()
        self._position = 0

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        buffer: list[str] = []
        last_flush = time.monotonic()
        while not self._stop.wait(self._interval):
            if not self._path.exists():
                continue
            try:
                with open(self._path, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(self._position)
                    data = fh.read()
                    self._position = fh.tell()
            except OSError:
                continue
            if data:
                for line in data.splitlines():
                    line = line.strip()
                    if line:
                        buffer.append(line[: _MAX_TAIL_LINE])
            if buffer and (
                len(buffer) >= self._batch
                or time.monotonic() - last_flush >= self._time_flush
            ):
                self._flush(self._source, buffer)
                buffer = []
                last_flush = time.monotonic()
        if buffer:
            self._flush(self._source, buffer)


class LogService:
    """Thread-safe facade over the log repository for writers and readers.

    ``log``/``info``/``warn``/``error``/``debug`` are callable from any thread
    (GUI thread, worker pool, tail threads) — the repository's connection is
    reentrant-locked. ``list_logs(after_id=...)`` is the incremental read used
    by the GUI's live page; ``export`` renders the whole session to a file.
    """

    def __init__(
        self,
        repository: "LogRepository",
        tail_interval: float = 0.4,
        flush_batch: int = 64,
        flush_seconds: float = 1.0,
    ) -> None:
        self._repository = repository
        self._tail_interval = tail_interval
        self._flush_batch = flush_batch
        self._flush_seconds = flush_seconds
        self._tailers: dict[Path, _TailLoop] = {}
        self._tail_lock = threading.Lock()

    # -------------------------------------------------------------- writing

    def log(
        self,
        level: str,
        source: str,
        message: str,
        extra: dict | None = None,
    ) -> None:
        self._repository.insert(
            LogEntry(id=0, ts=utcnow(), level=level, source=source, message=message, extra=extra)
        )

    def debug(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log(LEVEL_DEBUG, source, message, extra)

    def info(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log(LEVEL_INFO, source, message, extra)

    def warn(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log(LEVEL_WARN, source, message, extra)

    def error(self, source: str, message: str, extra: dict | None = None) -> None:
        self.log(LEVEL_ERROR, source, message, extra)

    # -------------------------------------------------------------- reading

    def list_logs(self, after_id: int = 0, limit: int = 2000) -> list[LogEntry]:
        return self._repository.list_after(after_id=after_id, limit=limit)

    def latest_id(self) -> int:
        return self._repository.latest_id()

    def count(self) -> int:
        return self._repository.count()

    def all_logs(self, limit: int = 100_000) -> list[LogEntry]:
        return self._repository.all(limit=limit)

    # -------------------------------------------------------------- lifecycle

    def reset(self) -> int:
        """Start a fresh log session: stop file tailers and wipe past rows.

        Called once per application launch so every run is a clean slate
        (past sessions are readable after export, not from the live page).
        """
        self._stop_all_tailers()
        cleared = self._repository.clear()
        self.info(
            "app",
            "Log session started",
            extra={"history_cleared": cleared},
        )
        return cleared

    def clear(self) -> int:
        """Non-destructive wipe used by the Log page's CLEAR button.

        Unlike ``reset`` it leaves file tailers alone; only the stored rows are
        dropped so the live list starts fresh while a running browser's output
        keeps streaming in.
        """
        return self._repository.clear()

    def close(self) -> None:
        """Stop background tail threads (called when the Container closes)."""
        self._stop_all_tailers()

    # --------------------------------------------------------------- tailing

    def tail_file(self, source: str, path: Path) -> None:
        """Begin streaming ``path`` (e.g. Chromium stdout/stderr) as ``source``.

        Idempotent: already-tracked paths are not re-tailed. The thread is a
        daemon, so it can never keep the process alive.
        """
        path = Path(path)
        with self._tail_lock:
            if path in self._tailers:
                return
            loop = _TailLoop(
                source, path, self._flush_from_tail,
                interval=self._tail_interval, batch=self._flush_batch,
                time_flush=self._flush_seconds,
            )
            self._tailers[path] = loop
            loop.start()

    def _flush_from_tail(self, source: str, lines: list[str]) -> None:
        self._repository.insert_many(
            [
                LogEntry(id=0, ts=utcnow(), level=LEVEL_INFO, source=source, message=line)
                for line in lines
            ]
        )

    def _stop_all_tailers(self) -> None:
        with self._tail_lock:
            tailers = list(self._tailers.values())
            self._tailers.clear()
        for loop in tailers:
            loop.request_stop()

    # --------------------------------------------------------------- export

    def export(self, path: Path) -> int:
        """Write the whole session log as plain text; returns entry count."""
        entries = self.all_logs()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(_render_entry(entry) + "\n")
        return len(entries)


def _render_entry(entry: LogEntry) -> str:
    ts = _format_ts(entry.ts)
    suffix = ""
    if entry.extra:
        try:
            suffix = "  " + json.dumps(entry.extra, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            suffix = f"  {entry.extra!r}"
    return f"{ts} | {entry.level:<5} | {entry.source:<12} | {entry.message}{suffix}"


def _format_ts(value: datetime) -> str:
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]