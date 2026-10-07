"""Fixtures shared by the in-process CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def cli_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    binary = tmp_path / "chrome.sh"
    binary.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'Chromium 152.0.0.0'; exit 0; fi\n"
        "trap 'exit 0' TERM\n"
        "while :; do sleep 0.05; done\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(binary))
    # Stub binaries expose no DevTools endpoint, so CDP stealth injection is
    # disabled for CLI-level tests (unit-covered separately in test_stealth_cdp).
    monkeypatch.setenv("ANTIDETECT_DISABLE_STEALTH", "1")
    return tmp_path
