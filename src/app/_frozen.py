"""Helpers for running the same code in development and in a frozen bundle.

When packaged with PyInstaller (``sys.frozen == True``) all bundled
resources live under ``sys._MEIPASS`` (onefile) or next to the executable
(onedir). User-writable data (SQLite DB, Chromium profiles, logs) must
NEVER be read from the bundle — it always lives in platformdirs /
``ANTIDETECT_DATA_DIR`` (see ``app.config.settings``).
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory with bundled read-only resources."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource that works in dev and in frozen app.

    Example: ``resource_path("app", "gui", "resources", "icon.png")``.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).joinpath(*parts)
    # Development layout: repository root / src ...
    here = Path(__file__).resolve()
    # src/app/_frozen.py -> src/
    src_dir = here.parents[1]
    return src_dir.joinpath(*parts)
