"""End-to-end CLI integration: drives ``python -m antidetect`` as a subprocess against
a stub Chromium binary in an isolated data dir."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture()
def fake_chromium(tmp_path: Path) -> Path:
    script = tmp_path / "fake_chromium.sh"
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'Chromium 152.0.0.0'; exit 0; fi\n"
        "trap 'exit 0' TERM\n"
        "while :; do sleep 0.05; done\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


@pytest.fixture()
def cli_env(tmp_path: Path, fake_chromium: Path):
    env = {
        **os.environ,
        "ANTIDETECT_DATA_DIR": str(tmp_path / "data"),
        "ANTIDETECT_CHROMIUM_PATH": str(fake_chromium),
    }
    return env, tmp_path / "data"


def run_cli(cli_env, *args: str, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "antidetect", *args],
        env=cli_env,
        input=input,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_full_acceptance_flow(cli_env):
    env, data_dir = cli_env

    created = run_cli(env, "profile", "create", "Integration")
    assert created.returncode == 0, created.stderr
    assert "id=1" in created.stdout
    assert "Integration" in created.stdout

    started = run_cli(env, "profile", "start", "1")
    assert started.returncode == 0, started.stderr
    assert "pid=" in started.stdout

    listing = run_cli(env, "profile", "list")
    assert "RUNNING" in listing.stdout
    assert "Integration" in listing.stdout

    profile_dir = data_dir / "profiles" / "profile_001"
    assert profile_dir.is_dir()
    marker = profile_dir / "state.txt"
    marker.write_text("persist-me", encoding="utf-8")

    # duplicate must quiesce the source and copy its state
    duplicated = run_cli(env, "profile", "duplicate", "1", "--name", "Clone")
    assert duplicated.returncode == 0, duplicated.stderr
    assert "Duplicated" in duplicated.stdout
    clone_marker = data_dir / "profiles" / "profile_002" / "state.txt"
    assert clone_marker.read_text(encoding="utf-8") == "persist-me"
    assert "STOPPED" in run_cli(env, "profile", "list").stdout

    stopped = run_cli(env, "profile", "stop", "1")
    assert stopped.returncode == 0, stopped.stderr
    assert marker.exists()

    # restart keeps the same state
    restarted = run_cli(env, "profile", "restart", "1")
    assert restarted.returncode == 0, restarted.stderr
    assert "pid=" in restarted.stdout
    time.sleep(0.3)
    assert "RUNNING" in run_cli(env, "profile", "list").stdout
    assert marker.read_text(encoding="utf-8") == "persist-me"

    shown = run_cli(env, "profile", "show", "1")
    assert "Integration" in shown.stdout
    assert "RUNNING" in shown.stdout

    run_cli(env, "profile", "stop", "1")

    edited = run_cli(env, "profile", "update", "1", "Renamed")
    assert edited.returncode == 0, edited.stderr
    assert "Renamed" in run_cli(env, "profile", "list").stdout

    run_cli(env, "profile", "delete", "1", "--yes")
    gone = run_cli(env, "profile", "list")
    assert "Renamed" not in gone.stdout
    run_cli(env, "profile", "delete", "2", "--yes")


def test_cli_errors_report_to_stderr_with_nonzero_exit(cli_env):
    env, _data = cli_env

    missing = run_cli(env, "profile", "show", "42")
    assert missing.returncode == 1
    assert "Error:" in missing.stderr

    empty_name = run_cli(env, "profile", "create", "   ")
    assert empty_name.returncode == 1
    assert "Error:" in empty_name.stderr

    unknown = run_cli(env, "profile", "frobnicate", "1")
    assert unknown.returncode == 2


def test_cli_delete_aborts_without_confirmation(cli_env):
    env, _data = cli_env
    run_cli(env, "profile", "create", "KeepMe")
    result = run_cli(
        env,
        "profile",
        "delete",
        "1",
        "--permanent",
        input="n\n",
    )
    assert result.returncode == 0
    assert "Aborted" in result.stdout
    assert "KeepMe" in run_cli(env, "profile", "list").stdout


def test_profile_list_empty_message(cli_env):
    env, _data = cli_env
    result = run_cli(env, "profile", "list")
    assert result.returncode == 0
    assert "No profiles yet" in result.stdout