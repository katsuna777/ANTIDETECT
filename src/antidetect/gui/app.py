"""Qt application bootstrap: Container lifetime + theme + main window.

The Container created here is the *single* instance for the whole GUI session:
created once before the window, closed exactly once from ``QApplication.aboutToQuit``.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from antidetect.container import bootstrap
from antidetect.gui.main_window import MainWindow
from antidetect.gui.preferences import Preferences
from antidetect.gui.theme import apply_theme
from antidetect.gui.resources import APP_ICON_PATH
from antidetect.i18n import set_language, tr

if TYPE_CHECKING:
    from antidetect.container import Container


def build_app(argv: list[str] | None = None, theme: str | None = None) -> QApplication:
    """Create or reuse the single QApplication, themed (also a test helper)."""
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("Antidetect")
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)   # macOS hides menu icons by default
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    apply_theme(app, theme or "system")
    return app


def run_app(container: "Container", app: QApplication | None = None) -> int:
    """Show the main window and run the event loop against ``container``."""
    app = app or build_app()
    prefs = Preferences(container.settings)
    try:
        set_language(prefs.get_language())
        apply_theme(app, prefs.get_theme())
    except Exception:
        pass

    container.logs.info(
        "app",
        tr("log.app.started"),
        extra={
            "data_dir": str(container.config.data_dir),
            "database": str(container.config.database_path),
            "chromium": str(container.config.chromium_path or "auto"),
        },
    )
    window = MainWindow(container, defer_first_page=True, prewarm=True)
    window.show()
    window.repaint()  # put the frame on screen before the first page is built

    # Order matters: close the window first (it stops profiles and drains the
    # worker pool), only then close the Container (SQLite).
    app.aboutToQuit.connect(lambda: container.logs.info("app", tr("log.app.exiting")))
    app.aboutToQuit.connect(container.close)
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    """``antidetect-gui`` entry point: bootstrap and run the GUI (``--selftest [report.json]`` checks the bundle instead)."""
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "--selftest":
        from antidetect.gui.selftest import run

        return run(args[1] if len(args) > 1 else None)

    from antidetect.runtime import ensure_ssl_certs

    ensure_ssl_certs()
    return run_app(bootstrap())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
