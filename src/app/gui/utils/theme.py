"""Central theme layer.

Every visual decision of the application lives here: colors, fonts, spacing
and a single application-wide style sheet. Widgets never set their own
``setStyleSheet`` — the theme is applied once per ``QApplication`` via
:func:`apply_theme` and re-applied on every :func:`toggle_theme`.

Themes follow the ``design/`` reference (19–86 studio, a typographic ledger):

* palette is strictly monochrome — Ink on Paper (light) / Paper on Ink (dark);
* the only separator is a 1px hairline; nothing uses radius, shadows or
  gradient depth except the status dot (a full circle);
* hierarchy comes from size and position, never from color or weight.

The reference was written for a web catalog at a 24px body size. A working
desktop application needs additional intermediate scale points for controls
and navigation; those are intentionally drawn from the reference's own font
family (Inter Light) and kept as the *same* monochrome system, so the
identity — one family, one weight, hairline rules — is preserved in both
light and dark modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Literal

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

ThemeName = Literal["light", "dark"]
AccentName = Literal[
    "mono",
    "red",
    "orange",
    "yellow",
    "green",
    "cyan",
    "blue",
    "purple",
    "pink",
    "lime",
]

#: Accent foregrounds. ``mono`` keeps the strict black-on-white /
#: white-on-black ledger; any other accent replaces the foreground ink
#: (text, borders, fills) while the paper background never changes.
ACCENTS: dict[str, str | None] = {
    "mono": None,
    "red": "#FF5A5A",
    "orange": "#FF9F2E",
    "yellow": "#FFD60A",
    "green": "#35D07F",
    "cyan": "#35C4DC",
    "blue": "#3B9DFF",
    "purple": "#B388FF",
    "pink": "#FF6EC7",
    "lime": "#9ACD32",
}

_ACCENT_SELECTION_DARK = "#0e0e0e"  # text on accent fills, dark theme
_ACCENT_SELECTION_LIGHT = "#111111"  # text on accent fills, light theme


@dataclass(frozen=True)
class Palette:
    """One monochrome theme: foreground ink, background paper + derivatives."""

    name: str
    ink: str
    paper: str
    muted: str  # secondary text / borders at 45%
    faint: str  # hairline separators inside lists at 25%
    selection_ink: str  # text on inverted selection
    splash_bg: str
    splash_fg: str


LIGHT = Palette(
    name="light",
    ink="#000000",
    paper="#ffffff",
    muted="rgba(0, 0, 0, 45%)",
    faint="rgba(0, 0, 0, 25%)",
    selection_ink="#ffffff",
    splash_bg="#000000",
    splash_fg="#ffffff",
)

DARK = Palette(
    name="dark",
    ink="#f5f5f5",
    paper="#0e0e0e",
    muted="rgba(245, 245, 245, 55%)",
    faint="rgba(245, 245, 245, 22%)",
    selection_ink="#0e0e0e",
    splash_bg="#0e0e0e",
    splash_fg="#f5f5f5",
)

THEMES: dict[str, Palette] = {"light": LIGHT, "dark": DARK}


def normalize_theme(name: str | None) -> ThemeName:
    normalized = (name or "light").strip().lower()
    if normalized == "dark":
        return "dark"
    return "light"


def normalize_accent(name: str | None) -> AccentName:
    """Stored accent color; unknown values fall back to strict monochrome."""
    normalized = (name or "mono").strip().lower()
    if normalized in ACCENTS and normalized != "mono":
        return normalized  # type: ignore[return-value]
    return "mono"


def _accent_rgba(accent_hex: str, alpha_percent: int) -> str:
    """``#RRGGBB`` + alpha percent -> ``rgba(r, g, b, a%)`` for muted/faint."""
    hex_clean = accent_hex.lstrip("#")
    red = int(hex_clean[0:2], 16)
    green = int(hex_clean[2:4], 16)
    blue = int(hex_clean[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha_percent}%)"


