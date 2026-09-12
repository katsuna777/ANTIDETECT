"""Shared helpers for offscreen PySide6 tests (no pytest-qt dependency).

The Qt platform must be ``offscreen`` so tests run headless on any machine; the
``qapp`` fixture sets it before the first ``QApplication`` is constructed.
"""

from __future__ import annotations

import os
import time
from typing import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


def spin_wait(predicate: Callable[[], bool], timeout_ms: int = 6000) -> bool:
    """Pump the event loop until ``predicate`` holds, then return its value.

    Queued worker signals are delivered to the GUI thread while the loop runs,
    so slots fire exactly like they would in a real session.
    """
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()