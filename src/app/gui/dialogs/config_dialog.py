"""Configuration create/edit dialog: manual fingerprint with timezone picker."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from app.application.configuration_generator import (
    SUPPORTED_LANGUAGES,
    country_defaults,
)
from app.application.profile_doctor import (
    SUPPORTED_TIMEZONES,
    TIMEZONE_COUNTRY,
    locale_country,
)
from app.gui.i18n import tr

_PLATFORMS = ["windows", "macos", "linux"]


class ConfigDialog(QDialog):
    """Create a custom configuration (``config is None``) or edit one."""

    def __init__(self, config=None, parent=None) -> None:
        super().__init__(parent)
        creating = config is None
        self.setWindowTitle(
            tr("dlg.config.new.title") if creating else tr("dlg.config.edit.title", name=config.name)
        )
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel(
            tr("dlg.config.new.header") if creating else tr("dlg.config.edit.header", id=config.id, name=config.name)
        )
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        subtitle = QLabel(tr("dlg.config.subtitle"))
        subtitle.setObjectName("HintLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self._syncing = False

        identity = QGroupBox(tr("dlg.group.identity"))
        identity_form = QFormLayout(identity)
        identity_form.setSpacing(10)

        self._name = QLineEdit("" if creating else (config.name or ""))
        self._name.setPlaceholderText(tr("dlg.config.name.ph"))
        self._name.setToolTip(tr("dlg.config.name.tip"))
        self._name.setClearButtonEnabled(True)
        identity_form.addRow(tr("dlg.name"), self._name)

        self._name_error = QLabel("")
        self._name_error.setObjectName("ErrorLabel")
        self._name_error.hide()
        identity_form.addRow("", self._name_error)
        layout.addWidget(identity)

        fingerprint = QGroupBox(tr("dlg.group.fingerprint"))
        fingerprint_form = QFormLayout(fingerprint)
        fingerprint_form.setSpacing(10)

        self._platform = QComboBox()
        self._platform.setToolTip(tr("dlg.platform.tip"))
        self._platform.addItem("—", None)
        for platform in _PLATFORMS:
            self._platform.addItem(platform, platform)
        if not creating:
            self._select(self._platform, config.platform)
        fingerprint_form.addRow(tr("dlg.platform"), self._platform)

        self._language = QComboBox()
        self._language.setEditable(True)
        self._language.setToolTip(tr("dlg.language.tip"))
        self._language.addItem("—")
        for language in SUPPORTED_LANGUAGES:
            self._language.addItem(language)
        self._language.setMaxVisibleItems(self._language.count())
        if not creating and config.language:
            if config.language in SUPPORTED_LANGUAGES:
                self._select_text(self._language, config.language)
            else:
                self._language.setCurrentText(config.language)
        fingerprint_form.addRow(tr("dlg.language"), self._language)

        self._locale = QLineEdit("" if creating else (config.locale or ""))
        self._locale.setPlaceholderText(tr("dlg.locale.ph"))
        self._locale.setToolTip(tr("dlg.locale.tip"))
        fingerprint_form.addRow(tr("dlg.locale"), self._locale)

        self._timezone = QComboBox()
        self._timezone.setToolTip(tr("dlg.timezone.tip"))
        self._timezone.addItem("—", None)
        for zone in SUPPORTED_TIMEZONES:
            self._timezone.addItem(zone, zone)
        if not creating:
            self._select(self._timezone, config.timezone)
        fingerprint_form.addRow(tr("dlg.timezone"), self._timezone)
        geo_hint = QLabel(tr("dlg.geo.hint"))
        geo_hint.setObjectName("HintLabel")
        fingerprint_form.addRow("", geo_hint)
        layout.addWidget(fingerprint)

        screen = QGroupBox(tr("dlg.group.screen"))
        screen_form = QFormLayout(screen)
        screen_form.setSpacing(10)

        self._width = QSpinBox()
        self._width.setRange(0, 7680)
        self._width.setSpecialValueText("—")
        self._width.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._width.setValue(config.screen_width if not creating and config.screen_width else 0)
        self._width.setToolTip(tr("dlg.width.tip"))
        screen_form.addRow(tr("dlg.width"), self._width)

        self._height = QSpinBox()
        self._height.setRange(0, 4320)
        self._height.setSpecialValueText("—")
        self._height.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._height.setValue(config.screen_height if not creating and config.screen_height else 0)
        self._height.setToolTip(tr("dlg.height.tip"))
        screen_form.addRow(tr("dlg.height"), self._height)

        screen_hint = QLabel(tr("dlg.screen.hint"))
        screen_hint.setObjectName("HintLabel")
        screen_form.addRow("", screen_hint)
        layout.addWidget(screen)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("PrimaryButton")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._name.textChanged.connect(self._validate)
        self._timezone.currentIndexChanged.connect(self._sync_from_timezone)
        self._locale.textChanged.connect(self._sync_from_locale)
        self._validate()

    # ------------------------------------------------------------ values

    @property
    def name(self) -> str:
        return self._name.text().strip()

    def values(self) -> dict:
        language = self._language.currentText().strip()
        if not language or language == "—":
            language = None
        locale = self._locale.text().strip() or None
        width = self._width.value() or None
        height = self._height.value() or None
        return {
            "name": self.name,
            "platform": self._platform.currentData(),
            "language": language,
            "locale": locale,
            "timezone": self._timezone.currentData(),
            "screen_width": width,
            "screen_height": height,
        }

    # ------------------------------------------------------------ validation

    def _validate(self) -> None:
        ok = bool(self.name)
        save = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setEnabled(ok)
        if ok:
            self._name_error.hide()
        else:
            self._name_error.setText(tr("dlg.config.name.empty"))
            self._name_error.show()

    # ------------------------------------------------------------ geo sync

    def _sync_from_timezone(self) -> None:
        if self._syncing:
            return
        timezone = self._timezone.currentData()
        if not timezone:
            return
        country = TIMEZONE_COUNTRY.get(timezone)
        defaults = country_defaults(country) if country else None
        if defaults is not None:
            _language, locale, _timezone = defaults
            self._apply_geo(locale=locale, timezone=timezone)

    def _sync_from_locale(self) -> None:
        if self._syncing:
            return
        country = locale_country(self._locale.text().strip())
        defaults = country_defaults(country) if country else None
        if defaults is not None:
            _language, _locale, timezone = defaults
            self._apply_geo(timezone=timezone)

    def _apply_geo(self, locale: str | None = None, timezone: str | None = None) -> None:
        self._syncing = True
        try:
            if locale is not None:
                self._locale.setText(locale)
            if timezone is not None:
                self._select(self._timezone, timezone)
        finally:
            self._syncing = False

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _select_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
