"""``Antidetect --selftest <report.json>``: start the app headlessly and prove the bundle is whole.

The build pipeline runs this against the frozen ``.exe`` / ``.app``. PyInstaller never fails on a
module or a data file it missed, so a broken bundle only shows up when somebody opens it; this runs
the same start-up a user would and writes what it found to a JSON file (the Windows build has no
console, so stdout is not an option). It works in a plain checkout too, and never touches the
user's data: everything happens in a throwaway directory.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

#: Modules PyInstaller cannot see (imported by name or only once a feature is switched on).
_LATE_IMPORTS = (
    "antidetect.api.manager", "antidetect.api.server", "antidetect.api.service", "antidetect.api.settings",
    "antidetect.api.examples", "antidetect.api.reference", "antidetect.gui.pages.api",
    "antidetect.gui.pages.api_docs", "http.server", "socketserver", "websocket", "platformdirs", "certifi",
)


class _Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def run(self, name: str, check) -> None:
        try:
            detail = check()
            self.checks.append({"name": name, "ok": True, "detail": "" if detail is None else str(detail)})
        except BaseException as exc:  # noqa: BLE001 - the whole point is to keep going and report
            self.checks.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}",
                                "trace": traceback.format_exc(limit=6)})

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.checks)


def _resources() -> str:
    from antidetect.domain.models.browser_configuration import BrowserConfiguration
    from antidetect.infrastructure.stealth.payload import build_payload
    from antidetect.infrastructure.stealth.spec import spec_from_configuration
    from antidetect.gui.resources import APP_ICON_PATH, APP_MARK_PATH
    from antidetect.runtime import bundled_cafile

    for icon in (APP_ICON_PATH, APP_MARK_PATH):
        if not Path(icon).is_file():
            raise FileNotFoundError(icon)
    cafile = bundled_cafile()
    if not cafile or not Path(cafile).is_file():
        raise FileNotFoundError("CA bundle (certifi/cacert.pem)")
    payload = build_payload(spec_from_configuration(BrowserConfiguration(id=1, name="selftest"), seed=1))
    if "__CFG__" in payload:
        raise ValueError("the stealth payload template was not filled in")
    return f"payload {len(payload)} chars, CA bundle ok"


def _imports() -> str:
    for name in _LATE_IMPORTS:
        importlib.import_module(name)
    return f"{len(_LATE_IMPORTS)} late imports"


def _window(report: _Report) -> None:
    """Database, main window, every page: what a user's first start goes through."""
    state: dict = {}

    def load() -> str:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication

        from antidetect.container import bootstrap
        from antidetect.gui.app import build_app
        from antidetect.gui.main_window import MainWindow
        from antidetect.gui.sidebar import (
            SECTION_ACTIVITY, SECTION_API, SECTION_PROFILES, SECTION_PROXIES, SECTION_SETTINGS, SECTION_TRASH,
        )
        from antidetect.infrastructure.database.migrations import discover

        state.update(QApplication=QApplication, Gui=QGuiApplication, bootstrap=bootstrap, build_app=build_app,
                     MainWindow=MainWindow, discover=discover,
                     sections=(SECTION_PROFILES, SECTION_PROXIES, SECTION_ACTIVITY, SECTION_API, SECTION_TRASH,
                               SECTION_SETTINGS))
        return "PySide6 and the GUI import"

    def database() -> str:
        state["container"] = container = state["bootstrap"]()
        applied = [r["version"] for r in container.db.execute("SELECT version FROM schema_migrations ORDER BY version")]
        expected = [m.version for m in state["discover"]()]
        if applied != expected:
            raise AssertionError(f"migrations applied {applied}, expected {expected}")
        container.profiles.list_profiles()
        return f"{len(applied)} migrations applied"

    def show() -> str:
        app = state["app"] = state["build_app"]()
        window = state["window"] = state["MainWindow"](state["container"], defer_first_page=False, prewarm=False)
        window.show()
        app.processEvents()
        return f"platform {state['Gui'].platformName()}"

    def pages() -> str:
        app, window = state["app"], state["window"]
        for key in state["sections"]:
            window.show_section(key)
            app.processEvents()
            if window.page(key) is None:
                raise AssertionError(f"page {key!r} was not built")
        return f"{len(state['sections'])} pages built"

    for name, step in (("application modules", load), ("database + migrations", database), ("main window", show),
                       ("every page opens", pages)):
        report.run(name, step)
        if not report.checks[-1]["ok"]:
            break
    if "window" in state:
        state["window"].close()
        state["app"].processEvents()
    if "container" in state:
        state["container"].close()


def run(report_path: str | None = None) -> int:
    """Run every check, write the JSON report, return the process exit code (0 = all passed)."""
    from antidetect import __version__
    from antidetect.runtime import ensure_ssl_certs, is_frozen

    report = _Report()
    before = os.environ.get("ANTIDETECT_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="antidetect-selftest-") as scratch:
            os.environ["ANTIDETECT_DATA_DIR"] = scratch        # never the user's real data
            ensure_ssl_certs()
            report.run("late imports", _imports)
            report.run("bundled resources", _resources)
            _window(report)
    finally:
        if before is None:
            os.environ.pop("ANTIDETECT_DATA_DIR", None)
        else:
            os.environ["ANTIDETECT_DATA_DIR"] = before
    result = {"version": __version__, "frozen": is_frozen(), "python": sys.version.split()[0],
              "ok": report.ok, "checks": report.checks}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report.ok else 1
