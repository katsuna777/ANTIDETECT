"""The main application window: sidebar navigation + content stack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from app.gui.utils.icons import APP_ICON_PATH

from app.gui.utils.preferences import Preferences
from app.gui.utils.theme import (
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
    apply_theme,
    current_theme,
)
from app.gui.widgets.pages.configurations_page import ConfigurationsPage
from app.gui.widgets.pages.logs_page import LogsPage
from app.gui.widgets.pages.profiles_page import ProfilesPage
from app.gui.widgets.pages.proxies_page import ProxiesPage
from app.gui.widgets.pages.settings_page import SettingsPage
from app.gui.widgets.sidebar import (
    SECTION_CONFIGURATIONS,
    SECTION_LOGS,
    SECTION_PROFILES,
    SECTION_PROXIES,
    SECTION_SETTINGS,
    Sidebar,
)
from app.gui.workers.task_runner import TaskRunner

if TYPE_CHECKING:
    from app.di import Container


class MainWindow(QMainWindow):
    """Hosts the section pages behind a hairline-separated sidebar."""

    def __init__(self, container: "Container", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = TaskRunner(self)
        self._prefs = Preferences(container.settings)

        self.setWindowTitle("Antidetect")
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar = Sidebar()
        self._stack = QStackedWidget()

        self._pages = {
            SECTION_PROFILES: ProfilesPage(container, self._runner, self),
            SECTION_PROXIES: ProxiesPage(container, self._runner, self),
            SECTION_CONFIGURATIONS: ConfigurationsPage(container, self._runner, self),
            SECTION_SETTINGS: SettingsPage(container, self),
            SECTION_LOGS: LogsPage(container, self._runner, self),
        }
        for page in self._pages.values():
            self._stack.addWidget(page)

        layout.addWidget(self._sidebar)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._sidebar.sectionRequested.connect(self._show_section)
        self._sidebar.themeToggleRequested.connect(self.toggle_theme)
        self._show_section(SECTION_PROFILES)

        # Restore persisted theme before first paint; sidebar reflects it.
        try:
            stored = self._prefs.get_theme(current_theme(QApplication.instance()))
            app = QApplication.instance()
            if app is not None:
                from app.gui.utils.theme import current_accent

                apply_theme(
                    app, stored, self._prefs.get_accent(current_accent(app))
                )
            self._sidebar.set_theme_label(stored)
        except Exception:
            pass

        self._register_shortcuts()

        self.statusBar().showMessage(
            f"data dir · {container.config.data_dir}   "
            f"chrome · {container.config.chromium_path or 'auto'}"
        )
        self.statusBar().setSizeGripEnabled(False)

        self._prefs.load_geometry(self)

    # ------------------------------------------------------------ sections

    def show_section(self, key: str) -> None:
        """Public navigation API (used by tests and future menus)."""
        self._show_section(key)

    def _show_section(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self._sidebar.select(key)
        self._stack.setCurrentWidget(page)

    def current_section(self) -> str | None:
        widget = self._stack.currentWidget()
        for key, page in self._pages.items():
            if page is widget:
                return key
        return None

    def page(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    # ------------------------------------------------------------ theme

    def current_theme(self) -> str:
        return current_theme(QApplication.instance())

    def toggle_theme(self) -> str:
        """Flip light/dark, persist it, and refresh the whole app stylesheet."""
        app = QApplication.instance()
        next_theme = "light" if self.current_theme() == "dark" else "dark"
        if app is not None:
            apply_theme(app, next_theme)
        try:
            self._prefs.set_theme(next_theme)
        except Exception:
            pass
        self._sidebar.set_theme_label(next_theme)
        settings = self._pages.get(SECTION_SETTINGS)
        if settings is not None and hasattr(settings, "sync_theme"):
            try:
                settings.sync_theme(next_theme)
            except Exception:
                pass
        return next_theme

    def _register_shortcuts(self) -> None:
        """1–5 jump between sections, T toggles the theme."""
        order = (
            SECTION_PROFILES,
            SECTION_PROXIES,
            SECTION_CONFIGURATIONS,
            SECTION_LOGS,
            SECTION_SETTINGS,
        )
        for index, key in enumerate(order, start=1):
            action = QAction(self)
            action.setShortcut(QKeySequence(str(index)))
            action.triggered.connect(lambda _=False, k=key: self._show_section(k))
            self.addAction(action)
        theme_action = QAction(self)
        theme_action.setShortcut(QKeySequence("T"))
        theme_action.triggered.connect(self.toggle_theme)
        self.addAction(theme_action)

    # ------------------------------------------------------------ lifecycle

    def closeEvent(self, event) -> None:
        """Persist window geometry and stop background tasks before quit.

        Ordering matters: the Container (and its SQLite connection) is closed
        from ``QApplication.aboutToQuit`` *after* this runs, so no worker is
        mid-flight against a closed database.
        """
        self._prefs.save_geometry(self)
        self._runner.shutdown()
        super().closeEvent(event)
