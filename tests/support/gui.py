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


def hover(widget, pos) -> None:
    """Put the pointer over ``pos`` (in ``widget``'s coordinates) by sending the widget its mouse-move.

    ``QTest.mouseMove`` is not a widget-level call: it moves the *platform's* cursor, which is one piece of
    state for the whole process, shared by every test a worker runs. A move to the spot where an earlier test
    left the cursor produces no event at all, and the move is handed to the first exposed top-level window
    under the point (a window or popup that is still around, the drawer of an opening row) instead of to
    ``widget``. ``QTest.mouseClick`` already delivers its press and release straight to the widget, so the
    hover that precedes it must not depend on any of that either.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def make_profile(container, name="Alpha", platform="windows", **kw):
    """Create a profile through the same two steps the page runs (no auto-geo, no real network)."""
    from antidetect.gui.models.specs import ProfileSpec
    from antidetect.gui.workers import tasks

    spec = ProfileSpec(name=name, platform=platform, geo_auto=False, **kw)
    profile = tasks.create_profile(container, spec)(lambda *a: None)
    if tasks.needs_settling(spec, start=False):
        tasks.settle_profile(container, profile.id)(lambda *a: None)
    return profile


def settle(window, count):
    """Reload the profiles page and wait until it shows ``count`` rows."""
    from antidetect.gui.sidebar import SECTION_PROFILES

    page = window.page(SECTION_PROFILES)
    page.reload()
    assert spin_wait(lambda: page._model.rowCount() == count)
    return page


def settings_tab(window, key: str):
    """Open a tab of the Settings page (``check`` / ``logs``) and return the page inside it."""
    from antidetect.gui.sidebar import SECTION_SETTINGS

    window.show_section(SECTION_SETTINGS)
    settings = window.page(SECTION_SETTINGS)
    settings.show_tab(key)
    return settings._subpages[key]


def logs_page(window):
    return settings_tab(window, "logs")


def check_page(window):
    return settings_tab(window, "check")
