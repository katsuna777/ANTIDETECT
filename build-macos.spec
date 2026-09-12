# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Antidetect — macOS .app bundle.

Result: dist/Antidetect.app (then packaged to release/Antidetect.dmg).
All runtime components live inside the .app bundle. User data (SQLite DB,
Chromium profiles, logs) is created at runtime in the OS user-data dir,
never inside the bundle.
NOTE: do NOT bundle data/ (it holds the local dev DB + profiles).
"""

import os
from pathlib import Path

ROOT = Path(os.path.abspath("."))
SRC = ROOT / "src"
RES = SRC / "app" / "gui" / "resources"

datas = []
if (RES / "icon.png").is_file():
    datas.append((str(RES / "icon.png"), "app/gui/resources"))
if (RES / "icon.icns").is_file():
    datas.append((str(RES / "icon.icns"), "app/gui/resources"))

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
    [],
    exclude_binaries=True,
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
    icon=str(RES / "icon.icns") if (RES / "icon.icns").is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Antidetect",
)

app = BUNDLE(
    coll,
    name="Antidetect.app",
    icon=str(RES / "icon.icns") if (RES / "icon.icns").is_file() else None,
    bundle_identifier="com.antidetect.browser",
    info_plist={
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleName": "Antidetect",
        "NSHighResolutionCapable": True,
    },
)
