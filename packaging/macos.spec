# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Antidetect — macOS .app bundle (dist/Antidetect.app).

User data (SQLite DB, Chromium profiles, logs) is created at runtime in the OS
user-data dir, never inside the bundle. Do NOT bundle data/ (local dev DB).
"""

import os
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821 - injected by PyInstaller
import _spec_common as common  # noqa: E402

ICON = common.RES / "icon.icns"
# Set only for a signed release (see build.py); unset = unsigned build that build.py signs ad-hoc afterwards.
IDENTITY = os.environ.get("MACOS_CODESIGN_IDENTITY", "").strip() or None
ENTITLEMENTS = os.path.join(SPECPATH, "entitlements.plist") if IDENTITY else None  # noqa: F821

a = Analysis(
    [str(common.ENTRY)],
    pathex=[str(common.SRC)],
    binaries=[],
    datas=common.datas(),
    hiddenimports=common.hiddenimports(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common.EXCLUDES,
    noarchive=False,
)
a.datas = common.drop_qt_extras(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Antidetect",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX would re-decompress every Qt library on each launch
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=IDENTITY,
    entitlements_file=ENTITLEMENTS,
    icon=str(ICON) if ICON.is_file() else None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Antidetect")

app = BUNDLE(
    coll,
    name="Antidetect.app",
    icon=str(ICON) if ICON.is_file() else None,
    bundle_identifier="com.antidetect.browser",
    info_plist={
        "CFBundleShortVersionString": common.version(),
        "CFBundleVersion": common.version(),
        "CFBundleName": "Antidetect",
        "LSMinimumSystemVersion": "13.0",   # the PySide6 wheels are tagged macosx_13_0
        "NSHighResolutionCapable": True,
    },
)