def palette_for(name: str | None, accent: str | None = None) -> Palette:
    """Palette for theme, optionally re-inked with an accent foreground."""
    theme = normalize_theme(name)
    base = THEMES[theme]
    accent_name = normalize_accent(accent)
    accent_hex = ACCENTS[accent_name]
    if accent_hex is None:
        return base
    if theme == "dark":
        muted, faint = _accent_rgba(accent_hex, 55), _accent_rgba(accent_hex, 22)
        selection_ink = _ACCENT_SELECTION_DARK
    else:
        muted, faint = _accent_rgba(accent_hex, 45), _accent_rgba(accent_hex, 25)
        selection_ink = _ACCENT_SELECTION_LIGHT
    return Palette(
        name=base.name,
        ink=accent_hex,
        paper=base.paper,
        muted=muted,
        faint=faint,
        selection_ink=selection_ink,
        splash_bg=base.splash_bg,
        splash_fg=base.splash_fg,
    )

# --------------------------------------------------------------------------- #
# Tokens (light defaults — kept for backwards compatibility)
# --------------------------------------------------------------------------- #

INK = "#000000"
PAPER = "#ffffff"

SPACING_UNIT = 6
SPACING_5 = 5
SPACING_8 = 8
SPACING_12 = 12
SPACING_24 = 24
SPACING_30 = 30

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
WINDOW_MIN_WIDTH = 1000
WINDOW_MIN_HEIGHT = 680
SIDEBAR_WIDTH = 240


def font_family() -> str:
    """Best available face from the design family (Inter → system fallbacks)."""
    installed = {family.lower() for family in QFontDatabase.families()}
    for candidate in ("Inter", "Inter UI", "SF Pro Text", "Helvetica Neue"):
        if candidate.lower() in installed:
            return candidate
    return "Helvetica Neue"


def font_stack(family: str | None = None) -> str:
    """QSS font stack built only from installed faces.

    Qt logs ``Replace uses of missing font family "Inter"`` for every
    stylesheet rule when the stack names a face that is not installed, so
    candidates that are absent on this machine are filtered out instead of
    being listed blindly. The resolved family always comes first.
    """
    resolved = family or font_family()
    try:
        installed = {name.lower() for name in QFontDatabase.families()}
    except Exception:
        installed = {resolved.lower()}
    ordered = [resolved]
    for candidate in (
        "Inter",
        "Inter UI",
        "SF Pro Text",
        "Segoe UI",
        "Roboto",
        "Helvetica Neue",
    ):
        if candidate.lower() in installed:
            if candidate.lower() != resolved.lower():
                ordered.append(candidate)
    # NOTE: no generic "sans-serif" tail — Qt treats the quoted literal as
    # a missing family and logs noise at startup; its built-in fallback
    # already applies when none of the listed faces match.
    return ", ".join(f'"{name}"' for name in ordered)


# --------------------------------------------------------------------------- #
# Style sheet
# --------------------------------------------------------------------------- #

