#!/usr/bin/env python3
"""Build, check and pack Antidetect for the OS this runs on (one script for CI and for a local build).

    python packaging/build.py               # Windows: release/Antidetect-<version>-windows-x64.exe
                                            # macOS:   release/Antidetect-<version>-macos-<arm64|x64>.dmg
    python packaging/build.py --no-smoke    # skip starting the finished app

Steps: environment check -> PyInstaller -> missing-module scan -> bundle validation -> (macOS: sign,
.dmg, notarize) -> the frozen app starts itself in ``--selftest`` mode -> versioned file + SHA-256.

macOS signing is opt-in through the environment (nothing is needed for an unsigned, ad-hoc build):
    MACOS_CODESIGN_IDENTITY   "Developer ID Application: Name (TEAMID)" - sign with hardened runtime
    APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD   - also notarize and staple the .dmg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import check_build_env  # noqa: E402
import check_warn  # noqa: E402
import validate_macos  # noqa: E402
import validate_windows  # noqa: E402

APP = "Antidetect"


def say(text: str) -> None:
    print(f"\n==> {text}", flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def version() -> str:
    namespace: dict = {}
    exec((ROOT / "src" / "antidetect" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return namespace["__version__"]


def target() -> tuple[str, str]:
    """(os, arch) names used in file names: windows-x64, macos-arm64, macos-x64."""
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if sys.platform == "win32":
        return "windows", arch
    if sys.platform == "darwin":
        return "macos", arch
    raise SystemExit(f"unsupported build OS: {sys.platform} (Windows and macOS only)")


def must(code: int, what: str) -> None:
    if code != 0:
        raise SystemExit(f"FAILED: {what}")


def pyinstaller(spec: Path) -> None:
    say(f"PyInstaller ({spec.name})")
    for stale in (ROOT / "dist", ROOT / "build" / spec.stem):
        shutil.rmtree(stale, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", ROOT / "dist",
         "--workpath", ROOT / "build", spec], cwd=ROOT)
    must(check_warn.main_for(ROOT / "build" / spec.stem / f"warn-{spec.stem}.txt"), "required module missing from the bundle")


def smoke(binary: Path, extra_env: dict[str, str]) -> None:
    """Start the frozen app in self-test mode: the same start-up a user goes through, no window left behind."""
    say("self-test of the frozen app")
    with tempfile.TemporaryDirectory(prefix="antidetect-smoke-") as scratch:
        report = Path(scratch) / "selftest.json"
        started = time.monotonic()
        try:
            proc = subprocess.run([str(binary), "--selftest", str(report)], env={**os.environ, **extra_env},
                                  timeout=300, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            raise SystemExit("FAILED: the frozen app did not finish its self-test in 5 minutes")
        took = time.monotonic() - started
        if not report.is_file():
            tail = ((proc.stderr or "") + (proc.stdout or ""))[-3000:]
            raise SystemExit(f"FAILED: the frozen app wrote no self-test report (exit {proc.returncode}, {took:.0f}s)\n{tail}")
        data = json.loads(report.read_text(encoding="utf-8"))
    for check in data["checks"]:
        print(f"  {'ok  ' if check['ok'] else 'FAIL'} {check['name']}: {check['detail']}")
        if not check["ok"]:
            print(check.get("trace", ""))
    if not data["frozen"]:
        raise SystemExit("FAILED: the self-test ran from source, not from the frozen app")
    if not data["ok"] or proc.returncode != 0:
        raise SystemExit("FAILED: the frozen app's self-test reported problems (above)")
    print(f"self-test passed in {took:.1f}s")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish(built: Path, final_name: str) -> Path:
    """Copy into release/ under the versioned name, write the checksum beside it, tell GitHub Actions."""
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    final = release / final_name
    final.unlink(missing_ok=True)
    shutil.copy2(built, final)
    (release / f"{final_name}.sha256").write_text(f"{sha256(final)}  {final_name}\n", encoding="utf-8")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as handle:
            handle.write(f"artifact={final_name}\n")
    print(f"\nOK: {final}  ({final.stat().st_size / 1e6:.1f} MB)")
    return final


# ---------------------------------------------------------------------------------------------- Windows
def build_windows(args: argparse.Namespace, name: str) -> None:
    pyinstaller(HERE / "windows.spec")
    exe = ROOT / "dist" / f"{APP}.exe"
    must(validate_windows.check(exe, expected_version=version()), "Windows artifact validation")
    if not args.no_smoke:
        smoke(exe, {"QT_QPA_PLATFORM": args.qt_platform} if args.qt_platform else {})
    publish(exe, name)


# ---------------------------------------------------------------------------------------------- macOS
def codesign(app: Path, identity: str) -> None:
    say("code signing" + ("" if identity else " (ad-hoc: no Developer ID configured)"))
    if identity:
        run(["codesign", "--force", "--deep", "--timestamp", "--options", "runtime", "--entitlements",
             HERE / "entitlements.plist", "--sign", identity, app])
    else:
        run(["codesign", "--force", "--deep", "--sign", "-", app])      # arm64 refuses to run unsigned code
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=1", app])


def make_dmg(app: Path, dmg: Path) -> None:
    say("packing .dmg")
    stage = Path(tempfile.mkdtemp(prefix="antidetect-dmg-stage-"))
    try:
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        dmg.unlink(missing_ok=True)
        for attempt in range(1, 4):                                    # hdiutil sometimes answers "Resource busy" on runners
            try:
                run(["hdiutil", "create", "-volname", "ANTIDETECT", "-srcfolder", stage, "-ov", "-format", "UDZO", dmg])
                return
            except subprocess.CalledProcessError:
                if attempt == 3:
                    raise
                time.sleep(5 * attempt)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def notarize(dmg: Path, identity: str) -> None:
    creds = [os.environ.get(k, "").strip() for k in ("APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_PASSWORD")]
    if not identity or not all(creds):
        print("notarization skipped (needs MACOS_CODESIGN_IDENTITY, APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD)")
        return
    say("notarization (can take a few minutes)")
    run(["codesign", "--force", "--timestamp", "--sign", identity, dmg])
    run(["xcrun", "notarytool", "submit", dmg, "--apple-id", creds[0], "--team-id", creds[1], "--password", creds[2], "--wait"])
    run(["xcrun", "stapler", "staple", dmg])


def build_macos(args: argparse.Namespace, name: str) -> None:
    pyinstaller(HERE / "macos.spec")
    app = ROOT / "dist" / f"{APP}.app"
    must(validate_macos.check_app(app), "macOS bundle validation")
    identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "").strip()
    codesign(app, identity)
    if not args.no_smoke:
        smoke(app / "Contents" / "MacOS" / APP, {"QT_QPA_PLATFORM": args.qt_platform} if args.qt_platform else {})
    dmg = ROOT / "dist" / f"{APP}.dmg"
    make_dmg(app, dmg)
    notarize(dmg, identity)
    must(validate_macos.check_dmg(dmg), "dmg validation")
    publish(dmg, name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-smoke", action="store_true", help="do not start the finished app")
    parser.add_argument("--qt-platform", default="", help="QT_QPA_PLATFORM for the self-test (e.g. offscreen); default: the real one")
    args = parser.parse_args()

    os_name, arch = target()
    ext = "exe" if os_name == "windows" else "dmg"
    name = f"{APP}-{version()}-{os_name}-{arch}.{ext}"
    say(f"{name}   (python {platform.python_version()}, {platform.platform()})")
    must(check_build_env.main(), "build environment")
    (build_windows if os_name == "windows" else build_macos)(args, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
