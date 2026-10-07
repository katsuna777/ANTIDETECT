"""Error presentation: expected domain/validation errors vs. unexpected ones."""

from __future__ import annotations

import pytest

from antidetect.domain.errors import ProfileConfigurationMissingError, ProfileNotFoundError
from antidetect.gui.components import ErrorDialog
from antidetect.gui.errors import error_details, friendly_error_text, show_error

pytestmark = pytest.mark.usefixtures("qapp")


def test_antidetect_error_shown_verbatim():
    exc = ProfileNotFoundError(4242)
    assert str(exc) in friendly_error_text(exc)


def test_validation_value_error_shown_verbatim():
    exc = ValueError("Profile name must not be empty.")
    assert friendly_error_text(exc) == "Profile name must not be empty."


def test_unknown_error_gives_generic_message():
    exc = RuntimeError("internal wiring bug")
    assert friendly_error_text(exc).startswith("Something went wrong")


def test_details_carry_class_name_for_expected_errors():
    assert "ProfileConfigurationMissingError" in error_details(ProfileConfigurationMissingError(1))


def test_details_carry_traceback_for_unexpected_errors():
    try:
        1 / 0
    except ZeroDivisionError as exc:
        details = error_details(exc)
    assert "ZeroDivisionError" in details
    assert "test_details_carry_traceback_for_unexpected_errors" in details


def test_error_dialog_hides_details_until_asked_and_runs_the_chosen_action(monkeypatch):
    fired = []
    dialog = ErrorDialog(None, "Something broke", "TRACEBACK", [("Fix it", lambda: fired.append(True))])
    dialog.show()
    assert dialog.details.isHidden()
    dialog._toggle.click()
    assert not dialog.details.isHidden() and dialog.details.toPlainText() == "TRACEBACK"
    fix = next(b for b in dialog.findChildren(type(dialog._toggle)) if b.text() == "Fix it")
    fix.click()
    assert dialog.chosen_action is not None and dialog.result() == dialog.DialogCode.Accepted
    dialog.chosen_action()
    assert fired == [True]


def test_show_error_runs_the_action_after_the_dialog_closes(monkeypatch):
    called = []
    monkeypatch.setattr(ErrorDialog, "exec", lambda self: setattr(self, "chosen_action", lambda: called.append(1)) or 0)
    show_error(None, ValueError("x"), [("Do", lambda: None)])
    assert called == [1]
