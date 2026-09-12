"""Owns the GUI's background task pool.

A single :class:`TaskRunner` is created by the main window and reused for the
lifetime of the application. Every submit has a ``(progress) -> result``
callable (see :mod:`app.gui.workers.tasks`) and runs on a shared
:class:`QThreadPool`, so different operations — profile start, proxy refresh,
cookie export — can execute concurrently without blocking the UI thread.
"""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, QThread, QThreadPool, QTimer

from app.gui.signals.worker_signals import TaskHandle, WorkerSignals
from app.gui.workers.worker import GenericWorker, TaskFunction

ErrorHandler = Callable[[object], None]

# Every live runner registers here so tests/teardowns can drain all pools
# before closing a shared Container (closing SQLite under an active worker
# thread can segfault the process, no matter how careful the lock is).
_ACTIVE_RUNNERS: set["TaskRunner"] = set()
_ACTIVE_LOCK = threading.Lock()


class TaskRunner(QObject):
    """Submits service-backed tasks to a shared thread pool.

    Callbacks (``on_result``, ``on_error``, ``on_progress``, ``on_finished``)
    are invoked through queued slot calls on whichever thread created the
    runner (the GUI thread), so widgets may be updated freely inside them.

    ``error_sink`` (a LogSink) receives one ERROR entry per failed task
    before ``on_error`` runs, so every worker failure lands in the session
    log even when the page only shows a dialog.
    """

    _INTERNAL_WAIT_MS = 3000

    def __init__(self, parent: QObject | None = None, error_sink=None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        # Allow several heavy operations (proxy refresh, profile start, cookie
        # export...) to overlap. idealThreadCount() can be 1/tiny on some CI
        # boxes, so enforce a meaningful floor.
        self._pool.setMaxThreadCount(
            max(4, QThread.idealThreadCount())
        )
        self._closed = False
        self._active = 0
        self._error_sink = error_sink
        with _ACTIVE_LOCK:
            _ACTIVE_RUNNERS.add(self)

    @staticmethod
    def drain_all(timeout_ms: int = 5000) -> None:
        """Wait for every registered runner to finish its tasks.

        Called before a shared Container is closed so no worker thread is ever
        mid-query when the SQLite connection is shut down.
        """
        with _ACTIVE_LOCK:
            runners = list(_ACTIVE_RUNNERS)
        for runner in runners:
            runner.shutdown(timeout_ms)

    # ------------------------------------------------------------ API

    @property
    def pool(self) -> QThreadPool:
        return self._pool

    @property
    def active_tasks(self) -> int:
        return self._active

    def submit(
        self,
        fn: TaskFunction,
        *,
        on_result: Callable[[object], None] | None = None,
        on_error: ErrorHandler | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> TaskHandle:
        """Queue ``fn`` for execution and return a handle for its signals."""
        signals = WorkerSignals(self)
        handle = TaskHandle(signals, parent=self)
        if on_result is not None:
            handle.result.connect(on_result)
        if on_error is not None:
            handle.error.connect(self._wrap_error(on_error))
        if on_progress is not None:
            handle.progress.connect(on_progress)
        if on_finished is not None:
            handle.finished.connect(on_finished)

        if self._closed:
            # The pool was drained (window closed / teardown). Never start new
            # work here: a worker would touch SQLite while the Container is
            # being shut down. Report an immediate no-op finish instead so the
            # caller restores busy state cleanly.
            QTimer.singleShot(0, self._no_op_then_finish)
            handle.finished.connect(self._on_finished)
            return handle

        self._active += 1
        handle.finished.connect(self._on_finished)

        worker = GenericWorker(fn, signals)
        self._pool.start(worker)
        return handle

    def _no_op_then_finish(self) -> None:
        self._active += 1
        self._on_finished()

    # ---------------------------------------------------------- shutdown

    def shutdown(self, timeout_ms: int | None = None) -> None:
        """Stop accepting work, cancel queued work and wait for anything running.

        Idempotent. Called from the main window's ``closeEvent`` (and by
        ``drain_all``), so the database (owned by the Container) is never
        closed underneath still-running tasks — and no lateness-delivered
        signal can start fresh tasks against a doomed pool.
        """
        self._closed = True
        self._pool.clear()
        self._pool.waitForDone(timeout_ms or self._INTERNAL_WAIT_MS)
        with _ACTIVE_LOCK:
            _ACTIVE_RUNNERS.discard(self)

    # ---------------------------------------------------------- internal

    def _wrap_error(self, handler: ErrorHandler) -> ErrorHandler:
        """Log the failure to the session log, then run the page handler."""

        def wrapped(exc: object) -> None:
            sink = self._error_sink
            if sink is not None:
                try:
                    sink.error("gui", f"Task failed: {exc}")
                except Exception:  # noqa: BLE001 - logging never breaks errors
                    pass
            handler(exc)

        return wrapped

    def _on_finished(self) -> None:
        self._active = max(0, self._active - 1)