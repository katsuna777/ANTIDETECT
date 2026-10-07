"""GUI preference persistence through the existing settings layer.

Preferences live in the same settings table as everything else, under the
``gui.`` prefix, so the GUI never opens SQLite itself.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QWidget

from antidetect.i18n import normalize


class SettingsRepository(Protocol):
    def get(self, key: str): ...   # pragma: no cover

    def set(self, key: str, value: str | None) -> None: ...   # pragma: no cover


class Preferences:
    KEY_WINDOW_GEOMETRY = "gui.window_geometry"
    KEY_CONFIRM_DESTRUCTIVE = "gui.confirm_destructive"
    KEY_THEME = "gui.theme"
    KEY_LANGUAGE = "gui.language"
    KEY_PROFILES_SORT = "gui.profiles_sort"
    KEY_TAGS_COLLAPSED = "gui.tags_collapsed"
    KEY_WORKSPACES_COLLAPSED = "gui.workspaces_collapsed"

    def __init__(self, settings: SettingsRepository) -> None:
        self._settings = settings

    # raw
    def get(self, key: str, default: str = "") -> str:
        setting = self._settings.get(key)
        return setting.value if setting is not None and setting.value is not None else default

    def set(self, key: str, value: str) -> None:
        self._settings.set(key, value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        if raw == "":
            return default
        return raw.lower() in ("1", "true", "yes", "on")

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, "1" if value else "0")

    # theme: "light" | "dark" | "system"
    def get_theme(self, default: str = "system") -> str:
        raw = self.get(self.KEY_THEME).strip().lower()
        return raw if raw in ("light", "dark", "system") else default

    def set_theme(self, theme: str) -> None:
        value = (theme or "").strip().lower()
        self.set(self.KEY_THEME, value if value in ("light", "dark", "system") else "system")

    # language
    def get_language(self, default: str = "en") -> str:
        raw = self.get(self.KEY_LANGUAGE)
        if not raw.strip():
            return default if default in ("en", "ru") else "en"
        return normalize(raw)

    def set_language(self, language: str) -> None:
        self.set(self.KEY_LANGUAGE, normalize(language))

    # table sort: "column:asc" / "column:desc"
    def get_sort(self, key: str, default: tuple[int, bool]) -> tuple[int, bool]:
        raw = self.get(key)
        try:
            column, direction = raw.split(":")
            return int(column), direction == "desc"
        except ValueError:
            return default

    def set_sort(self, key: str, column: int, descending: bool) -> None:
        self.set(key, f"{column}:{'desc' if descending else 'asc'}")

    # window geometry
    def load_geometry(self, widget: QWidget) -> bool:
        raw = self.get(self.KEY_WINDOW_GEOMETRY)
        if not raw:
            return False
        try:
            return bool(widget.restoreGeometry(bytes.fromhex(raw)))
        except ValueError:
            return False

    def save_geometry(self, widget: QWidget) -> None:
        try:
            self.set(self.KEY_WINDOW_GEOMETRY, bytes(widget.saveGeometry().toHex()).decode("ascii"))
        except Exception:
            pass
