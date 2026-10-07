#!/usr/bin/env python3
"""Validate the Windows artifact: Antidetect.exe is standalone and carries the right version.

Checks:
- file exists and is not suspiciously small (>= 20 MB onefile bundle);
- no mandatory runtime sidecars next to it (no .dll/.so/.pyd folders, no .py sources required);
- on Windows: the version in the file's Properties matches ``antidetect.__version__``;
- the real start-up check (``Antidetect.exe --selftest``) lives in build.py.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

MIN_SIZE_BYTES = 20 * 1024 * 1024
SIDE_CAR_SUFFIXES = {".dll", ".so", ".dylib", ".pyd", ".py"}


def _file_version(exe: Path) -> str | None:
    """ProductVersion from the exe's resources (Windows only; ``None`` elsewhere)."""
    if sys.platform != "win32":
        return None
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"(Get-Item -LiteralPath '{exe}').VersionInfo.ProductVersion"],
        capture_output=True, text=True, timeout=60,
    )
    return proc.stdout.strip() or None


def check(exe: Path, expected_version: str | None = None) -> int:
    if not exe.is_file():
        print(f"ERROR: {exe} does not exist")
        return 1
    size = exe.stat().st_size
    print(f"{exe.name}: {size} bytes")
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

    if expected_version and sys.platform == "win32":
        found = _file_version(exe)
        print(f"file properties version: {found}")
        # "0.2.0" is stored as 0.2.0.0
        if not found or found.split(".")[:3] != expected_version.split(".")[:3]:
            print(f"ERROR: the exe says version {found!r}, the code says {expected_version!r}")
            return 1

    print("Windows artifact OK: standalone onefile exe")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--version", default=None, help="expected product version (checked on Windows only)")
    args = parser.parse_args()
    return check(Path(args.exe), args.version)


if __name__ == "__main__":
    raise SystemExit(main())
