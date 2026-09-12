"""Profiles empty state lives inside the list block as a watermark."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from app.gui.widgets.pages.profiles_page import ProfilesPage

pytestmark = pytest.mark.usefixtures("qapp")


def _page(gui_container):
    from app.gui.workers.task_runner import TaskRunner

    return ProfilesPage(gui_container, TaskRunner())


def test_empty_hint_is_watermark_inside_list(gui_container):
    page = _page(gui_container)
    page._profiles = []
    page._configs = []
    page._render_list()

    assert page._empty.parent() is page._list
    assert not page._empty.isHidden()
    assert page._empty.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    page.close()


def test_hint_hides_with_first_profile(gui_container):
    gui_container.profiles.create_profile("first")
    page = _page(gui_container)
    page._profiles = gui_container.profiles.list_profiles()
    page._configs = []
    page._render_list()

    assert page._empty.isHidden()
    assert page._list.count() == 1
    page.close()
