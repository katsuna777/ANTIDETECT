"""Friendly error presentation (English / Russian).

Expected domain errors (:class:`app.domain.errors.AntiDetectError` and the
ValueErrors raised by service validation) are shown in the current UI
language. Anything else is treated as an internal failure. Either way the
full traceback, when available, is demoted to the collapsible
``Detailed text`` section — never the primary interface.
"""

from __future__ import annotations

import traceback
from typing import Any

from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from app.domain.errors import (
    AntiDetectError,
    BrowserConfigurationNotFoundError,
    BrowserConfigurationValidationError,
    ChromiumNotFoundError,
    CookieFileNotFoundError,
    ProfileAlreadyExistsError,
    ProfileAlreadyRunningError,
    ProfileConfigurationMissingError,
    ProfileNotFoundError,
    ProfileNotRunningError,
    ProxyNotFoundError,
    ProxyNotUsableError,
    ProxySourceError,
)
from app.gui.i18n import is_ru, tr

_EXPECTED = (AntiDetectError, ValueError)

_MIN_DIALOG_WIDTH = 560


def friendly_error_text(exc: Any) -> str:
    """Human-readable one-liner for the error dialog's main area."""
    translated = translate_domain_error(exc)
    if translated is not None:
        return translated
    if isinstance(exc, _EXPECTED):
        return str(exc)
    return tr("error.unexpected")


def translate_domain_error(exc: Any) -> str | None:
    """Russian/English text for known domain errors; None when unknown."""
    if isinstance(exc, ProfileNotFoundError):
        return tr("err.profile.notfound", id=exc.profile_id)
    if isinstance(exc, ProfileAlreadyExistsError):
        return tr("err.profile.exists", name=exc.name)
    if isinstance(exc, ProfileAlreadyRunningError):
        return tr("err.profile.running", id=exc.profile_id, pid=exc.pid)
    if isinstance(exc, ProfileNotRunningError):
        return tr("err.profile.notrunning", id=exc.profile_id)
    if isinstance(exc, ProfileConfigurationMissingError):
        return tr("err.profile.noconfig", id=exc.profile_id)
    if isinstance(exc, BrowserConfigurationNotFoundError):
        return tr("err.config.notfound", id=exc.configuration_id)
    if isinstance(exc, BrowserConfigurationValidationError):
        return tr("err.config.invalid", msg=exc.message)
    if isinstance(exc, ChromiumNotFoundError):
        return tr("err.chromium.notfound")
    if isinstance(exc, ProxyNotFoundError):
        return tr("err.proxy.notfound", id=exc.proxy_id)
    if isinstance(exc, ProxyNotUsableError):
        return tr("err.proxy.unusable", id=exc.proxy_id, detail=exc.detail)
    if isinstance(exc, ProxySourceError):
        return tr("err.proxy.source", source=exc.source_name, detail=exc.detail)
    if isinstance(exc, CookieFileNotFoundError):
        return tr("err.cookie.nocookies", id=exc.profile_id, detail=exc.detail)
    return None


def error_details(exc: Any) -> str:
    if isinstance(exc, _EXPECTED):
        return f"{type(exc).__name__}: {exc}"
    try:
        return "".join(traceback.format_exception(exc))
    except Exception:
        return f"{type(exc).__name__}: {exc}"


def _build_box(
    parent: QWidget | None,
    exc: Any,
    actions: list[tuple[str, Any]] | None = None,
) -> tuple[QMessageBox, dict[int, Any]]:
    from PySide6.QtWidgets import QSpacerItem, QSizePolicy

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("app.title"))
    box.setText(friendly_error_text(exc))
    box.setDetailedText(error_details(exc))
    label = box.findChild(QLabel, "qt_msgbox_label")
    if label is not None:
        label.setWordWrap(True)
        label.setMinimumWidth(_MIN_DIALOG_WIDTH - 120)
    layout = box.layout()
    if layout is not None:
        spacer = QSpacerItem(
            _MIN_DIALOG_WIDTH, 0,
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding,
        )
        layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())
    callbacks: dict[int, Any] = {}
    for label_text, callback in actions or []:
        button = box.addButton(label_text, QMessageBox.ButtonRole.ActionRole)
        callbacks[id(button)] = callback
    box.addButton(QMessageBox.StandardButton.Close)
    _rename_details_button(box)
    return box, callbacks


def _rename_details_button(box: QMessageBox) -> None:
    for button in box.buttons():
        text = (button.text() or "").lower()
        if "detail" in text or "подробн" in text:
            button.setText(tr("error.details"))
            button.clicked.connect(
                lambda _checked=False, target=button: target.setText(tr("error.details"))
            )
            break


def show_error(
    parent: QWidget | None,
    exc: Any,
    actions: list[tuple[str, Any]] | None = None,
) -> None:
    box, callbacks = _build_box(parent, exc, actions)
    box.exec()
    clicked = box.clickedButton()
    callback = callbacks.get(id(clicked)) if clicked is not None else None
    if callback is not None:
        callback()
