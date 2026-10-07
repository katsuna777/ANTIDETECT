#!/usr/bin/env python3
"""Fail-fast guard for the *build* environment (not the frozen app).

PyInstaller silently ships a broken bundle when an optional-but-required
dependency is missing from the machine that runs the build: the module is
recorded as "missing module" in the warn file and the frozen app crashes
at runtime (e.g. StealthError: websocket-client is required...).

Run this BEFORE PyInstaller. Exit code != 0 means: install
`pip install -e ".[build]"` into the build interpreter first.
"""

from __future__ import annotations

import sys

REQUIRED = ("websocket", "platformdirs", "PySide6", "certifi")


def main() -> int:
    print(f"build interpreter: {sys.executable}")
    failed: list[str] = []
    for name in REQUIRED:
        try:
            __import__(name)
        except ImportError:
            failed.append(name)
            print(f"MISSING: {name}")
        else:
            print(f"OK: {name}")
    if failed:
        print(
            "ERROR: build env is incomplete "
            f"({', '.join(failed)}). Run: pip install -e \".[build]\"",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
