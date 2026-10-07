"""The version stamped into a browser's executable (Windows).

``chrome.exe --version`` prints nothing on Windows (Chrome is a GUI-subsystem program with no console
to write to), so the version cannot be asked for the way it is on macOS and Linux. Every Chrome / Chromium
build carries it in the executable's version resource instead, and Windows can read that without starting
the program, through ``version.dll``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def windows_file_version(binary: Path | str) -> str | None:
    """``155.0.8059.39`` from the executable's version resource, ``None`` when it has none (or off Windows)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [(name, wintypes.DWORD) for name in (
                "dwSignature", "dwStrucVersion", "dwFileVersionMS", "dwFileVersionLS", "dwProductVersionMS",
                "dwProductVersionLS", "dwFileFlagsMask", "dwFileFlags", "dwFileOS", "dwFileType",
                "dwFileSubtype", "dwFileDateMS", "dwFileDateLS")]

        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = [wintypes.LPCVOID, wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID),
                                           ctypes.POINTER(wintypes.UINT)]
        version.VerQueryValueW.restype = wintypes.BOOL

        path = str(binary)
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buffer):
            return None
        info, length = wintypes.LPVOID(), wintypes.UINT()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(info), ctypes.byref(length)) or not info.value:
            return None
        fixed = ctypes.cast(info, ctypes.POINTER(FixedFileInfo)).contents
        ms, ls = fixed.dwProductVersionMS, fixed.dwProductVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return None
