"""Small, optional bits of native-window behaviour (macOS title bar). Every call degrades to a no-op."""

from __future__ import annotations

import ctypes
import os
import sys
import warnings

from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

MAC_TITLEBAR_INSET = 28    # height of the title bar the traffic lights live in


def _is_cocoa() -> bool:
    """True only on a real macOS window system (not the offscreen platform the tests and screenshots use)."""
    return sys.platform == "darwin" and QGuiApplication.platformName() == "cocoa"


def expands_into_titlebar() -> bool:
    """macOS with Qt >= 6.9 can let content run under the title bar and keep the traffic lights."""
    version = tuple(int(part) for part in qVersion().split(".")[:3] if part.isdigit())
    return _is_cocoa() and version >= (6, 9) and not os.environ.get("ANTIDETECT_NATIVE_TITLEBAR")


def expand_into_titlebar(window: QWidget) -> int:
    """Draw the window's content under the (invisible) title bar; returns the inset to leave free, 0 = unchanged.

    Call before the window is shown.
    """
    if not expands_into_titlebar():
        return 0
    with warnings.catch_warnings():
        # PySide reports the flag's enum value as an alias of a deprecated one; the flag itself is fine
        warnings.simplefilter("ignore", DeprecationWarning)
        window.setWindowFlag(Qt.WindowType.ExpandedClientAreaHint, True)
        window.setWindowFlag(Qt.WindowType.NoTitleBarBackgroundHint, True)
    return MAC_TITLEBAR_INSET


def finish_titlebar(window: QWidget) -> None:
    """Hide the title text and the separator line under the title bar (macOS; call once the window exists)."""
    if not _is_cocoa():
        return
    try:
        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        send = objc.objc_msgSend

        def call(target, selector: bytes, *args, argtypes=()):
            send.restype = ctypes.c_void_p
            send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
            return send(target, objc.sel_registerName(selector), *args)

        ns_window = call(ctypes.c_void_p(int(window.winId())), b"window")
        if not ns_window:
            return
        call(ns_window, b"setTitleVisibility:", 1, argtypes=(ctypes.c_long,))          # NSWindowTitleHidden
        call(ns_window, b"setTitlebarSeparatorStyle:", 1, argtypes=(ctypes.c_long,))   # NSTitlebarSeparatorStyleNone
    except Exception:
        pass
