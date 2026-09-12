"""Generic background task execution for the GUI.

Application services are synchronous; the GUI runs them on a
:class:`QThreadPool` through :class:`GenericWorker` (a :class:`QRunnable`).
Workers never touch Qt widgets, so any number of them can run at once without
freezing the interface.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRunnable

from app.gui.signals.worker_signals import WorkerSignals

ProgressCallback = Callable[[int, int], None]
TaskFunction = Callable[[ProgressCallback], object]


class GenericWorker(QRunnable):
    """Runs ``fn(progress)`` off the GUI thread and relays its outcome.

    The callable is invoked with a ``(done, total)`` progress callback which it
    may ignore. Any exception (including every :class:`app.domain.errors
    .AntiDetectError`) is caught and forwarded through the ``error`` signal —
    it never escapes into Qt's thread pool. ``finished`` always fires so the UI
    can restore busy state.
    """

    def __init__(self, fn: TaskFunction, signals: WorkerSignals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        def emit_progress(done: int, total: int) -> None:
            self._signals.progress.emit(done, total)

        try:
            result = self._fn(emit_progress)
        except Exception as exc:  # noqa: BLE001 - forwarded to the UI
            self._signals.error.emit(exc)
        else:
            self._signals.result.emit(result)
        finally:
            self._signals.finished.emit()