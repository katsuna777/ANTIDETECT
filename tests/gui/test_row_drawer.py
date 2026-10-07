"""The row drawer engine: the animation, the ghost of a closing row, scrolling into view, resizing."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QVariantAnimation

from antidetect.gui.components.profile_drawer import NARROW
from antidetect.gui.sidebar import SECTION_PROFILES
from antidetect.gui.theme import current_palette
from antidetect.gui.views.delegates import PROFILE_ROW_HEIGHT
from tests.support.gui import make_profile, settle, spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


def _heights(page):
    return [page._view.rowHeight(r) for r in range(page._model.rowCount())]


def _page(window, gui_container, count=3):
    for i in range(count):
        make_profile(gui_container, f"P{i:02d}")
    return settle(window, count)


def test_opening_grows_the_row_by_the_drawers_height_and_closing_gives_it_back(window, gui_container):
    page = _page(window, gui_container)
    ex = page._expander
    key = page._model.row_at(1).id
    ex.open(key)
    assert ex.is_open() and ex.key == key
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)
    full = page._drawer.height()
    assert full > 200 and _heights(page) == [PROFILE_ROW_HEIGHT, PROFILE_ROW_HEIGHT + full, PROFILE_ROW_HEIGHT]
    assert ex.extra_of_row(1) == full and ex.extra_of_row(0) == 0 and ex.extra_of_row(7) == 0
    assert page._view.expansion_extra(1) == full
    clip = ex._clip
    assert clip.isVisibleTo(page._view.viewport()) and clip.height() == full - 2         # the card's 2 px margin
    assert clip.y() == page._view.rowViewportPosition(1) + PROFILE_ROW_HEIGHT
    ex.close()
    assert not ex.is_open()
    assert spin_wait(lambda: _heights(page) == [PROFILE_ROW_HEIGHT] * 3)
    assert not clip.isVisible()


def test_the_height_follows_the_animation_and_stays_between_the_ends(window, gui_container):
    page = _page(window, gui_container)
    ex = page._expander
    ex.open(page._model.row_at(0).id)
    ex._anim.stop()
    last = 0
    for t in (0.1, 0.4, 0.7, 1.0):
        ex._on_step(t)
        height = page._view.rowHeight(0) - PROFILE_ROW_HEIGHT
        assert last < height <= page._drawer.height()
        assert ex._clip.height() == max(0, height - 2)
        last = height
    ex._on_finished()
    assert page._view.rowHeight(0) == PROFILE_ROW_HEIGHT + page._drawer.height()


def test_opening_another_row_keeps_a_ghost_of_the_first_while_it_shrinks(window, gui_container):
    page = _page(window, gui_container)
    ex = page._expander
    first, second = page._model.row_at(0).id, page._model.row_at(1).id
    ex.open(first)
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)
    full = page._drawer.height()
    ex.open(second)
    ex._anim.stop()
    assert ex._ghost_key == first and ex.key == second and not ex._ghost._pixmap.isNull()
    ex._on_step(0.5)
    assert page._view.rowHeight(0) - PROFILE_ROW_HEIGHT == pytest.approx(full * 0.5, abs=2)
    assert page._view.rowHeight(1) - PROFILE_ROW_HEIGHT == pytest.approx(full * (0.5 if full else 0), abs=full)
    assert ex._ghost.isVisibleTo(page._view.viewport()) and ex._ghost.height() == pytest.approx(full * 0.5 - 2, abs=3)
    ex._on_finished()
    assert ex._ghost_key is None and not ex._ghost.isVisible()
    assert _heights(page)[0] == PROFILE_ROW_HEIGHT and _heights(page)[1] == PROFILE_ROW_HEIGHT + full


def test_the_drawer_scrolls_into_view_when_it_opens_near_the_bottom(window, gui_container):
    page = _page(window, gui_container, 14)
    window.resize(1200, 640)
    page._view.verticalScrollBar().setValue(page._view.verticalScrollBar().maximum())
    spin_wait(lambda: False, 100)
    ex = page._expander
    last = page._model.row_at(page._model.rowCount() - 3)
    ex.open(last.id)
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)
    row = page._model.position_of(last.id)
    top = page._view.rowViewportPosition(row)
    bottom = top + page._view.rowHeight(row)
    assert 0 <= top and bottom <= page._view.viewport().height() + 8                      # the whole drawer is visible


def test_closing_without_animation_is_instant(window, gui_container):
    page = _page(window, gui_container)
    ex = page._expander
    ex.open(page._model.row_at(0).id)
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)
    ex.close(animated=False)
    assert _heights(page) == [PROFILE_ROW_HEIGHT] * 3 and not ex._clip.isVisible() and ex._ghost_key is None
    ex.close()                                                                            # closing a closed table is fine
    ex.open(12345)                                                                        # an unknown row is ignored
    assert not ex.is_open()


def test_the_open_row_keeps_its_height_through_a_refresh_and_a_resort(window, gui_container):
    from antidetect.gui.models.profiles import COL_NAME

    page = _page(window, gui_container)
    ex = page._expander
    key = page._model.row_at(0).id
    ex.open(key)
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)
    full = page._drawer.height()
    page._apply_rows(page._model.rows())                                  # the same rows come back
    page._model.set_rows([r for r in page._model.rows()])
    assert page._view.rowHeight(page._model.position_of(key)) == PROFILE_ROW_HEIGHT + full
    page._sort_by(COL_NAME, Qt_desc())
    position = page._model.position_of(key)
    assert position == 2 and _heights(page) == [PROFILE_ROW_HEIGHT, PROFILE_ROW_HEIGHT, PROFILE_ROW_HEIGHT + full]
    page._model.set_rows([])                                              # everything disappears
    assert not ex.is_open() and not ex._clip.isVisible()


def Qt_desc():
    from PySide6.QtCore import Qt

    return Qt.SortOrder.DescendingOrder


def test_a_narrow_window_stacks_the_form_and_the_height_follows(window, gui_container):
    page = _page(window, gui_container)
    ex = page._expander
    ex.open(page._model.row_at(0).id)
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)
    drawer = page._drawer
    wide = drawer.height()
    assert page._view.viewport().width() >= NARROW and not drawer._narrow
    window.resize(1040, 700)
    spin_wait(lambda: False, 150)
    assert page._view.viewport().width() < NARROW and drawer._narrow
    assert drawer.height() > wide                                          # one column is taller
    assert page._view.rowHeight(0) == PROFILE_ROW_HEIGHT + drawer.height()
    assert drawer.width() == page._view.viewport().width()
    window.resize(1360, 760)
    spin_wait(lambda: False, 150)
    assert not drawer._narrow and drawer.height() == wide


def test_the_expanded_row_is_painted_as_one_card(window, gui_container):
    page = _page(window, gui_container)
    ex = page._expander
    ex.open(page._model.row_at(0).id)
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)
    image = page._view.viewport().grab().toImage()
    pal = current_palette()
    card = image.pixelColor(page._view.viewport().width() // 2, PROFILE_ROW_HEIGHT + 12)       # inside the drawer
    assert card.name().upper() in (pal.drawer.upper(), "#F7F7F9")
    below = image.pixelColor(page._view.viewport().width() // 2, PROFILE_ROW_HEIGHT + page._drawer.height() + 20)
    assert below.name().upper() != pal.drawer.upper()                                         # the next row is outside it


def test_a_window_without_rows_has_no_drawer_to_show(window, gui_container):
    page = window.page(SECTION_PROFILES)
    assert not page._expander.is_open() and not page._expander._clip.isVisible()


def test_the_wheel_over_the_drawer_reaches_the_table(window, gui_container):
    """Qt hands an ignored wheel event to the parent widget: everything in the drawer must ignore it (a plain
    label, the fields, the select, the note while it has nothing to scroll), or the table would not scroll over it."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    page = _page(window, gui_container)
    page.open_drawer(page._model.row_at(1).id)
    page._expander._finish_now()
    drawer = page._drawer

    def accepted(widget) -> bool:
        event = QWheelEvent(QPointF(5, 5), widget.mapToGlobal(QPointF(5, 5)), QPoint(0, 0), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        event.accept()
        QApplication.sendEvent(widget, event)
        return event.isAccepted()

    for widget in (drawer._l_name, drawer._name, drawer._url, drawer._workspace, drawer._notes.viewport(), drawer._tags,
                   drawer._facts):
        assert not accepted(widget), type(widget).__name__


def test_language_and_theme_changes_with_a_drawer_open(window, gui_container):
    from antidetect.gui.theme import current_palette

    page = _page(window, gui_container)
    page.open_drawer(page._model.row_at(1).id)
    page._expander._finish_now()
    drawer = page._drawer
    drawer._name.setText("typing…")
    window.set_language("ru")
    assert drawer._l_notes.text() == "Заметки" and drawer._settings.text() == "Все настройки…"
    assert drawer._name.text() == "typing…"                                  # what was typed survives
    window.set_theme("dark")
    spin_wait(lambda: False, 100)
    assert current_palette().is_dark and page._expander.is_open()
    assert page._view.rowHeight(1) == PROFILE_ROW_HEIGHT + drawer.height()
    window.set_theme("light")


def _wait_still(page):
    ex = page._expander
    assert spin_wait(lambda: ex._anim.state() != QVariantAnimation.State.Running)


def test_adding_tags_that_wrap_grows_the_open_row_and_nothing_is_squeezed(window, gui_container):
    """Regression: a tag that wrapped onto a second line left the drawer at its old height, so the chips were cut
    off and the buttons at the bottom were crushed."""
    page = _page(window, gui_container)
    page.open_drawer(page._model.row_at(0).id)
    _wait_still(page)
    drawer = page._drawer
    before = drawer.height()
    assert drawer.height() >= drawer.layout().minimumSize().height()
    drawer._tags.set_tags(["damita2829@gmail.com", "damita3132@gmail.com", "123", "another-long-name@example.com"])
    drawer._tags.changed.emit()
    _wait_still(page)
    assert drawer.height() > before                                           # the second line of chips has room
    assert drawer.height() >= drawer.layout().minimumSize().height()          # ...and the form is not squeezed
    assert page._view.rowHeight(0) == PROFILE_ROW_HEIGHT + drawer.height()
    assert drawer._tags.height() >= drawer._tags.layout().heightForWidth(drawer._tags.width())
    drawer._tags.set_tags([])
    drawer._tags.changed.emit()
    _wait_still(page)
    assert drawer.height() == before and page._view.rowHeight(0) == PROFILE_ROW_HEIGHT + before


def test_save_and_revert_appear_only_when_there_is_something_to_save(window, gui_container):
    page = _page(window, gui_container)
    page.open_drawer(page._model.row_at(0).id)
    _wait_still(page)
    drawer = page._drawer
    assert drawer._save.isHidden() and drawer._revert.isHidden() and drawer._hint.isHidden()
    drawer._notes.setPlainText("hello")
    assert not drawer._save.isHidden() and drawer._save.isEnabled() and not drawer._revert.isHidden()
    drawer._revert.click()
    assert drawer._save.isHidden() and drawer._revert.isHidden() and drawer._notes.toPlainText() == ""


def test_the_drawer_shows_only_what_the_row_does_not_already_say(window, gui_container):
    page = _page(window, gui_container)
    page.open_drawer(page._model.row_at(0).id)
    _wait_still(page)
    drawer = page._drawer
    assert set(drawer._facts._values) == {"screen", "gpu", "hardware", "timezone", "created", "started", "cookies"}
    for gone in ("_duplicate", "_cookies", "_folder", "_trash"):               # the row's menu has them
        assert not hasattr(drawer, gone)


def test_the_first_opening_is_warmed_up_in_idle_time(window, gui_container):
    page = _page(window, gui_container)
    assert spin_wait(lambda: page._warmed)
    key = page._model.row_at(0).id
    page._expander.warm_up(key)
    assert not page._expander.is_open() and not page._expander._clip.isVisible()      # unseen
    assert page._drawer.row() is not None and page._drawer.row().id == key


def test_russian_cores_use_the_right_plural(qapp):
    from antidetect.gui.components.profile_drawer import _cores_text
    from antidetect.i18n import set_language

    set_language("ru")
    try:
        assert [_cores_text(n) for n in (1, 4, 8, 11, 12, 21)] == [
            "1 ядро", "4 ядра", "8 ядер", "11 ядер", "12 ядер", "21 ядро"]
    finally:
        set_language("en")
    assert _cores_text(8) == "8 cores"