_QSS_TEMPLATE = Template(
    """
* {
    font-family: $font;
    font-size: 14px;
    font-weight: 300;
    color: $ink;
    background: $paper;
}

QWidget {
    outline: none;
}

QLabel { background: transparent; }

QFrame#Hairline {
    background: $ink;
    border: none;
    min-height: 1px;
    max-height: 1px;
}

/* ---------------------------------------------------------------- sidebar */

QWidget#Sidebar {
    background: $paper;
    border-right: 1px solid $ink;
}

QLabel#BrandMark {
    font-size: 22px;
    font-weight: 200;
    color: $ink;
}

QLabel#SidebarHeaderRule {
    color: $ink;
}

QLabel#SidebarFooter {
    font-size: 11px;
    color: $ink;
}

QPushButton#NavButton {
    border: none;
    background: transparent;
    text-align: left;
    padding: 10px 24px;
    font-size: 15px;
    color: $ink;
}

QPushButton#NavButton:hover {
    background: $ink;
    color: $paper;
}

QPushButton#NavButton:checked {
    background: $ink;
    color: $paper;
}

/* -------------------------------------------------------------- pages */

QLabel#PageTitle {
    font-size: 32px;
    font-weight: 200;
    color: $ink;
}

QLabel#PageKicker {
    font-size: 13px;
    font-weight: 300;
    color: $ink;
}

QLabel#MetricValue {
    font-size: 30px;
    font-weight: 200;
    color: $ink;
}

QLabel#MetricLabel {
    font-size: 11px;
    color: $ink;
}

QLabel#ResultLabel {
    font-size: 13px;
    color: $ink;
}

QLabel#HintLabel {
    font-size: 11px;
    color: $muted;
}

QLabel#ErrorLabel {
    font-size: 12px;
    color: $ink;
    border-left: 3px solid $ink;
    padding-left: 8px;
    font-weight: 400;
}

QLabel#EmptyState {
    font-size: 14px;
    color: $muted;
    padding: 24px 0;
}

QLabel#StatusDot {
    background: $ink;
    border-radius: 3px;
}

/* ------------------------------------------------------------- controls */

QPushButton {
    background: transparent;
    color: $ink;
    border: 1px solid $ink;
    border-radius: 0;
    padding: 6px 24px;
    font-size: 13px;
    font-weight: 300;
}

QPushButton:hover:!checked {
    background: $ink;
    color: $paper;
}

QPushButton:pressed {
    background: $ink;
    color: $paper;
}

QPushButton:checked {
    background: $ink;
    color: $paper;
}

QPushButton:disabled {
    color: $muted;
    border-color: $muted;
    background: transparent;
}

QPushButton#PrimaryButton {
    background: $ink;
    color: $paper;
}

QPushButton#DangerButton {
    border-style: dashed;
}

QLineEdit#Invalid, QComboBox#Invalid {
    border: 2px solid $ink;
    border-left-width: 6px;
}

QComboBox, QLineEdit, QSpinBox {
    background: $paper;
    color: $ink;
    border: 1px solid $ink;
    border-radius: 0;
    padding: 5px 12px;
    font-size: 13px;
    selection-background-color: $ink;
    selection-color: $selink;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 2px solid $ink;
    padding: 4px 11px;
}

QComboBox:disabled, QLineEdit:disabled {
    color: $muted;
    border-color: $muted;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background: $paper;
    color: $ink;
    border: 1px solid $ink;
    selection-background-color: $ink;
    selection-color: $selink;
    /* The popup must never render narrower than readable text or with
       collapsed rows, whatever the host style reports as content hints. */
    min-width: 220px;
}

QCheckBox {
    background: transparent;
    spacing: 8px;
    font-size: 13px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid $ink;
    background: $paper;
}

QCheckBox::indicator:checked {
    background: $ink;
}

/* --------------------------------------------------------------- text */

QTextEdit, QPlainTextEdit, QTextBrowser {
    selection-background-color: $ink;
    selection-color: $selink;
}

/* --------------------------------------------------------------- tables */

QTableView {
    background: $paper;
    color: $ink;
    border: 1px solid $ink;
    gridline-color: $ink;
    font-size: 13px;
    selection-background-color: $ink;
    selection-color: $selink;
    alternate-background-color: $paper;
}

QHeaderView::section {
    background: $paper;
    color: $ink;
    border: none;
    border-bottom: 1px solid $ink;
    padding: 6px 12px;
    font-size: 11px;
}

QListWidget, QListView, QTreeView {
    background: $paper;
    color: $ink;
    border: 1px solid $ink;
    outline: none;
    font-size: 13px;
    padding: 4px;
    selection-background-color: $ink;
    selection-color: $selink;
}

QListWidget::item, QListView::item {
    padding: 5px 10px;
    min-height: 22px;
    border: none;
    border-bottom: 1px solid $faint;
    background: transparent;
}

QListWidget::item:selected, QListView::item:selected,
QTreeView::item:selected {
    background: $ink;
    color: $paper;
}

QTableView::item:selected {
    background: $ink;
    color: $paper;
}

QProgressBar {
    background: $paper;
    color: $ink;
    border: 1px solid $ink;
    text-align: center;
    font-size: 12px;
}

QProgressBar::chunk {
    background: $ink;
}

QLabel#DialogTitle {
    font-size: 15px;
    font-weight: 300;
}

QTableCornerButton::section {
    background: $paper;
    border: none;
}

/* ----------------------------------------------------------- progress */

QScrollBar:vertical {
    background: $paper;
    width: 12px;
    border: none;
    border-left: 1px solid $ink;
    margin: 0 0 0 8px;
}

QScrollBar::handle:vertical {
    background: $ink;
    min-height: 24px;
}

QScrollBar:horizontal {
    background: $paper;
    height: 12px;
    border: none;
    border-top: 1px solid $ink;
    margin: 8px 0 0 0;
}

QScrollBar::handle:horizontal {
    background: $ink;
    min-width: 24px;
}

QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* -------------------------------------------------------------- dialogs */

QMessageBox {
    background: $paper;
}

QMessageBox QLabel {
    color: $ink;
    background: transparent;
    font-size: 14px;
}

QMessageBox QPushButton {
    min-width: 80px;
}

QDialog {
    background: $paper;
}

QDialogButtonBox QPushButton {
    min-width: 80px;
}

/* -------------------------------------------------------------- status */

QStatusBar {
    background: $paper;
    color: $ink;
    border-top: 1px solid $ink;
    font-size: 11px;
}

QStatusBar::item {
    border: none;
}

QStatusBar QLabel {
    color: $ink;
}

/* --------------------------------------------------------------- group */

QGroupBox {
    border: 1px solid $ink;
    border-radius: 0;
    margin-top: 24px;
    padding: 20px 12px 16px 12px;
    font-size: 12px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 8px;
}
"""
)

