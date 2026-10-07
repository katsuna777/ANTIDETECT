"""Friendly error presentation (English / Russian).

Expected domain errors (:class:`antidetect.domain.errors.AntiDetectError` and the
ValueErrors raised by service validation) are shown in the current UI language.
Anything else is treated as an internal failure. Either way the technical details
sit one click away in the error dialog — never in the primary message.
"""

from __future__ import annotations

import traceback
from typing import Any

from PySide6.QtWidgets import QWidget

from antidetect.domain.errors import (
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
    TagAlreadyExistsError,
    TagNotFoundError,
    WorkspaceAlreadyExistsError,
    WorkspaceNotFoundError,
)
from antidetect.gui.components import ErrorDialog
from antidetect.i18n import tr

_EXPECTED = (AntiDetectError, ValueError)


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
    if isinstance(exc, TagNotFoundError):
        return tr("err.tag.notfound", id=exc.tag_id)
    if isinstance(exc, TagAlreadyExistsError):
        return tr("err.tag.exists", name=exc.name)
    if isinstance(exc, WorkspaceNotFoundError):
        return tr("err.workspace.notfound", id=exc.workspace_id)
    if isinstance(exc, WorkspaceAlreadyExistsError):
        return tr("err.workspace.exists", name=exc.name)
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


def show_error(
    parent: QWidget | None,
    exc: Any,
    actions: list[tuple[str, Any]] | None = None,
) -> None:
    dialog = ErrorDialog(parent, friendly_error_text(exc), error_details(exc), actions)
    dialog.exec()
    if dialog.chosen_action is not None:
        dialog.chosen_action()
