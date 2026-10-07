"""Shared GUI fixtures: English UI, a real window over a throwaway Container."""

from __future__ import annotations

import pytest

from antidetect.gui.main_window import MainWindow
from antidetect.gui.theme import apply_theme
from antidetect.i18n import set_language
from tests.support.fakes import StubChecker


@pytest.fixture(autouse=True)
def _english_and_light(qapp):
    """The QApplication is shared by the whole session: start every test from the same look."""
    set_language("en")
    apply_theme(qapp, "light")
    yield
    set_language("en")
    apply_theme(qapp, "light")


@pytest.fixture(autouse=True)
def _no_silent_slot_errors():
    """Qt prints an exception raised in a slot and carries on, so a test would stay green while
    the user sees a traceback in the console. Turn every such exception into a failure."""
    import sys

    caught: list[BaseException] = []
    previous = sys.excepthook
    def record(kind, value, tb) -> None:
        import traceback

        traceback.print_exception(kind, value, tb)       # pytest shows it next to the failure
        caught.append(value)

    sys.excepthook = record
    try:
        yield
    finally:
        sys.excepthook = previous
    assert not caught, f"exception(s) raised inside Qt slots: {[repr(e) for e in caught]}"


def release(win) -> None:
    """Close a window and free it: a closed window that lingers is restyled on every theme change
    of the shared QApplication, which makes each later test slower than the one before."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    win.close()
    win.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture()
def window(gui_container, fake_chromium, qapp):
    gui_container.browser.set_chromium_path(fake_chromium)
    win = MainWindow(gui_container)
    win.resize(1200, 760)
    win.show()
    yield win
    release(win)


@pytest.fixture()
def gui_container(gui_container):
    """The production wiring, except that proxy checks never touch the network."""
    gui_container.proxies._checker = StubChecker()
    return gui_container
