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


def bundled_cafile() -> str | None:
    """Locate a CA bundle for TLS verification, frozen or not.

    The frozen app must never rely on the build machine's OpenSSL paths
    (e.g. ``/opt/homebrew/etc/openssl@3/cert.pem``): they do not exist on
    user machines, so every ``https://`` fetch would fail verification.
    We ship ``certifi/cacert.pem`` as bundle data and prefer it there.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "certifi" / "cacert.pem"
        if candidate.is_file():
            return str(candidate)
    try:
        import certifi
    except ImportError:
        return None
    candidate = Path(certifi.where())
    return str(candidate) if candidate.is_file() else None


def ensure_ssl_certs() -> None:
    """Point the process at a valid CA bundle before any HTTPS I/O.

    Safe to call in development too; a no-op when no bundle is found.
    Must run before the first ``ssl`` context is created (i.e. at the top
    of every entry point). ``urllib``/``ssl`` honour ``SSL_CERT_FILE``.
    """
    import os

    cafile = bundled_cafile()
    if cafile:
        os.environ.setdefault("SSL_CERT_FILE", cafile)
