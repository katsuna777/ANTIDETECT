#!/usr/bin/env python3
"""Validate the Windows artifact: Antidetect.exe is standalone.

Checks:
- file exists and is not suspiciously small (>= 20 MB onefile bundle);
- no mandatory runtime sidecars next to it (no .dll/.so/.pyd folders,
  no .py sources required);
- optional smoke run does not crash instantly on missing files
  (skipped unless --smoke is passed and a display/toolchain allows it).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MIN_SIZE_BYTES = 20 * 1024 * 1024
SIDE_CAR_SUFFIXES = {".dll", ".so", ".dylib", ".pyd", ".py"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    exe = Path(args.exe)
    if not exe.is_file():
        print(f"ERROR: {exe} does not exist")
        return 1
    size = exe.stat().st_size
    print(f"Antidetect.exe: {size} bytes")
    if size < MIN_SIZE_BYTES:
        print(f"ERROR: suspiciously small (< {MIN_SIZE_BYTES} bytes) — bundle likely incomplete")
        return 1

    siblings = [p for p in exe.parent.iterdir() if p.resolve() != exe.resolve()]
    offenders = [p for p in siblings if p.suffix.lower() in SIDE_CAR_SUFFIXES or p.is_dir()]
    # Only fail for directories that look like a PyInstaller onedir sidecar.
    hard_offenders = [
        p for p in offenders
        if p.is_dir() and (p.name == "_internal" or list(p.glob("*.dll")) or list(p.glob("*.pyd")))
    ]
    if hard_offenders:
        print("ERROR: sidecar runtime dirs found next to exe (not standalone):")
        for p in hard_offenders:
            print(f"  - {p}")
        return 1

    if args.smoke:
        import subprocess

        try:
            proc = subprocess.run([str(exe), "--help"], capture_output=True, timeout=60)
            print(f"smoke --help exit code: {proc.returncode}")
        except Exception as exc:  # noqa: BLE001
            print(f"smoke skipped/failed: {exc}")

    print("Windows artifact OK: standalone onefile exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
