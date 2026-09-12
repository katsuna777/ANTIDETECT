"""Accent foregrounds + wrapping control rows."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from app.gui.utils.flow_layout import FlowLayout, make_flow_row
from app.gui.utils.preferences import Preferences
from app.gui.utils.theme import (
    ACCENTS,
    apply_theme,
    build_stylesheet,
    current_accent,
    normalize_accent,
    palette_for,
    toggle_theme,
)

pytestmark = pytest.mark.usefixtures("qapp")


# ------------------------------------------------------------------ accents


def test_normalize_accent_falls_back_to_mono():
    assert normalize_accent("yellow") == "yellow"
    assert normalize_accent("BLUE") == "blue"
    assert normalize_accent("green") == "green"
    assert normalize_accent(None) == "mono"
    assert normalize_accent("magenta") == "mono"


def test_mono_palette_is_unchanged():
    assert palette_for("light", "mono").ink == "#000000"
    assert palette_for("dark", "mono").ink == "#f5f5f5"
    assert palette_for("light").paper == "#ffffff"
    assert palette_for("dark").paper == "#0e0e0e"


@pytest.mark.parametrize("accent", ["yellow", "blue", "green"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_accent_replaces_ink_but_keeps_paper(theme, accent):
    pal = palette_for(theme, accent)
    assert pal.ink == ACCENTS[accent]
    base = palette_for(theme, "mono")
    assert pal.paper == base.paper
    assert pal.ink in build_stylesheet(theme=theme, accent=accent)


def test_accent_selection_text_contrasts_fill():
    # Yellow fill must carry dark text in both modes (white-on-yellow on
    # light paper would be unreadable).
    assert palette_for("light", "yellow").selection_ink != "#ffffff"
    assert palette_for("dark", "yellow").selection_ink == "#0e0e0e"


def test_toggle_theme_keeps_accent():
    app = QApplication.instance()
    apply_theme(app, "dark", "yellow")
    assert toggle_theme(app) == "light"
    assert current_accent(app) == "yellow"
    assert "#FFD60A" in app.styleSheet()
    assert current_accent(None) == "mono"


def test_accent_preference_roundtrip(gui_container):
    prefs = Preferences(gui_container.settings)
    assert prefs.get_accent() == "mono"
    prefs.set_accent("green")
    assert prefs.get_accent() == "green"
    prefs.set_accent("ultraviolet")
    assert prefs.get_accent() == "mono"


def test_settings_page_offers_four_accents(gui_container):
    from app.gui.widgets.pages.settings_page import SettingsPage

    page = SettingsPage(gui_container)
    values = [
        page._accent_combo.itemData(i)
        for i in range(page._accent_combo.count())
    ]
    assert values == ["mono", "yellow", "blue", "green"]


# ------------------------------------------------------------------ flow rows


def _fixed_widget(width: int, height: int = 30) -> QWidget:
    # QPushButton reports a text-driven sizeHint (unlike QLabel, whose hint
    # ignores setFixedSize) — pad the caption so the hint is ~width px.
    widget = QPushButton("·" * max(1, width // 8))
    widget.setFixedSize(width, height)
    widget.setSizePolicy(
        widget.sizePolicy().Policy.Maximum, widget.sizePolicy().Policy.Fixed
    )
    return widget


def test_flow_row_wraps_on_narrow_width():
    row = make_flow_row(
        _fixed_widget(200), _fixed_widget(200), _fixed_widget(200)
    )
    assert isinstance(row, FlowLayout)
    assert row.hasHeightForWidth() is True
    single_line = row.heightForWidth(700)
    wrapped = row.heightForWidth(250)
    assert wrapped > single_line


def test_flow_row_skips_hidden_widgets_at_placement():
    from PySide6.QtCore import QRect

    visible = _fixed_widget(200)
    hidden = _fixed_widget(200)
    hidden.hide()
    row = make_flow_row(visible, hidden)
    row.setGeometry(QRect(0, 0, 700, 100))
    assert visible.geometry().width() == 200
    # Hidden widget is never placed: keeps its default (0, 0) position
    # instead of taking the second slot at x=212.
    assert hidden.pos().x() == 0


def test_configurations_page_uses_flow_rows(gui_container):
    from app.gui.widgets.pages.configurations_page import ConfigurationsPage
    from app.gui.workers.task_runner import TaskRunner

    page = ConfigurationsPage(gui_container, TaskRunner())
    assert page._generate is not None
    assert page._timezone_filter.count() > 40
    assert isinstance(page._new, QPushButton)
    page.close()
