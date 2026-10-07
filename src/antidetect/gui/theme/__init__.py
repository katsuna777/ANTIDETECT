"""Application theme: tokens, style sheet, icons, and the theme-change bus."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

from antidetect.gui.theme.palette import (
    DARK,
    LIGHT,
    THEMES,
    Palette,
    normalize_theme,
    palette_named,
    resolve_theme,
)
from antidetect.gui.theme.stylesheet import build_stylesheet

__all__ = [
    "DARK", "LIGHT", "THEMES", "Palette", "apply_theme", "build_stylesheet", "bus",
    "current_palette", "current_theme", "normalize_theme", "resolve_theme",
]

_WINDOW_FONT_PX = 13
_STYLE_SET = "antidetect.style_set"


class _ThemeBus(QObject):
    """Widgets that draw themselves (icons, delegates) listen here and repaint."""

    #: the style sheet is about to be swapped: let go of anything that is costly to restyle and cheap to rebuild
    aboutToChange = Signal()
    changed = Signal()


bus = _ThemeBus()


def _qpalette(p: Palette) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.window,
        QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.raised,
        QPalette.ColorRole.AlternateBase: p.surface,
        QPalette.ColorRole.Text: p.text,
        QPalette.ColorRole.Button: p.raised,
        QPalette.ColorRole.ButtonText: p.text,
        QPalette.ColorRole.ToolTipBase: p.inverse,
        QPalette.ColorRole.ToolTipText: p.inverse_text,
        QPalette.ColorRole.Highlight: p.accent,
        QPalette.ColorRole.HighlightedText: p.accent_text,
        QPalette.ColorRole.PlaceholderText: p.faint,
        QPalette.ColorRole.Link: p.accent,
    }
    for role, value in roles.items():
        pal.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.faint))
    return pal


@lru_cache(maxsize=None)
def _stylesheet(name: str) -> str:
    return build_stylesheet(palette_named(name))


def _freeze(app: QApplication) -> list[QWidget]:
    """Stop the windows repainting while the style is swapped: they paint once afterwards, not per widget."""
    frozen = [w for w in app.topLevelWidgets() if w.isVisible() and w.updatesEnabled()]
    for widget in frozen:
        widget.setUpdatesEnabled(False)
    return frozen


class _StyleChangeGate(QObject):
    """Keeps a style change away from a scroll area (scroll areas, item views, text edits).

    A ``QScrollArea`` answers one by measuring everything inside it, down to the text layout of every
    wrapped label, and an item view by laying out all its items again (a combo box with 2000 profiles
    in its popup): nearly all of what a theme switch used to cost (1.5 s with the API instruction
    built). A theme changes colours only, never a margin or a border, so there is nothing to re-measure;
    the widgets inside still get their own style change.
    """

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        return event.type() == QEvent.Type.StyleChange


_gate = _StyleChangeGate()


def _gate_scroll_areas(app: QApplication, *, on: bool) -> None:
    for widget in app.allWidgets():
        if isinstance(widget, QAbstractScrollArea):
            (widget.installEventFilter if on else widget.removeEventFilter)(_gate)


def apply_theme(app: QApplication, theme: str | None = "system") -> str:
    """Apply a theme application-wide; returns the resolved ``light`` / ``dark``.

    A style sheet swap restyles every live widget (~0.25 ms each), so each step only runs when it
    changes something: re-selecting the current theme costs nothing, and the Fusion style is set once.
    """
    requested = normalize_theme(theme)
    resolved = resolve_theme(requested, app)
    sheet = _stylesheet(resolved)
    app.setProperty("antidetect.theme", requested)
    if app.styleSheet() == sheet and app.property("antidetect.resolved_theme") == resolved:
        return resolved
    if not app.property(_STYLE_SET):
        # Identical rendering on Windows / macOS / Linux. Replacing the style restyles everything, and once a
        # style sheet is on, ``app.style()`` is Qt's sheet proxy, not Fusion: so remember it ourselves.
        app.setStyle("Fusion")
        app.setProperty(_STYLE_SET, True)
    bus.aboutToChange.emit()
    frozen = _freeze(app)
    _gate_scroll_areas(app, on=True)
    try:
        app.setPalette(_qpalette(palette_named(resolved)))
        app.setStyleSheet(sheet)
        app.setProperty("antidetect.resolved_theme", resolved)
        font = app.font()
        if font.pixelSize() != _WINDOW_FONT_PX:
            font.setPixelSize(_WINDOW_FONT_PX)
            app.setFont(font)
    finally:
        _gate_scroll_areas(app, on=False)
        for widget in frozen:
            widget.setUpdatesEnabled(True)
    bus.changed.emit()
    return resolved


def current_theme(app: QApplication | None = None) -> str:
    """The *requested* theme (``light`` / ``dark`` / ``system``)."""
    app = app or QApplication.instance()
    return normalize_theme(app.property("antidetect.theme") if app is not None else None)


def current_palette(app: QApplication | None = None) -> Palette:
    app = app or QApplication.instance()
    resolved = app.property("antidetect.resolved_theme") if app is not None else None
    return palette_named(resolved or "light")
