"""Accent foregrounds + wrapping control rows."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from app.gui.utils.flow_layout import FlowLayout, glued_pair, make_flow_row
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


@pytest.mark.parametrize("accent", [a for a in ACCENTS if a != "mono"])
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


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("accent", [a for a in ACCENTS])
def test_selection_colors_follow_theme_not_system(theme, accent):
    """Regression: selected error/details text must stay visible.

    Without palette Highlight roles, selected text keeps the system
    highlight under our QSS ink — i.e. invisible selected text.
    """
    from PySide6.QtGui import QColor, QPalette

    from app.gui.utils.theme import palette_for

    app = QApplication.instance()
    apply_theme(app, theme, accent)
    pal = palette_for(theme, accent)
    colors = QApplication.instance().palette()
    assert colors.color(QPalette.ColorRole.Highlight) == QColor(pal.ink)
    assert colors.color(QPalette.ColorRole.HighlightedText) == QColor(
        pal.selection_ink
    )


def test_selected_text_renders_with_contrast():
    """Pixel check: a select-all in a text field paints readable selection."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QTextEdit

    app = QApplication.instance() or QApplication([])
    apply_theme(app, "dark", "yellow")
    editor = QTextEdit()
    try:
        editor.setPlainText("Profile #003 failed pre-launch diagnostics")
        editor.show()
        editor.selectAll()
        app.processEvents()
        image = editor.grab().toImage()
        yellowish = 0
        total = 0
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                pixel = QColor(image.pixel(x, y))
                total += 1
                if pixel.red() > 200 and pixel.green() > 180 and pixel.blue() < 100:
                    yellowish += 1
        # Selection band must be clearly present (not a sliver, not missing).
        assert yellowish / max(total, 1) > 0.05
    finally:
        editor.close()


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
    assert values == list(Preferences.ACCENTS)
    assert len(values) == 10


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


def _shown_host(*widgets, width=700, height=100):
    """Real usage mirror: layout installed in a shown host widget.

    (Calling setGeometry on a parentless layout leaves children as
    top-level windows whose geometry the platform plugin owns.)
    """
    from PySide6.QtWidgets import QApplication

    from app.gui.utils.flow_layout import FlowLayout

    host = QWidget()
    host.resize(width, height)
    row = FlowLayout(host)
    for widget in widgets:
        row.addWidget(widget)
    host.show()
    row.activate()
    QApplication.processEvents()
    return host


def test_flow_row_centers_items_vertically():
    short = _fixed_widget(100, height=20)
    tall = _fixed_widget(100, height=40)
    _host = _shown_host(short, tall)
    short_center = short.geometry().center().y()
    tall_center = tall.geometry().center().y()
    assert abs(short_center - tall_center) <= 1


def test_glued_pair_keeps_label_and_control_together():
    label = QLabel("Timezone")
    control = _fixed_widget(200)
    pair = glued_pair(label, control)
    follower = _fixed_widget(200)
    _host = _shown_host(pair, follower)
    # Pair internals: label left of control, adjacent (glued, one unit).
    assert label.geometry().left() < control.geometry().left()
    assert control.geometry().left() - label.geometry().right() <= 10
    # The pair wraps as one indivisible block, ahead of the follower.
    assert pair.geometry().left() <= follower.geometry().left()


def test_flow_row_skips_hidden_widgets_at_placement():
    hidden = _fixed_widget(300)
    visible = _fixed_widget(200)
    hidden.hide()
    _host = _shown_host(hidden, visible, width=900)
    # The hidden 300px widget takes no slot: visible starts at x=0,
    # not at x=312 behind it.
    assert visible.pos().x() == 0


def test_configurations_page_uses_flow_rows(gui_container):
    from app.gui.widgets.pages.configurations_page import ConfigurationsPage
    from app.gui.workers.task_runner import TaskRunner

    page = ConfigurationsPage(gui_container, TaskRunner())
    assert page._generate is not None
    assert page._timezone_filter.count() > 40
    assert isinstance(page._new, QPushButton)
    page.close()


@pytest.mark.parametrize("accent", [a for a in ACCENTS])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_scrollbars_keep_gap_from_content(theme, accent):
    """Regression: the scrollbar must not sit flush on block borders.

    Both orientations keep a paper gap on the content side.
    """
    qss = build_stylesheet(theme=theme, accent=accent)
    assert "QScrollBar:vertical" in qss
    assert "margin: 0 0 0 8px" in qss
    assert "QScrollBar:horizontal" in qss
    assert "margin: 8px 0 0 0" in qss


def test_combo_popups_cannot_render_narrow_or_collapsed():
    """Regression: combo popups keep readable width/row height anywhere."""
    qss = build_stylesheet(theme="light", accent="mono")
    assert "min-width: 220px" in qss
    assert "min-height: 22px" in qss


def test_language_pool_shows_every_entry_at_once():
    from app.gui.dialogs.config_dialog import ConfigDialog

    dialog = ConfigDialog()
    combo = dialog._language
    try:
        assert combo.maxVisibleItems() >= combo.count() >= 20
    finally:
        dialog.close()


def test_popup_selection_text_stays_visible():
    """Pixel check: the highlighted row keeps contrasting text.

    Guards the "languages don't show" class of bugs: selection background
    with invisible text looks like an empty black block.
    """
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from app.gui.dialogs.config_dialog import ConfigDialog
    from app.gui.utils.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app, "light", "mono")
    dialog = ConfigDialog()
    try:
        dialog.show()
        dialog._language.showPopup()
        app.processEvents()
        image = dialog._language.view().grab().toImage()
        assert image.width() >= 220
        light = dark = 0
        for y in range(0, min(34, image.height())):
            for x in range(0, image.width(), 2):
                lightness = QColor(image.pixel(x, y)).lightness()
                if lightness > 150:
                    light += 1
                elif lightness <= 80:
                    dark += 1
        assert dark > 0, "expected the dark selection band"
        assert light > 50, "selected-row text must contrast its background"
    finally:
        dialog.close()
