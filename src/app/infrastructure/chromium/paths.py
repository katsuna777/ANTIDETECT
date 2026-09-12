from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.domain.errors import ChromiumNotFoundError

def _windows_install_paths() -> list[Path]:
    """Build Windows candidate paths from current env (not import-time)."""
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    program_w6432 = os.environ.get("PROGRAMW6432", program_files)
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(program_files) / "Google/Chrome/Application/chrome.exe",
        Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
        Path(program_w6432) / "Google/Chrome/Application/chrome.exe",
        # Chrome Beta / Dev / Canary (SxS)
        Path(program_files) / "Google/Chrome Beta/Application/chrome.exe",
        Path(program_files) / "Google/Chrome Dev/Application/chrome.exe",
        Path(local_app_data) / "Google/Chrome/Application/chrome.exe" if local_app_data else None,
        Path(local_app_data) / "Google/Chrome SxS/Application/chrome.exe" if local_app_data else None,
        # Chromium / Brave / Edge on Windows
        Path(program_files) / "Chromium/Application/chrome.exe",
        Path(program_files) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(program_files_x86) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(local_app_data) / "BraveSoftware/Brave-Browser/Application/brave.exe" if local_app_data else None,
        Path(program_files) / "Microsoft/Edge/Application/msedge.exe",
        Path(program_files_x86) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return [p for p in candidates if p is not None]


def _registry_candidates() -> list[Path]:
    """Chrome-family paths from Windows registry App Paths (best effort)."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    names = ("chrome.exe", "msedge.exe", "brave.exe", "chromium.exe")
    roots = []
    try:
        roots.append(winreg.HKEY_LOCAL_MACHINE)
    except AttributeError:
        return []
    try:
        roots.append(winreg.HKEY_CURRENT_USER)
    except AttributeError:
        pass
    found: list[Path] = []
    for root in roots:
        for name in names:
            for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(
                        root,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}",
                        0,
                        winreg.KEY_READ | view,
                    ) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                        candidate = Path(str(value).strip().strip('"'))
                        if candidate.is_file():
                            found.append(candidate)
                except OSError:
                    continue
    return found


def _clean_env_path(value: str) -> Path | None:
    """Strip quotes/whitespace from env-provided paths (Windows loves quotes)."""
    cleaned = value.strip().strip('"').strip("'").strip()
    if not cleaned:
        return None
    return Path(cleaned).expanduser()


_KNOWN_PATHS: dict[str, list[Path]] = {
    "darwin": [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path.home() / "Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "win32": [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Public")) / "Google/Chrome/Application/chrome.exe",
    ],
    "linux": [
        Path("/opt/google/chrome/chrome"),
        Path("/opt/google/chrome-beta/chrome"),
        Path("/opt/google/chrome-unstable/chrome"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/google-chrome-beta"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/snap/bin/chromium"),
        Path("/var/lib/flatpak/exports/bin/com.google.Chrome"),
        Path.home() / ".local/bin/google-chrome",
    ],
}

_KNOWN_COMMANDS = [
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "microsoft-edge",
    "chrome",
    "chrome.exe",
    "msedge",
    "msedge.exe",
    "brave",
    "brave.exe",
]


def discover_chromium(override: str | None = None) -> Path:
    """Locate a Chromium-based executable.

    Precedence: explicit override -> ``ANTIDETECT_CHROMIUM_PATH`` /
    ``CHROME_PATH`` env vars -> well-known install paths -> ``PATH`` commands.
    """
    if override:
        resolved = _clean_env_path(override)
        if resolved is not None and resolved.is_file():
            return resolved
        raise ChromiumNotFoundError()

    for env_var in ("ANTIDETECT_CHROMIUM_PATH", "CHROME_PATH"):
        value = os.environ.get(env_var)
        if value:
            candidate = _clean_env_path(value)
            if candidate is not None and candidate.is_file():
                return candidate

    platform_key = sys.platform
    # cygwin/msys python reports cygwin/win32-ish platforms but runs Windows
    # binaries — treat them like win32 for discovery purposes.
    if platform_key.startswith(("cygwin", "msys")):
        platform_key = "win32"
    if platform_key in _KNOWN_PATHS:
        for candidate in _KNOWN_PATHS[platform_key]:
            if candidate.is_file():
                return candidate
    if platform_key == "win32" or sys.platform == "win32":
        for candidate in _windows_install_paths():
            if candidate.is_file():
                return candidate
        for candidate in _registry_candidates():
            if candidate.is_file():
                return candidate

    for command in _KNOWN_COMMANDS:
        found = shutil.which(command)
        if found:
            return Path(found)

    raise ChromiumNotFoundError()