"""Colour tokens. One neutral scale, one accent, status colours only for status."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

THEMES = ("light", "dark", "system")


@dataclass(frozen=True)
class Palette:
    name: str
    window: str          # the canvas behind everything; the sidebar sits directly on it
    sidebar: str
    surface: str         # the content sheet, cards, table
    raised: str          # inputs, menus, popovers
    subtle: str          # segmented track, chips, disabled fill
    hover: str           # row / button hover
    border: str
    border_strong: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_soft: str     # selection, callouts
    accent_text: str     # text on accent fills
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    danger_text: str     # text on a solid danger fill
    inverse: str         # toast background
    inverse_text: str
    nav_selected: str    # the active sidebar row
    pill: str            # fill of the little cards inside table rows
    pill_border: str
    drawer: str          # the card of a row that is opened into its drawer

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    @property
    def shadow(self) -> int:
        """Alpha (0-255) of the soft drop shadow under the little cards; none on black, where it would not show."""
        return 0 if self.is_dark else 22


LIGHT = Palette(
    name="light",
    window="#F4F4F6", sidebar="#F4F4F6", surface="#FFFFFF", raised="#FFFFFF",
    subtle="#F0F0F3", hover="#F6F6F8",
    border="#E8E8EC", border_strong="#D8D8DE",
    text="#0F0F12", muted="#62626C", faint="#9A9AA5",
    accent="#2F5BF0", accent_hover="#2548D2", accent_soft="#EDEDF1", accent_text="#FFFFFF",
    success="#118A4C", success_soft="#E3F5EB",
    warning="#A85B09", warning_soft="#FDF1DD",
    danger="#D12B20", danger_soft="#FCEAE8", danger_text="#FFFFFF",
    inverse="#171A20", inverse_text="#F5F6F8",
    nav_selected="#E8E8EC", pill="#FFFFFF", pill_border="#ECECF0", drawer="#F7F7F9",
)

# True black: every surface is a pure neutral grey (R = G = B) so nothing reads as navy or
# slate; the only blue left is the accent itself (primary button, focus ring).
DARK = Palette(
    name="dark",
    window="#000000", sidebar="#000000", surface="#0B0B0B", raised="#1A1A1A",
    subtle="#141414", hover="#151515",
    border="#222222", border_strong="#343434",
    text="#EDEDED", muted="#A0A0A0", faint="#6E6E6E",
    accent="#6188FF", accent_hover="#7C9BFF", accent_soft="#262626", accent_text="#000000",
    success="#3BD283", success_soft="#0E2418",
    warning="#E8A648", warning_soft="#2A200C",
    danger="#F2675F", danger_soft="#2C1514", danger_text="#000000",
    inverse="#EDEDED", inverse_text="#000000",
    nav_selected="#1C1C1C", pill="#141414", pill_border="#242424", drawer="#101010",
)

_PALETTES = {"light": LIGHT, "dark": DARK}


def normalize_theme(name: str | None) -> str:
    value = (name or "system").strip().lower()
    return value if value in THEMES else "system"


def resolve_theme(name: str | None, app: QApplication | None = None) -> str:
    """``system`` becomes ``light`` or ``dark`` from the OS colour scheme."""
    value = normalize_theme(name)
    if value != "system":
        return value
    app = app or QApplication.instance()
    try:
        return "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception:
        return "light"


def palette_named(name: str) -> Palette:
    return _PALETTES.get(name, LIGHT)
