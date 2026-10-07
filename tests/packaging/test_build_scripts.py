"""The build pipeline's own scripts: the frozen-app self-test, the warn scan, version stamping."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"


@pytest.fixture(scope="module")
def spec_common():
    sys.path.insert(0, str(PACKAGING))
    try:
        import _spec_common
        yield _spec_common
    finally:
        sys.path.remove(str(PACKAGING))


def test_the_selftest_runs_from_source_and_leaves_the_real_data_alone(tmp_path):
    """``antidetect-gui --selftest`` is what build.py runs against the frozen app: it must pass here too."""
    report = tmp_path / "report.json"
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT / "src")}
    env.pop("ANTIDETECT_DATA_DIR", None)
    proc = subprocess.run([sys.executable, "-m", "antidetect.gui", "--selftest", str(report)], env=env,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["ok"] and not data["frozen"]
    names = [c["name"] for c in data["checks"]]
    assert names == ["late imports", "bundled resources", "application modules", "database + migrations",
                     "main window", "every page opens"]
    assert all(c["ok"] for c in data["checks"])


def _selftest_in_a_child(tmp_path, body: str) -> subprocess.CompletedProcess:
    """Run ``body`` in a separate interpreter: the self-test builds a QApplication and sets the UI language,
    which must not leak into the other tests of this process."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT / "src")}
    env.pop("ANTIDETECT_DATA_DIR", None)
    return subprocess.run([sys.executable, "-c", body, str(tmp_path / "report.json")], env=env,
                          capture_output=True, text=True, timeout=180)


def test_the_selftest_reports_a_missing_resource_instead_of_crashing(tmp_path):
    proc = _selftest_in_a_child(tmp_path, """
import sys
from antidetect.gui import selftest
def broken():
    raise FileNotFoundError("payload.js")
selftest._resources = broken
raise SystemExit(selftest.run(sys.argv[1]))
""")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    failed = [c for c in data["checks"] if not c["ok"]]
    assert [c["name"] for c in failed] == ["bundled resources"] and "payload.js" in failed[0]["detail"]
    assert any(c["name"] == "every page opens" and c["ok"] for c in data["checks"]), "later checks must still run"


def test_the_selftest_restores_the_data_dir_variable(tmp_path):
    proc = _selftest_in_a_child(tmp_path, """
import os, sys
os.environ["ANTIDETECT_DATA_DIR"] = "before"
from antidetect.gui import selftest
selftest.run(sys.argv[1])
raise SystemExit(0 if os.environ["ANTIDETECT_DATA_DIR"] == "before" else 3)
""")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_warn_scan_fails_on_a_missing_required_module_a_missing_file_and_passes_when_clean(tmp_path):
    sys.path.insert(0, str(PACKAGING))
    try:
        import check_warn
    finally:
        sys.path.remove(str(PACKAGING))

    warn = tmp_path / "warn.txt"
    warn.write_text("missing module named resource - imported by x\nmissing module named posix\n")
    assert check_warn.scan(warn) == 0                                   # optional platform modules are fine
    for name in ("websocket", "certifi", "antidetect.api.server"):
        warn.write_text(f"missing module named {name} - imported by y\n")
        assert check_warn.scan(warn) == 1, name
    assert check_warn.scan(tmp_path / "nope.txt") == 1                  # a wrong path must not pass silently


def test_the_windows_version_resource_carries_the_code_version(spec_common):
    import antidetect

    text = Path(spec_common.windows_version_file()).read_text(encoding="utf-8")
    numbers = ", ".join((re.findall(r"\d+", antidetect.__version__) + ["0"] * 4)[:4])
    assert f"filevers=({numbers})" in text and f"prodvers=({numbers})" in text
    assert f"StringStruct('ProductVersion', '{antidetect.__version__}')" in text
    assert "StringStruct('OriginalFilename', 'Antidetect.exe')" in text


def test_the_version_the_release_workflow_reads_is_what_the_code_exports():
    """release.yml compares the tag with the line ``__version__ = "x"`` via sed: keep that line's shape."""
    import antidetect

    source = (ROOT / "src" / "antidetect" / "__init__.py").read_text(encoding="utf-8")
    assert re.search(r'^__version__ = "([^"]+)"$', source, re.M).group(1) == antidetect.__version__


def test_every_script_and_spec_name_the_same_artifacts(spec_common):
    """build.py names the files; the workflow uploads them by pattern and the README tells users their names."""
    build = (PACKAGING / "build.py").read_text(encoding="utf-8")
    assert 'f"{APP}-{version()}-{os_name}-{arch}.{ext}"' in build
    workflow = (ROOT / ".github" / "workflows" / "_build.yml").read_text(encoding="utf-8")
    assert "release/*" in workflow and "packaging/build.py" in workflow
    assert spec_common.version() == __import__("antidetect").__version__
