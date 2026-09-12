"""Qt application bootstrap: Container lifetime + theme + main window.

The Container created here is the *single* instance for the whole GUI session:
created once before the window, closed exactly once from
``QApplication.aboutToQuit``.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.di import bootstrap
from app.gui.main_window import MainWindow
from app.gui.utils.icons import APP_ICON_PATH
from app.gui.utils.theme import apply_theme
from app.gui.widgets.splash_screen import SplashScreen, attach_fade_in

if TYPE_CHECKING:
    from app.di import Container


def build_app(argv: list[str] | None = None, theme: str | None = None) -> QApplication:
    """Create or reuse the single QApplication, themed (test helper)."""
    # Silence the one-time ``qt.qpa.fonts`` startup info (font-alias timing);
    # it carries no signal about our theme and only litters the console.
    # Set before the first QApplication — ignored when the user overrode it.
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    apply_theme(app, theme)
    return app


def run_app(
    container: "Container",
    app: QApplication | None = None,
    show_splash: bool = True,
) -> int:
    """Show the main window and run the event loop against ``container``.

    On every launch the window opens immediately and the 0–100% splash
    runs as an overlay *inside* it. Splash is skipped only when
    ``show_splash`` is False or ``ANTIDETECT_NO_SPLASH=1`` is set (tests/dev).
    Returns the QApplication exit code. The ``container`` is closed via
    ``aboutToQuit``; ``MainWindow.closeEvent`` has already drained the worker
    pool by then.
    """
    app = app or build_app()
    try:
        from app.gui.i18n import set_language
        from app.gui.utils.preferences import Preferences

        stored = Preferences(container.settings).get_theme()
        stored_lang = Preferences(container.settings).get_language()
        set_language(stored_lang)
        from app.gui.utils.theme import current_accent

        apply_theme(app, stored, Preferences(container.settings).get_accent(current_accent(app)))
    except Exception:
        pass

    from app.gui.i18n import tr

    container.logs.info(
        "app",
        tr("log.app.started"),
        extra={
            "data_dir": str(container.config.data_dir),
            "database": str(container.config.database_path),
            "chromium": str(container.config.chromium_path or "auto"),
        },
    )
    window = MainWindow(container)
    window.show()

    skip = not show_splash or os.environ.get("ANTIDETECT_NO_SPLASH") == "1"
    if not skip:
        # Overlay внутри окна: контент уже под ним, по окончании сплэш
        # гаснет, а контент мягко проявляется (fade-in; slide выключен —
        # виджет живёт в layout окна и двигать его нельзя).
        splash = SplashScreen(window)
        splash.start(
            lambda: attach_fade_in(window.centralWidget(), slide=False)
        )

    # Порядок важен: сначала закрыть окно (MainWindow.closeEvent глушит
    # TaskRunner и сохраняет геометрию), и только потом закрывать
    # Container (SQLite). Сплэш — child окна, умрёт вместе с ним.
    app.aboutToQuit.connect(window.close)
    app.aboutToQuit.connect(
        lambda: container.logs.info("app", tr("log.app.exiting"))
    )
    app.aboutToQuit.connect(container.close)
    return app.exec()


def main() -> int:
    """``python -m app.gui`` entry point: bootstrap and run the GUI."""
    from app._frozen import ensure_ssl_certs

    ensure_ssl_certs()
    return run_app(bootstrap())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())