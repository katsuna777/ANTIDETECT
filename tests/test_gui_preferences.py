"""Preferences adapter: typed key/value persistence over the settings layer."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from app.gui.utils.preferences import Preferences

pytestmark = pytest.mark.usefixtures("qapp")


def test_string_roundtrip(gui_container):
    prefs = Preferences(gui_container.settings)
    prefs.set("gui.demo_value", "hello")
    assert prefs.get("gui.demo_value") == "hello"


def test_bool_roundtrip(gui_container):
    prefs = Preferences(gui_container.settings)
    assert prefs.get_bool("gui.demo_flag", default=False) is False
    prefs.set_bool("gui.demo_flag", True)
    assert prefs.get_bool("gui.demo_flag") is True
    prefs.set_bool("gui.demo_flag", False)
    assert prefs.get_bool("gui.demo_flag") is False


def test_missing_value_falls_back(gui_container):
    prefs = Preferences(gui_container.settings)
    assert prefs.get("gui.nope", default="fallback") == "fallback"
    assert prefs.get_bool("gui.nope", default=True) is True


def test_geometry_roundtrip_via_existing_settings(gui_container):
    prefs = Preferences(gui_container.settings)
    source = QWidget()
    # Stay inside the 800x800 offscreen virtual desktop to avoid clamping.
    source.setGeometry(40, 40, 400, 300)

    prefs.save_geometry(source)
    restore = QWidget()
    assert prefs.load_geometry(restore) is True
    assert restore.geometry() == source.geometry()


def test_geometry_load_without_stored_value(gui_container):
    prefs = Preferences(gui_container.settings)
    widget = QWidget()
    assert prefs.load_geometry(widget) is False