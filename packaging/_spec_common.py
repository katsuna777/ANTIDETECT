"""Shared pieces of the PyInstaller specs (imported by macos.spec / windows.spec)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PKG = SRC / "antidetect"
RES = PKG / "gui" / "resources"
ENTRY = PKG / "gui" / "__main__.py"

# Only these Qt bindings are used. Everything else in PySide6 is dead weight in
# the bundle (and in start-up time), so keep it out explicitly.
_QT_UNUSED = (
    "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
    "QtAxContainer", "QtBluetooth", "QtCharts", "QtConcurrent", "QtDataVisualization",
    "QtDesigner", "QtGraphs", "QtHelp", "QtHttpServer", "QtLocation", "QtMultimedia",
    "QtMultimediaWidgets", "QtNetwork", "QtNetworkAuth", "QtNfc", "QtOpenGL",
    "QtOpenGLWidgets", "QtPdf", "QtPdfWidgets", "QtPositioning", "QtPrintSupport",
    "QtQml", "QtQuick", "QtQuick3D", "QtQuickControls2", "QtQuickWidgets",
    "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort",
    "QtShaderTools", "QtSpatialAudio", "QtSql", "QtStateMachine", "QtTest",
    "QtTextToSpeech", "QtUiTools", "QtVirtualKeyboard", "QtWebChannel", "QtWebEngineCore",
    "QtWebEngineQuick", "QtWebEngineWidgets", "QtWebSockets", "QtWebView", "QtXml",
)
EXCLUDES = [f"PySide6.{name}" for name in _QT_UNUSED] + [
    "tkinter", "unittest", "pydoc", "doctest", "lib2to3", "distutils", "setuptools", "pip",
    "pytest", "xdist",
]


def datas() -> list[tuple[str, str]]:
    """Read-only resources the frozen app opens at runtime."""
    items: list[tuple[str, str]] = []
    for name in ("icon.png", "icon-128.png", "icon.icns", "icon.ico"):
        if (RES / name).is_file():
            items.append((str(RES / name), "antidetect/gui/resources"))
    # The in-page fingerprint script is read at runtime (stealth/payload.py). Without
    # it the protection layer cannot start, so the build fails here instead.
    payload = PKG / "infrastructure" / "stealth" / "js" / "payload.js"
    if not payload.is_file():
        raise SystemExit(f"missing required resource: {payload}")
    items.append((str(payload), "antidetect/infrastructure/stealth/js"))
    # certifi is a hard requirement: without its CA bundle every https:// fetch
    # (proxy sources) fails verification on user machines, whose OpenSSL paths
    # differ from the build machine's. Fail loudly here, not silently at runtime.
    try:
        import certifi
    except ImportError as exc:
        raise SystemExit('certifi is required for the build (pip install -e ".[build]")') from exc
    items.append((certifi.where(), "certifi"))
    return items


def hiddenimports() -> list[str]:
    """Migrations are loaded via importlib (see infrastructure/database/migrations),
    so PyInstaller's static analysis misses them — list them explicitly."""
    package = "antidetect.infrastructure.database.migrations.versions"
    versions = PKG / "infrastructure" / "database" / "migrations" / "versions"
    modules = [f"{package}.{p.stem}" for p in sorted(versions.glob("*.py")) if p.stem != "__init__"]
    # The API is imported only once it is switched on (and by name from a lazy ``__getattr__``),
    # so list it too; http.server is what it listens with.
    api = ["antidetect.api.manager", "antidetect.api.server", "antidetect.api.service", "antidetect.api.settings",
           "antidetect.api.examples", "antidetect.api.reference", "antidetect.gui.pages.api",
           "antidetect.gui.pages.api_docs", "http.server", "socketserver"]
    return ["websocket", "platformdirs", "certifi", package, *modules, *api]


def drop_qt_extras(entries):
    """Strip Qt translations and QML payload that a widgets-only app never loads."""
    skip = ("/translations/", "\\translations\\", "/qml/", "\\qml\\")
    return [e for e in entries if not any(marker in e[0] or marker in e[1] for marker in skip)]


def version() -> str:
    namespace: dict = {}
    exec((PKG / "__init__.py").read_text(encoding="utf-8"), namespace)
    return namespace["__version__"]


def windows_version_file() -> str:
    """Write the resource that fills the exe's Properties -> Details tab (name, version) and return its path.

    Without it the file shows no version at all, which looks like malware to people and to antivirus engines.
    """
    ver = version()
    nums = [int(n) for n in re.findall(r"\d+", ver)[:4]]
    nums += [0] * (4 - len(nums))
    quad = ", ".join(str(n) for n in nums)
    fields = {
        "CompanyName": "Antidetect", "FileDescription": "Antidetect", "FileVersion": ver,
        "InternalName": "Antidetect", "OriginalFilename": "Antidetect.exe",
        "ProductName": "Antidetect", "ProductVersion": ver,
    }
    strings = ",\n        ".join(f"StringStruct({k!r}, {v!r})" for k, v in fields.items())
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({quad}), prodvers=({quad}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        {strings}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    target = ROOT / "build" / "version_info.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)
