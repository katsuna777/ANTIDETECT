# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Antidetect — Windows standalone onefile exe.

Result: release/Antidetect.exe (single file, Python + deps + resources inside).
No DLLs, no sidecar folders required next to the exe.
"""

import os
from pathlib import Path

ROOT = Path(os.path.abspath("."))
SRC = ROOT / "src"
RES = SRC / "app" / "gui" / "resources"

ICON_ICO = RES / "icon.ico"
# Windows EXE accepts only .ico (a .png aborts the build unless Pillow is
# installed, so never fall back to it — fail visibly instead of shipping
# an icon-less exe silently).
icon_arg = str(ICON_ICO) if ICON_ICO.is_file() else None
if icon_arg is None:
    raise SystemExit(f"missing required icon: {ICON_ICO}")

datas = []
if (RES / "icon.png").is_file():
    datas.append((str(RES / "icon.png"), "app/gui/resources"))
if (RES / "icon.icns").is_file():
    datas.append((str(RES / "icon.icns"), "app/gui/resources"))
if ICON_ICO.is_file():
    datas.append((str(ICON_ICO), "app/gui/resources"))

# certifi is a hard requirement: without its CA bundle every https:// fetch
# (proxy sources) fails verification on user machines, whose OpenSSL paths
# differ from the build machine's. Fail loudly here, not silently at runtime.
try:
    import certifi as _certifi
except ImportError as _exc:
    raise SystemExit(
        "certifi is required for the build (pip install -r requirements-build.txt)"
    ) from _exc
datas.append((_certifi.where(), "certifi"))

# Migration modules are loaded dynamically via importlib (see
# app/infrastructure/database/migrations/__init__.py) so PyInstaller's
# static analysis misses them — list explicitly (glob = future-proof).
_versions_dir = SRC / "app" / "infrastructure" / "database" / "migrations" / "versions"
migration_modules = [
    f"app.infrastructure.database.migrations.versions.{p.stem}"
    for p in sorted(_versions_dir.glob("*.py"))
    if p.stem != "__init__"
]

a = Analysis(
    [str(SRC / "app" / "gui" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "platformdirs",
        "websocket",
        "certifi",
        "app.infrastructure.database.migrations.versions",
        *migration_modules,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)
