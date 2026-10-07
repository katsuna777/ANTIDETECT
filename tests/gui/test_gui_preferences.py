from __future__ import annotations

from antidetect.gui.preferences import Preferences


class _Setting:
    def __init__(self, value):
        self.value = value


class _Store:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return _Setting(self.data[key]) if key in self.data else None

    def set(self, key, value):
        self.data[key] = value


def test_string_and_bool_roundtrip():
    prefs = Preferences(_Store())
    assert prefs.get("x", "d") == "d"
    prefs.set("x", "v")
    assert prefs.get("x") == "v"
    assert prefs.get_bool("flag", default=True) is True
    prefs.set_bool("flag", False)
    assert prefs.get_bool("flag", default=True) is False


def test_theme_accepts_light_dark_system_only():
    prefs = Preferences(_Store())
    assert prefs.get_theme() == "system"
    for value in ("light", "dark", "system"):
        prefs.set_theme(value)
        assert prefs.get_theme() == value
    prefs.set_theme("neon")
    assert prefs.get_theme() == "system"


def test_language_normalizes():
    prefs = Preferences(_Store())
    assert prefs.get_language() == "en"
    prefs.set_language("Русский")
    assert prefs.get_language() == "ru"


def test_geometry_missing_value_is_not_restored():
    class _Widget:
        def restoreGeometry(self, _data):  # pragma: no cover
            raise AssertionError("must not be called")

    assert Preferences(_Store()).load_geometry(_Widget()) is False
