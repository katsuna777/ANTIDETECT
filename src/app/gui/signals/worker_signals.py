"""Signals emitted by :class:`app.gui.workers.worker.Worker`.

Each ``Worker`` owns one :class:`WorkerSignals` instance. The signals may be
emitted from the pool thread; slots connected in the GUI thread are delivered
through queued connections by Qt's event loop.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    """Transport object carrying a single task's outcomes to the GUI thread."""

    result = Signal(object)
    """Payload of a successful run (service return value)."""

    error = Signal(object)
    """The exception raised by the task (an AntiDetectError for expected ones)."""

    finished = Signal()
    """Fired after ``result`` or ``error``; marks the task as done."""

    progress = Signal(int, int)
    """(done, total) progress updates for long-running tasks."""


class TaskHandle(QObject):
    """Per-task facade giving the UI typed access to a running operation.

    The handle re-exposes the worker signals with the same names so pages can
    connect through one object instead of reaching into internals.
    """

    result = Signal(object)
    error = Signal(object)
    finished = Signal()
    progress = Signal(int, int)

    def __init__(self, signals: WorkerSignals, parent: QObject | None = None) -> None:
        super().__init__(parent)
        signals.result.connect(self.result)
        signals.error.connect(self.error)
        signals.finished.connect(self.finished)
        signals.progress.connect(self.progress)