def build_stylesheet(
    family: str | None = None,
    theme: str | None = None,
    accent: str | None = None,
) -> str:
    """Render the style sheet for theme ("light"/"dark") + accent."""
    pal = palette_for(theme, accent)
    return _QSS_TEMPLATE.substitute(
        font=font_stack(family),
        ink=pal.ink,
        paper=pal.paper,
        muted=pal.muted,
        faint=pal.faint,
        selink=pal.selection_ink,
    )


def apply_theme(
    app: QApplication, theme: str | None = None, accent: str | None = None
) -> str:
    """Apply the global theme to ``app; returns the normalized name."""
    name = normalize_theme(theme)
    accent_name = normalize_accent(accent)
    pal = palette_for(name, accent_name)
    family = font_family()
    app.setStyleSheet(build_stylesheet(family, name, accent_name))
    # Selection colors live in the palette, not the style sheet: without
    # this, selected text (error details, labels) keeps the system highlight
    # while QSS forces our ink on top — i.e. invisible selected text.
    palette = QPalette(app.palette())
    palette.setColor(QPalette.ColorRole.Highlight, QColor(pal.ink))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(pal.selection_ink))
    app.setPalette(palette)
    try:
        app.setProperty("antidetectTheme", name)
        app.setProperty("antidetectAccent", accent_name)
    except Exception:
        pass
    default = QFont(family, 13)
    default.setWeight(QFont.Weight.Light)
    app.setFont(default)
    return name


def current_theme(app: QApplication | None = None) -> str:
    """Best-effort current theme name (defaults to light)."""
    try:
        if app is not None:
            value = app.property("antidetectTheme")
            if value in ("light", "dark"):
                return str(value)
    except Exception:
        pass
    return "light"


def current_accent(app: QApplication | None = None) -> str:
    """Best-effort current accent name (defaults to mono)."""
    try:
        if app is not None:
            value = app.property("antidetectAccent")
            if value in ACCENTS:
                return str(value)
    except Exception:
        pass
    return "mono"


def toggle_theme(app: QApplication) -> str:
    """Flip light<->dark on app, keeping the accent; returns the new theme."""
    return apply_theme(
        app,
        "dark" if current_theme(app) != "dark" else "light",
        current_accent(app),
    )