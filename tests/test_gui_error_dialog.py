"""Error presentation: expected domain/validation errors vs. unexpected ones."""

from __future__ import annotations

import pytest

from app.domain.errors import (
    ProfileConfigurationMissingError,
    ProfileNotFoundError,
)
from app.gui.dialogs.error_dialog import error_details, friendly_error_text

pytestmark = pytest.mark.usefixtures("qapp")


def test_antidetect_error_shown_verbatim():
    exc = ProfileNotFoundError(4242)
    assert str(exc) in friendly_error_text(exc)


def test_validation_value_error_shown_verbatim():
    exc = ValueError("Profile name must not be empty.")
    assert friendly_error_text(exc) == "Profile name must not be empty."


def test_unknown_error_gives_generic_message():
    exc = RuntimeError("internal wiring bug")
    assert friendly_error_text(exc) == "The operation failed unexpectedly."


def test_details_carry_class_name_for_expected_errors():
    exc = ProfileConfigurationMissingError(1)
    details = error_details(exc)
    assert "ProfileConfigurationMissingError" in details


def test_details_carry_traceback_for_unexpected_errors():
    try:
        1 / 0
    except ZeroDivisionError as exc:
        details = error_details(exc)
    assert "ZeroDivisionError" in details
    assert "test_details_carry_traceback_for_unexpected_errors" in details


def test_action_buttons_keep_full_caption_width():
    """Regression: long action captions must not squeeze into stubs.

    QMessageBox sizes to the message and compresses the button row;
    _build_box forces a floor so every button gets its size hint.
    """
    from app.domain.errors import ChromiumError
    from app.gui.dialogs.error_dialog import _build_box

    exc = ChromiumError("Profile #003 failed pre-launch diagnostics.")
    fired: list = []
    box, callbacks = _build_box(
        None, exc, actions=[("Fix timezone automatically", lambda: fired.append(True))]
    )
    try:
        box.show()
        buttons = {button.text(): button for button in box.buttons()}
        assert set(buttons) >= {"Close", "Fix timezone automatically"}
        for button in buttons.values():
            assert button.width() >= button.sizeHint().width() - 2
        assert len(callbacks) == 1
    finally:
        box.close()