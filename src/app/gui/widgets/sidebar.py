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

SECTION_PROFILES = "profiles"
SECTION_PROXIES = "proxies"
SECTION_CONFIGURATIONS = "configurations"
SECTION_SETTINGS = "settings"
SECTION_LOGS = "logs"

# Frequency-ordered: work first, observability next, app prefs last.
_SECTIONS = (
    (SECTION_PROFILES, "PROFILES", "Browser profiles · list, launch, edit (1)"),
    (SECTION_PROXIES, "PROXIES", "Proxy pool · refresh, check, lookup IP (2)"),
    (SECTION_CONFIGURATIONS, "CONFIGURATIONS", "Fingerprints · generate, reuse (3)"),
    (SECTION_LOGS, "LOG", "Live session log · export, clear (4)"),
    (SECTION_SETTINGS, "SETTINGS", "App preferences · theme, confirmations (5)"),
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
        for index, (key, label, tip) in enumerate(_SECTIONS):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tip)
            self._group.addButton(button, index)
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self._theme_button = QPushButton("◐  DARK")
        self._theme_button.setObjectName("NavButton")
        self._theme_button.setCheckable(False)
        self._theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_button.setToolTip("Switch light / dark theme (T)")
        self._theme_button.clicked.connect(self.themeToggleRequested.emit)
        layout.addWidget(self._theme_button)

        footer = QLabel("GUI · MONO LEDGER")
        footer.setObjectName("SidebarFooter")
        footer.setContentsMargins(24, 12, 24, 12)
        layout.addWidget(footer)

        self._group.idClicked.connect(self._on_clicked)

    def select(self, key: str) -> None:
        """Switch the highlighted section without re-emission (programmatic)."""
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def set_theme_label(self, theme: str) -> None:
        """Reflect the active theme on the toggle button (○ light / ● dark)."""
        if theme == "dark":
            self._theme_button.setText("●  LIGHT")
        else:
            self._theme_button.setText("◐  DARK")

    def _on_clicked(self, index: int) -> None:
        key = _SECTIONS[index][0]
        self.sectionRequested.emit(key)
