"""Background execution for the GUI.

Application services are synchronous; the GUI runs them on one shared
:class:`QThreadPool`. A task is a ``(progress) -> result`` callable (see
:mod:`antidetect.gui.workers.tasks`). Its outcome travels back through *one*
long-lived queued signal on the runner, so callbacks run on the GUI thread and may
touch widgets freely, and a task costs two plain Python objects — no QObject per
task to create, connect or race against on deletion. Workers never touch widgets.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Signal

_PROGRESS_INTERVAL_S = 0.05   # a task reports at most 20 times a second: the bar cannot show more

ProgressCallback = Callable[[int, int], None]
TaskFunction = Callable[[ProgressCallback], object]
ErrorHandler = Callable[[object], None]

# Every live runner registers here so tests/teardowns can drain all pools
# before closing a shared Container (closing SQLite under an active worker
# thread can segfault the process, no matter how careful the lock is).
_ACTIVE_RUNNERS: set["TaskRunner"] = set()
_ACTIVE_LOCK = threading.Lock()


class _Task:
    """The callbacks of one submitted task."""

    __slots__ = ("on_result", "on_error", "on_progress", "on_finished")

    def __init__(self, on_result, on_error, on_progress, on_finished) -> None:
        self.on_result = on_result
        self.on_error = on_error
        self.on_progress = on_progress
        self.on_finished = on_finished


class _Worker(QRunnable):
    def __init__(self, fn: TaskFunction, task: _Task, deliver: Callable[[object], None]) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn
        self._task = task
        self._deliver = deliver

    def run(self) -> None:
        task = self._task

        def deliver(item: tuple) -> None:
            try:
                self._deliver(item)
            except RuntimeError:
                pass  # the runner (and window) are already gone: nobody is left to tell

        last = 0.0

        def progress(done: int, total: int) -> None:
            # A proxy check reports once per proxy (tens of thousands): coalesce, but never lose the last one.
            nonlocal last
            now = time.monotonic()
            if done >= total or now - last >= _PROGRESS_INTERVAL_S:
                last = now
                deliver((task, "progress", (done, total)))

        try:
            outcome = self._fn(progress)
        except Exception as exc:  # noqa: BLE001 - forwarded to the UI, never escapes into Qt's pool
            deliver((task, "error", exc))
        else:
            deliver((task, "result", outcome))
        finally:
            deliver((task, "finished", None))


class TaskRunner(QObject):
    """Submits service-backed tasks to a shared thread pool.

    ``error_sink`` (a LogSink) receives one ERROR entry per failed task before
    ``on_error`` runs, so every worker failure lands in the session log even when
    the page only shows a toast.
    """

    _SHUTDOWN_WAIT_MS = 3000
    _delivered = Signal(object)   # emitted from pool threads, handled on the GUI thread

    def __init__(self, parent: QObject | None = None, error_sink=None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        # Several heavy operations (proxy refresh, profile start, cookie export...)
        # may overlap; idealThreadCount() can be tiny on CI boxes, so keep a floor.
        self._pool.setMaxThreadCount(max(4, QThread.idealThreadCount()))
        self._closed = False
        self._error_sink = error_sink
        self._delivered.connect(self._dispatch)
        with _ACTIVE_LOCK:
            _ACTIVE_RUNNERS.add(self)

    @staticmethod
    def drain_all(timeout_ms: int = 5000) -> None:
        """Wait for every registered runner (called before a shared Container closes)."""
        with _ACTIVE_LOCK:
            runners = list(_ACTIVE_RUNNERS)
        for runner in runners:
            runner.shutdown(timeout_ms)

    def submit(
        self,
        fn: TaskFunction,
        *,
        on_result: Callable[[object], None] | None = None,
        on_error: ErrorHandler | None = None,
        on_progress: ProgressCallback | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        """Queue ``fn``; its callbacks run on the GUI thread, ``on_finished`` always last."""
        task = _Task(on_result, on_error, on_progress, on_finished)
        if self._closed:
            # The pool was drained (window closed / teardown). Never start new work:
            # a worker would touch SQLite while the Container is shutting down.
            # Report an immediate no-op finish so the caller restores its busy state.
            QTimer.singleShot(0, lambda: self._dispatch((task, "finished", None)))
            return
        self._pool.start(_Worker(fn, task, self._delivered.emit))

    def shutdown(self, timeout_ms: int | None = None) -> None:
        """Stop accepting work, drop queued work and wait for what is running (idempotent)."""
        self._closed = True
        self._pool.clear()
        self._pool.waitForDone(timeout_ms or self._SHUTDOWN_WAIT_MS)
        with _ACTIVE_LOCK:
            _ACTIVE_RUNNERS.discard(self)

    # ------------------------------------------------------------- GUI thread
    def _dispatch(self, item: tuple) -> None:
        task, kind, payload = item
        if kind == "progress":
            if task.on_progress is not None:
                task.on_progress(*payload)
        elif kind == "result":
            if task.on_result is not None:
                task.on_result(payload)
        elif kind == "error":
            self._log_failure(payload)
            if task.on_error is not None:
                task.on_error(payload)
        elif task.on_finished is not None:
            task.on_finished()

    def _log_failure(self, exc: object) -> None:
        sink = self._error_sink
        if sink is not None:
            try:
                sink.error("gui", f"Task failed: {exc}")
            except Exception:  # noqa: BLE001 - logging never breaks error handling
                pass
