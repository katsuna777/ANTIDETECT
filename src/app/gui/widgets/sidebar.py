"""Left navigation rail.

Presented as a flat index of the sections (Profiles, Proxies,
Configurations, Log, Settings). The current section is shown as a filled
bar (text inverts); everything else is plain text on paper with no fill.

Order is task-frequency first, utility last: daily work (Profiles →
Proxies → Configurations) sits on top, the live Log follows, and Settings
is pinned to the bottom as an app-level utility.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.utils.theme import SIDEBAR_WIDTH
from app.gui.i18n import tr

SECTION_PROFILES = "profiles"
SECTION_PROXIES = "proxies"
SECTION_CONFIGURATIONS = "configurations"
SECTION_SETTINGS = "settings"
SECTION_LOGS = "logs"

# Frequency-ordered: work first, observability next, app prefs last.
_SECTIONS = (
    (SECTION_PROFILES, "sidebar.profiles", "sidebar.tip.profiles"),
    (SECTION_PROXIES, "sidebar.proxies", "sidebar.tip.proxies"),
    (SECTION_CONFIGURATIONS, "sidebar.configurations", "sidebar.tip.configurations"),
    (SECTION_LOGS, "sidebar.log", "sidebar.tip.log"),
    (SECTION_SETTINGS, "sidebar.settings", "sidebar.tip.settings"),
)


class Sidebar(QWidget):
    """The fixed-width navigation column of the main window.

    Emits :attr:`sectionRequested` whenever the user selects a section and
    :attr:`themeToggleRequested` when the theme button is pressed.
    """

    sectionRequested = Signal(str)
    themeToggleRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QLabel("ANTIDETECT")
        brand.setObjectName("BrandMark")
        brand.setContentsMargins(24, 24, 24, 8)
        layout.addWidget(brand)

        rule = QFrame()
        rule.setObjectName("Hairline")
        rule.setContentsMargins(24, 0, 24, 0)
        layout.addWidget(rule)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._keys: list[str] = []
        for index, (key, label_key, tip_key) in enumerate(_SECTIONS):
            button = QPushButton(tr(label_key))
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tr(tip_key))
            self._group.addButton(button, index)
            self._buttons[key] = button
            self._keys.append(key)
            layout.addWidget(button)

        layout.addStretch(1)

        self._theme_button = QPushButton(tr("sidebar.theme.dark"))
        self._theme_button.setObjectName("NavButton")
        self._theme_button.setCheckable(False)
        self._theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_button.setToolTip(tr("sidebar.theme.tip"))
        self._theme_button.clicked.connect(self.themeToggleRequested.emit)
        layout.addWidget(self._theme_button)

        footer = QLabel(tr("sidebar.footer"))
        footer.setObjectName("SidebarFooter")
        footer.setContentsMargins(24, 12, 24, 12)
        layout.addWidget(footer)
        self._footer = footer
        self._theme_name = "light"

        self._group.idClicked.connect(self._on_clicked)

    def retranslate(self, theme: str | None = None) -> None:
        """Re-apply all captions for the current language."""
        if theme is not None:
            self._theme_name = theme
        for key, label_key, tip_key in _SECTIONS:
            button = self._buttons.get(key)
            if button is not None:
                button.setText(tr(label_key))
                button.setToolTip(tr(tip_key))
        self.set_theme_label(self._theme_name)
        self._theme_button.setToolTip(tr("sidebar.theme.tip"))
        self._footer.setText(tr("sidebar.footer"))

    def select(self, key: str) -> None:
        """Switch the highlighted section without re-emission (programmatic)."""
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def set_theme_label(self, theme: str) -> None:
        """Reflect the active theme on the toggle button (○ light / ● dark)."""
        self._theme_name = theme
        if theme == "dark":
            self._theme_button.setText(tr("sidebar.theme.light"))
        else:
            self._theme_button.setText(tr("sidebar.theme.dark"))

    def _on_clicked(self, index: int) -> None:
        key = _SECTIONS[index][0]
        self.sectionRequested.emit(key)
