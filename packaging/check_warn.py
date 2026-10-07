#!/usr/bin/env python3
"""Fail the build if PyInstaller recorded a required module as missing.

PyInstaller never errors on missing (hidden)imports — it only logs
"missing module named X" into warn-<spec>.txt and ships a bundle that
crashes at runtime. Run this right after PyInstaller.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# "antidetect" also catches antidetect.<anything>: our own modules must never be reported missing.
REQUIRED = ("websocket", "platformdirs", "PySide6", "certifi", "antidetect")


def scan(warn: Path, modules: tuple[str, ...] = REQUIRED) -> int:
    """0 when the warn file exists and names none of ``modules`` as missing; 1 otherwise."""
    if not warn.is_file():
        print(f"ERROR: PyInstaller's warn file not found: {warn} (the spec name or path changed?)")
        return 1
    text = warn.read_text(errors="replace")
    bad = [m for m in modules if f"missing module named {m}" in text]
    if bad:
        print(f"ERROR: modules missing from bundle: {', '.join(bad)} (see {warn})")
        return 1
    print("warn scan OK: all required modules bundled")
    return 0


def main_for(warn: Path) -> int:
    return scan(warn)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warn", required=True, help="path to warn-<spec>.txt")
    parser.add_argument("--modules", default=",".join(REQUIRED))
    args = parser.parse_args()
    return scan(Path(args.warn), tuple(args.modules.split(",")))


if __name__ == "__main__":
    raise SystemExit(main())
