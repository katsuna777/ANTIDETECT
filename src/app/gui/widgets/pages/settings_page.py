"""Settings page: runtime info, safety, appearance and interface language."""

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

from app.gui.i18n import get_language, set_language, tr
from app.gui.utils.preferences import Preferences
from app.gui.utils.theme import apply_theme
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container


class SettingsPage(PlaceholderPage):
    def __init__(self, container: "Container", parent=None) -> None:
        # Scrollable like every other page: on short windows the appearance
        # combos must scroll into view, never squeeze into unreadable stubs.
        super().__init__(tr("settings.title"), kicker=tr("settings.kicker"))
        self._container = container
        self._prefs = Preferences(container.settings)

        self._runtime_box = QGroupBox(tr("settings.runtime"))
        runtime_layout = QVBoxLayout(self._runtime_box)
        self._runtime = QLabel()
        self._runtime.setObjectName("ResultLabel")
        self._runtime.setWordWrap(True)
        self._runtime.setTextInteractionFlags(
            self._runtime.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        runtime_layout.addWidget(self._runtime)
        self.add_widget(self._runtime_box)

        self._safety_box = QGroupBox(tr("settings.safety"))
        safety_layout = QVBoxLayout(self._safety_box)
        self._confirm = QCheckBox(tr("settings.confirm"))
        self._confirm.setToolTip(tr("settings.confirm.tip"))
        self._confirm.setChecked(
            self._prefs.get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, default=True)
        )
        self._confirm.toggled.connect(self._apply_confirm_choice)
        safety_layout.addWidget(self._confirm)
        self._safety_hint = QLabel(tr("settings.safety.hint"))
        self._safety_hint.setObjectName("HintLabel")
        safety_layout.addWidget(self._safety_hint)
        self.add_widget(self._safety_box)

        self._appearance_box = QGroupBox(tr("settings.appearance"))
        appearance_layout = QVBoxLayout(self._appearance_box)
        self._theme_combo = QComboBox()
        self._theme_combo.addItem(tr("settings.theme.light"), "light")
        self._theme_combo.addItem(tr("settings.theme.dark"), "dark")
        self._theme_combo.setToolTip(tr("settings.theme.tip"))
        current = self._prefs.get_theme()
        self._theme_combo.setCurrentIndex(1 if current == "dark" else 0)
        self._theme_combo.currentIndexChanged.connect(self._apply_theme_choice)
        appearance_layout.addWidget(self._theme_combo)
        self._accent_combo = QComboBox()
        for accent in Preferences.ACCENTS:
            self._accent_combo.addItem(tr(f"settings.accent.{accent}"), accent)
        self._accent_combo.setToolTip(tr("settings.accent.tip"))
        accent_index = list(Preferences.ACCENTS).index(self._prefs.get_accent())
        self._accent_combo.setCurrentIndex(accent_index)
        self._accent_combo.currentIndexChanged.connect(self._apply_accent_choice)
        appearance_layout.addWidget(self._accent_combo)
        self._appearance_hint = QLabel(tr("settings.appearance.hint"))
        self._appearance_hint.setObjectName("HintLabel")
        self._appearance_hint.setWordWrap(True)
        appearance_layout.addWidget(self._appearance_hint)
        self._theme_toggle = QPushButton(tr("settings.toggle"))
        self._theme_toggle.setToolTip(tr("settings.toggle.tip"))
        self._theme_toggle.clicked.connect(self._toggle_theme_button)
        appearance_layout.addWidget(self._theme_toggle)
        self.add_widget(self._appearance_box)

        self._language_box = QGroupBox(tr("settings.language"))
        language_layout = QVBoxLayout(self._language_box)
        self._language_combo = QComboBox()
        self._language_combo.addItem(tr("settings.language.english"), "en")
        self._language_combo.addItem(tr("settings.language.russian"), "ru")
        self._language_combo.setToolTip(tr("settings.language.tip"))
        stored_lang = self._prefs.get_language(get_language())
        set_language(stored_lang)
        self._language_combo.setCurrentIndex(1 if stored_lang == "ru" else 0)
        self._language_combo.currentIndexChanged.connect(self._apply_language_choice)
        language_layout.addWidget(self._language_combo)
        self._language_hint = QLabel(tr("settings.language.hint"))
        self._language_hint.setObjectName("HintLabel")
        self._language_hint.setWordWrap(True)
        language_layout.addWidget(self._language_hint)
        self.add_widget(self._language_box)

        self._design = QLabel(tr("settings.design"))
        self._design.setObjectName("ResultLabel")
        self._design.setWordWrap(True)
        self.add_widget(self._design)

        self.add_stretch()
        self._refresh_runtime()

    # ------------------------------------------------------------ retranslate

    def retranslate(self) -> None:
        """Re-apply every caption for the current language (no font change)."""
        self.set_title(tr("settings.title"), tr("settings.kicker"))
        self._runtime_box.setTitle(tr("settings.runtime"))
        self._refresh_runtime()
        self._safety_box.setTitle(tr("settings.safety"))
        self._confirm.setText(tr("settings.confirm"))
        self._confirm.setToolTip(tr("settings.confirm.tip"))
        self._safety_hint.setText(tr("settings.safety.hint"))
        self._appearance_box.setTitle(tr("settings.appearance"))
        self._theme_combo.blockSignals(True)
        try:
            theme_data = [self._theme_combo.itemData(i) for i in range(self._theme_combo.count())]
            self._theme_combo.clear()
            self._theme_combo.addItem(tr("settings.theme.light"), "light")
            self._theme_combo.addItem(tr("settings.theme.dark"), "dark")
            current = self._prefs.get_theme()
            self._theme_combo.setCurrentIndex(1 if current == "dark" else 0)
        finally:
            self._theme_combo.blockSignals(False)
        self._theme_combo.setToolTip(tr("settings.theme.tip"))
        self._accent_combo.blockSignals(True)
        try:
            current_accent = self._prefs.get_accent()
            self._accent_combo.clear()
            for accent in Preferences.ACCENTS:
                self._accent_combo.addItem(tr(f"settings.accent.{accent}"), accent)
            try:
                self._accent_combo.setCurrentIndex(list(Preferences.ACCENTS).index(current_accent))
            except ValueError:
                self._accent_combo.setCurrentIndex(0)
        finally:
            self._accent_combo.blockSignals(False)
        self._accent_combo.setToolTip(tr("settings.accent.tip"))
        self._appearance_hint.setText(tr("settings.appearance.hint"))
        self._theme_toggle.setText(tr("settings.toggle"))
        self._theme_toggle.setToolTip(tr("settings.toggle.tip"))
        self._language_box.setTitle(tr("settings.language"))
        self._language_combo.blockSignals(True)
        try:
            self._language_combo.clear()
            self._language_combo.addItem(tr("settings.language.english"), "en")
            self._language_combo.addItem(tr("settings.language.russian"), "ru")
            self._language_combo.setCurrentIndex(1 if get_language() == "ru" else 0)
        finally:
            self._language_combo.blockSignals(False)
        self._language_combo.setToolTip(tr("settings.language.tip"))
        self._language_hint.setText(tr("settings.language.hint"))
        self._design.setText(tr("settings.design"))

    def _refresh_runtime(self) -> None:
        auto = tr("settings.runtime.auto")
        self._runtime.setText(
            tr(
                "settings.runtime.text",
                data=str(self._container.config.data_dir),
                db=str(self._container.config.database_path),
                chrome=str(self._container.config.chromium_path or auto),
            )
        )

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
        theme_name = tr("log.theme.dark") if theme == "dark" else tr("log.theme.light")
        self._container.logs.info("gui", tr("log.theme", theme=theme_name))
        self._apply_current_look()

    def _apply_accent_choice(self) -> None:
        accent = self._accent_combo.currentData() or "mono"
        self._prefs.set_accent(str(accent))
        self._container.logs.info("gui", tr("log.accent", accent=str(accent)))
        self._apply_current_look()

    def _apply_language_choice(self) -> None:
        code = self._language_combo.currentData() or "en"
        code = "ru" if str(code) == "ru" else "en"
        self._prefs.set_language(code)
        set_language(code)
        lang_name = tr("log.language.name.ru") if code == "ru" else tr("log.language.name.en")
        # Log the switch itself (in the new language, as required).
        self._container.logs.info("gui", tr("log.language", lang=lang_name))
        window = self.window()
        if window is not None and hasattr(window, "retranslate"):
            try:
                window.retranslate()
            except Exception:
                self.retranslate()
        else:
            self.retranslate()

    def _apply_current_look(self) -> None:
        app = QApplication.instance()
        if app is not None:
            from app.gui.utils.theme import current_accent

            theme = self._prefs.get_theme()
            accent = self._prefs.get_accent(current_accent(app))
            apply_theme(app, theme, accent)

    def _apply_confirm_choice(self, checked: bool) -> None:
        self._prefs.set_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, checked)
        self._container.logs.info(
            "gui",
            tr("log.confirm.on") if checked else tr("log.confirm.off"),
        )

    def _toggle_theme_button(self) -> None:
        window = self.window()
        if window is not None and hasattr(window, "toggle_theme"):
            window.toggle_theme()
        else:
            self._apply_theme_choice()
