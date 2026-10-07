"""The application menu bar (the native one on macOS): every shortcut lives in a menu, so all of them can be found."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QMenu

from antidetect.gui.sidebar import (
    SECTION_ACTIVITY,
    SECTION_API,
    SECTION_PROFILES,
    SECTION_PROXIES,
    SECTION_SETTINGS,
    SECTION_TRASH,
)
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.gui.main_window import MainWindow

_NAV = (
    (SECTION_PROFILES, "nav.profiles", "Ctrl+1"),
    (SECTION_PROXIES, "nav.proxies", "Ctrl+2"),
    (SECTION_ACTIVITY, "nav.activity", "Ctrl+3"),
    (SECTION_API, "nav.api", "Ctrl+4"),
    (SECTION_TRASH, "nav.trash", "Ctrl+5"),
    (SECTION_SETTINGS, "nav.settings", "Ctrl+6"),
)


class AppMenu:
    """Owns the actions; the same QAction objects are on the window (so the shortcuts work) and in the menus."""

    def __init__(self, window: "MainWindow") -> None:
        self._window = window
        self._titles: list[tuple[QAction | QMenu, str]] = []
        bar = window.menuBar()
        # Only macOS has a menu bar that is not part of the window; elsewhere the shortcuts work without drawing one.
        bar.setVisible(QGuiApplication.platformName() == "cocoa")

        def action(key: str, callback, shortcut: str | QKeySequence.StandardKey | None = None,
                   role: QAction.MenuRole | None = None) -> QAction:
            act = QAction(tr(key), window)
            if shortcut is not None:
                act.setShortcut(QKeySequence(shortcut))
            if role is not None:
                act.setMenuRole(role)
            act.triggered.connect(lambda _checked=False: callback())
            window.addAction(act)
            self._titles.append((act, key))
            return act

        def menu(key: str) -> QMenu:
            m = bar.addMenu(tr(key))
            self._titles.append((m, key))
            return m

        file_menu = menu("menu.file")
        file_menu.addAction(action("menu.file.new", window.new_profile, QKeySequence.StandardKey.New))
        file_menu.addAction(action("menu.more.bulk", window.bulk_create, "Ctrl+Shift+N"))
        file_menu.addAction(action("menu.more.import", window.import_profile))
        file_menu.addAction(action("menu.file.proxies", window.add_proxies))
        file_menu.addAction(action("menu.browser.download", window.download_browser))
        file_menu.addSeparator()
        file_menu.addAction(action("menu.file.settings", lambda: window.show_section(SECTION_SETTINGS),
                                   "Ctrl+,", QAction.MenuRole.PreferencesRole))
        file_menu.addAction(action("menu.file.about", lambda: window.show_section(SECTION_SETTINGS),
                                   None, QAction.MenuRole.AboutRole))
        file_menu.addAction(action("menu.file.quit", window.close, QKeySequence.StandardKey.Quit,
                                   QAction.MenuRole.QuitRole))

        view_menu = menu("menu.view")
        for key, text_key, shortcut in _NAV:
            view_menu.addAction(action(text_key, lambda k=key: window.show_section(k), shortcut))
        view_menu.addSeparator()
        view_menu.addAction(action("menu.view.search", window.open_palette, "Ctrl+K"))
        view_menu.addAction(action("menu.view.theme", window.toggle_theme, "Ctrl+Shift+L"))

        window_menu = menu("menu.window")
        window_menu.addAction(action("menu.window.minimize", window.showMinimized, "Ctrl+M"))
        window_menu.addAction(action("menu.window.zoom", self._zoom))

    def _zoom(self) -> None:
        window = self._window
        window.showNormal() if window.isMaximized() else window.showMaximized()

    def retranslate(self) -> None:
        for item, key in self._titles:
            if isinstance(item, QMenu):
                item.setTitle(tr(key))
            else:
                item.setText(tr(key))
