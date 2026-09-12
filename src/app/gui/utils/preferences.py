"""GUI preference persistence through the existing settings layer.

Stores key/value preferences via the SettingsRepository exposed on the
:class:`app.di.Container` — the GUI never opens the SQLite connection itself.
The namespace prefix ``gui.`` keeps GUI preferences separate from any future
server/CLI settings.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QWidget


class SettingsRepository(Protocol):
    """The subset of the settings contract the GUI's preferences need."""

    def get(self, key: str):  # pragma: no cover - protocol
        ...

    def set(self, key: str, value: str | None) -> None:  # pragma: no cover
        ...


class Preferences:
    """Typed getter/setter facade over a settings repository.

    All values are persisted as plain strings, matching the application's
    settings table. Typed helpers parse/format on top.
    """

    KEY_WINDOW_GEOMETRY = "gui.window_geometry"
    KEY_CONFIRM_DESTRUCTIVE = "gui.confirm_destructive"
    KEY_THEME = "gui.theme"
    THEME_LIGHT = "light"
    THEME_DARK = "dark"

    def __init__(self, settings: SettingsRepository) -> None:
        self._settings = settings

    # ------------------------------------------------------------- raw

    def get(self, key: str, default: str = "") -> str:
        setting = self._settings.get(key)
        return setting.value if setting is not None and setting.value is not None else default

    def set(self, key: str, value: str) -> None:
        self._settings.set(key, value)

    # ------------------------------------------------------------- bool

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        if raw == "":
            return default
        return raw.lower() in ("1", "true", "yes", "on")

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, "1" if value else "0")

    # ------------------------------------------------------------- theme

    def get_theme(self, default: str = THEME_LIGHT) -> str:
        """Stored color theme: ``'light'`` or ``'dark'`` (fallback to default)."""
        raw = self.get(self.KEY_THEME).strip().lower()
        if raw in (self.THEME_LIGHT, self.THEME_DARK):
            return raw
        return default

    def set_theme(self, theme: str) -> None:
        normalized = theme.strip().lower()
        if normalized not in (self.THEME_LIGHT, self.THEME_DARK):
            normalized = self.THEME_LIGHT
        self.set(self.KEY_THEME, normalized)

    # ---------------------------------------------------------- geometry

    def load_geometry(self, widget: QWidget) -> bool:
        """Restore ``widget``'s saved geometry; ``False`` when nothing stored."""
        raw = self.get(self.KEY_WINDOW_GEOMETRY)
        if not raw:
            return False
        try:
            restored = widget.restoreGeometry(bytes.fromhex(raw))
        except ValueError:
            return False
        return bool(restored)

    def save_geometry(self, widget: QWidget) -> None:
        self.set(self.KEY_WINDOW_GEOMETRY, bytes(widget.saveGeometry()).hex())