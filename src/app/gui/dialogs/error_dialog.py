"""Friendly error presentation.

Expected domain errors (:class:`app.domain.errors.AntiDetectError` and the
ValueErrors raised by service validation) are shown as their own message.
Anything else is treated as an internal failure. Either way the full traceback,
when available, is demoted to the collapsible ``Detailed text`` section — never
the primary interface.
"""

from __future__ import annotations

import traceback
from typing import Any

from PySide6.QtWidgets import QMessageBox, QWidget

from app.domain.errors import AntiDetectError

_EXPECTED = (AntiDetectError, ValueError)


def friendly_error_text(exc: Any) -> str:
    """Human-readable one-liner for the error dialog's main area."""
    if isinstance(exc, _EXPECTED):
        return str(exc)
    return "The operation failed unexpectedly."


def error_details(exc: Any) -> str:
    """Collapsible technical details (exception type, stack when present)."""
    if isinstance(exc, _EXPECTED):
        return f"{type(exc).__name__}: {exc}"
    try:
        return "".join(traceback.format_exception(exc))
    except Exception:  # noqa: BLE001 - never crash the dialog over formatting
        return f"{type(exc).__name__}: {exc}"


def show_error(parent: QWidget | None, exc: Any) -> None:
    """Raise a themed modal error dialog for ``exc``."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Antidetect")
    box.setText(friendly_error_text(exc))
    box.setDetailedText(error_details(exc))
    box.exec()