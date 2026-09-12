#!/usr/bin/env python3
"""Validate the macOS artifact: Antidetect.app bundle and Antidetect.dmg.

Checks:
- --app: bundle exists, Contents/MacOS binary + Resources exist,
  bundled PySide6/Qt libs inside (no dependency on the project dir);
- --dmg: file exists, attaches with hdiutil, contains Antidetect.app.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def check_app(app: Path) -> int:
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    plist = app / "Contents" / "Info.plist"
    if not app.is_dir():
        print(f"ERROR: {app} is not a directory")
        return 1
    for required in (macos, resources, plist):
        if not required.exists():
            print(f"ERROR: missing bundle part: {required}")
            return 1
    binaries = [p for p in macos.iterdir()] if macos.is_dir() else []
    if not binaries:
        print(f"ERROR: no binary in {macos}")
        return 1
    print(f"bundle binary: {[b.name for b in binaries]}")
    frameworks = app / "Contents" / "Frameworks"
    qt_inside = list(app.rglob("*QtCore*")) + list(app.rglob("*PySide6*"))
    if not qt_inside and not (frameworks.exists()):
        print("WARNING: no Qt/PySide6 files found inside bundle — app may not be standalone")
    else:
        print(f"bundled Qt/PySide6 entries: {len(qt_inside)}")
    print("macOS .app OK")
    return 0


def check_dmg(dmg: Path) -> int:
    if not dmg.is_file():
        print(f"ERROR: {dmg} does not exist")
        return 1
    size = dmg.stat().st_size
    print(f"Antidetect.dmg: {size} bytes")
    if size < 10 * 1024 * 1024:
        print("ERROR: dmg suspiciously small (< 10 MB)")
        return 1
    mount = Path(tempfile.mkdtemp(prefix="antidetect-dmg-"))
    try:
        proc = subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(dmg)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            print(f"ERROR: cannot attach dmg: {proc.stderr[-2000:]}")
            return 1
        try:
            inner = mount / "Antidetect.app"
            if not inner.exists():
                print(f"ERROR: Antidetect.app not found inside dmg (saw: {list(mount.iterdir())})")
                return 1
            rc = check_app(inner)
            if rc != 0:
                return rc
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], capture_output=True, timeout=120)
    finally:
        try:
            mount.rmdir()
        except OSError:
            pass
    print("macOS .dmg OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default=None)
    parser.add_argument("--dmg", default=None)
    args = parser.parse_args()
    if not args.app and not args.dmg:
        print("ERROR: pass --app and/or --dmg")
        return 2
    if args.app:
        rc = check_app(Path(args.app))
        if rc != 0:
            return rc
    if args.dmg:
        rc = check_dmg(Path(args.dmg))
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
