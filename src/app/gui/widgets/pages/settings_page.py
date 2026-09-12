"""Settings placeholder page.

Shows the resolved runtime configuration plus the GUI prefs layer. Preference
values round-trip through :class:`app.gui.utils.preferences.Preferences`, which
persists them in the application's existing settings table — a live proof that
the GUI never touches storage directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.gui.utils.preferences import Preferences
from app.gui.utils.theme import apply_theme
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container


class SettingsPage(PlaceholderPage):
    def __init__(self, container: "Container", parent=None) -> None:
        # Scrollable like every other page: on short windows the appearance
        # combos must scroll into view, never squeeze into unreadable stubs.
        super().__init__("Settings", kicker="SECTION 05")
        self._container = container
        self._prefs = Preferences(container.settings)

        runtime_box = QGroupBox("1 · Runtime")
        runtime_layout = QVBoxLayout(runtime_box)
        runtime = QLabel(
            f"data dir        {container.config.data_dir}\n"
            f"database        {container.config.database_path}\n"
            f"chromium        {container.config.chromium_path or 'auto (discovered at start)'}"
        )
        runtime.setObjectName("ResultLabel")
        runtime.setWordWrap(True)
        runtime.setTextInteractionFlags(
            runtime.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        runtime_layout.addWidget(runtime)
        self.add_widget(runtime_box)

        safety_box = QGroupBox("2 · Safety")
        safety_layout = QVBoxLayout(safety_box)
        self._confirm = QCheckBox("Confirm before destructive actions")
        self._confirm.setToolTip("When off, DELETE and REFRESH POOL run immediately")
        self._confirm.setChecked(
            self._prefs.get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, default=True)
        )
        self._confirm.toggled.connect(
            lambda checked: self._prefs.set_bool(
                Preferences.KEY_CONFIRM_DESTRUCTIVE, checked
            )
        )
        safety_layout.addWidget(self._confirm)
        safety_hint = QLabel("Covers profile delete, configuration delete and proxy pool refresh.")
        safety_hint.setObjectName("HintLabel")
        safety_layout.addWidget(safety_hint)
        self.add_widget(safety_box)

        appearance_box = QGroupBox("3 · Appearance")
        appearance_layout = QVBoxLayout(appearance_box)
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Light · paper ledger", "light")
        self._theme_combo.addItem("Dark · inverted ledger", "dark")
        self._theme_combo.setToolTip("Switch light / dark theme (T). Saved in gui.theme.")
        current = self._prefs.get_theme()
        self._theme_combo.setCurrentIndex(1 if current == "dark" else 0)
        self._theme_combo.currentIndexChanged.connect(self._apply_theme_choice)
        appearance_layout.addWidget(self._theme_combo)
        self._accent_combo = QComboBox()
        self._accent_combo.addItem("Mono · strict ledger", "mono")
        self._accent_combo.addItem("Red accent", "red")
        self._accent_combo.addItem("Orange accent", "orange")
        self._accent_combo.addItem("Yellow accent", "yellow")
        self._accent_combo.addItem("Green accent", "green")
        self._accent_combo.addItem("Cyan accent", "cyan")
        self._accent_combo.addItem("Blue accent", "blue")
        self._accent_combo.addItem("Purple accent", "purple")
        self._accent_combo.addItem("Pink accent", "pink")
        self._accent_combo.addItem("Lime accent", "lime")
        self._accent_combo.setToolTip(
            "Accent foreground: replaces the black/white ink, paper background stays. Saved in gui.accent."
        )
        accent_index = list(Preferences.ACCENTS).index(self._prefs.get_accent())
        self._accent_combo.setCurrentIndex(accent_index)
        self._accent_combo.currentIndexChanged.connect(self._apply_accent_choice)
        appearance_layout.addWidget(self._accent_combo)
        appearance_hint = QLabel("Background stays paper/ink · only the foreground accent changes.")
        appearance_hint.setObjectName("HintLabel")
        appearance_hint.setWordWrap(True)
        appearance_layout.addWidget(appearance_hint)
        self._theme_toggle = QPushButton("TOGGLE THEME (T)")
        self._theme_toggle.setToolTip("Flip light / dark immediately")
        self._theme_toggle.clicked.connect(self._toggle_theme_button)
        appearance_layout.addWidget(self._theme_toggle)
        self.add_widget(appearance_box)

        theme = QLabel(
            "design        ink on paper · 1px hairlines · one family, one weight"
        )
        theme.setObjectName("ResultLabel")
        theme.setWordWrap(True)
        self.add_widget(theme)

        self.add_stretch()

    def sync_theme(self, theme: str) -> None:
        """Reflect an externally toggled theme (sidebar / shortcut)."""
        try:
            self._theme_combo.blockSignals(True)
            self._theme_combo.setCurrentIndex(1 if theme == "dark" else 0)
        finally:
            self._theme_combo.blockSignals(False)

    def _apply_theme_choice(self) -> None:
        theme = self._theme_combo.currentData() or "light"
        self._prefs.set_theme(str(theme))
        self._apply_current_look()

    def _apply_accent_choice(self) -> None:
        accent = self._accent_combo.currentData() or "mono"
        self._prefs.set_accent(str(accent))
        self._apply_current_look()

    def _apply_current_look(self) -> None:
        app = QApplication.instance()
        if app is not None:
            from app.gui.utils.theme import current_accent

            theme = self._prefs.get_theme()
            accent = self._prefs.get_accent(current_accent(app))
            apply_theme(app, theme, accent)

    def _toggle_theme_button(self) -> None:
        window = self.window()
        if window is not None and hasattr(window, "toggle_theme"):
            window.toggle_theme()
        else:
            self._apply_theme_choice()