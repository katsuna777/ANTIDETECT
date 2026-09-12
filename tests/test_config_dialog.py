"""Config dialog: timezone picker over supported zones, sane defaults."""

from __future__ import annotations

import pytest

from app.application.profile_doctor import SUPPORTED_TIMEZONES
from app.gui.dialogs.config_dialog import ConfigDialog

pytestmark = pytest.mark.usefixtures("qapp")


def test_timezone_combo_lists_supported_zones():
    dialog = ConfigDialog()
    zones = [
        dialog._timezone.itemData(i) for i in range(dialog._timezone.count())
    ]
    assert zones[0] is None  # "—" unset option
    assert set(zones[1:]) == set(SUPPORTED_TIMEZONES)
    assert "Europe/Moscow" in zones


def test_new_dialog_defaults_to_unset():
    dialog = ConfigDialog()
    assert dialog.name == ""
    assert dialog.values()["timezone"] is None
    # Empty name blocks Save.
    save = dialog._buttons.button(
        dialog._buttons.StandardButton.Save
    )
    assert not save.isEnabled()


def test_edit_dialog_prefills_configuration(gui_container):
    from app.gui.workers.task_runner import TaskRunner  # noqa: F401

    cfg = gui_container.configurations.create_configuration(
        "prefill-me",
        platform="windows",
        language="de",
        locale="de-DE",
        timezone="Europe/Berlin",
        screen_width=1920,
        screen_height=1080,
    )
    dialog = ConfigDialog(cfg)
    assert dialog.name == "prefill-me"
    values = dialog.values()
    assert values["platform"] == "windows"
    assert values["language"] == "de"
    assert values["locale"] == "de-DE"
    assert values["timezone"] == "Europe/Berlin"
    assert values["screen_width"] == 1920
    assert values["screen_height"] == 1080
