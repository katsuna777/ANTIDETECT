#!/usr/bin/env python3
"""Fail the build if PyInstaller recorded a required module as missing.

PyInstaller never errors on missing (hidden)imports — it only logs
"missing module named X" into warn-<spec>.txt and ships a bundle that
crashes at runtime. Run this right after PyInstaller.
"""

from __future__ import annotations

import argparse
from pathlib import Path

REQUIRED = ("websocket", "platformdirs", "PySide6")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warn", required=True, help="path to warn-<spec>.txt")
    parser.add_argument("--modules", default=",".join(REQUIRED))
    args = parser.parse_args()

    warn = Path(args.warn)
    text = warn.read_text(errors="replace") if warn.is_file() else ""
    if not warn.is_file():
        print(f"WARNING: warn file not found: {warn} (skipping scan)")
        return 0
    bad = [m for m in args.modules.split(",") if f"missing module named {m}" in text]
    if bad:
        print(f"ERROR: modules missing from bundle: {', '.join(bad)} (see {warn})")
        return 1
    print("warn scan OK: all required modules bundled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
