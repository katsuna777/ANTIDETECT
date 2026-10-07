"""Full application bootstrap: run_app wires window + container + shutdown."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTimer

from antidetect.gui.app import run_app

pytestmark = pytest.mark.usefixtures("qapp")


def test_run_app_opens_window_and_closes_container_cleanly(
    gui_container, qapp
):
    """The single Container must be closed exactly via aboutToQuit."""
    try:
        QTimer.singleShot(300, qapp.quit)
        code = run_app(gui_container, qapp)
        assert code == 0

        # aboutToQuit closed the database — the file must still exist on disk.
        assert gui_container.db.path.exists()
        # Any further DB access now raises the closed-database signal.
        with pytest.raises(Exception):
            gui_container.db.execute("SELECT 1")
    finally:
        # run_app connected aboutToQuit -> container.close; drop it so it never
        # fires again for other tests sharing this session-scoped QApplication.
        qapp.aboutToQuit.disconnect()