# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Antidetect — Windows standalone onefile exe (dist/Antidetect.exe).

Single file, Python + deps + resources inside; no sidecar folders required.
"""

import sys

sys.path.insert(0, SPECPATH)  # noqa: F821 - injected by PyInstaller
import _spec_common as common  # noqa: E402

# Windows EXE accepts only .ico (a .png aborts the build unless Pillow is
# installed, so never fall back to it — fail visibly instead of shipping
# an icon-less exe silently).
ICON = common.RES / "icon.ico"
if not ICON.is_file():
    raise SystemExit(f"missing required icon: {ICON}")

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
    a.binaries,
    a.datas,
    [],
    name="Antidetect",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX would re-decompress every Qt library on each launch
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=common.windows_version_file(),
)
