from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.cli.cli import main

# Reuses the cli_env fixture from test_cli.py (env var redirection).
from tests.test_cli import cli_env  # noqa: F401


def _db_path(data_dir: Path) -> Path:
    return data_dir / "antidetect.db"


def _insert_proxy(data_dir: Path, host="1.2.3.4", port=8080, status="WORKING") -> int:
    conn = sqlite3.connect(_db_path(data_dir))
    try:
        cur = conn.execute(
            "INSERT INTO proxies (protocol, host, port, status, created_at, updated_at) "
            "VALUES ('HTTP', ?, ?, ?, "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (host, port, status),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_config_generate_list_and_show(cli_env, capsys) -> None:
    assert main(["config", "generate", "--name", "WinTest", "--from-template", "windows-chrome"]) == 0
    captured = capsys.readouterr()
    assert "Generated configuration id=2" in captured.out

    assert main(["config", "list"]) == 0
    captured = capsys.readouterr()
    assert "WinTest" in captured.out
    assert "windows" in captured.out

    assert main(["config", "show", "2"]) == 0
    captured = capsys.readouterr()
    assert "WinTest" in captured.out
    assert "Windows NT 10.0" in captured.out
    assert "America/New_York" in captured.out


def test_config_create_and_duplicate(cli_env, capsys) -> None:
    assert (
        main(
            [
                "config", "create", "Hand",
                "--user-agent", "TestUA/9.9",
                "--timezone", "Europe/Berlin",
                "--platform", "linux",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["config", "duplicate", "2", "--name", "HandClone"]) == 0
    capsys.readouterr()

    assert main(["config", "list"]) == 0
    captured = capsys.readouterr()
    assert "Hand" in captured.out
    assert "HandClone" in captured.out


def test_config_delete_detaches_profiles(cli_env, capsys) -> None:
    assert main(["config", "create", "Temp", "--timezone", "Asia/Tokyo"]) == 0
    capsys.readouterr()
    assert main(["profile", "create", "Linked", "--configuration-id", "2"]) == 0
    capsys.readouterr()

    assert main(["config", "delete", "2"]) == 0
    capsys.readouterr()

    assert main(["profile", "show", "1"]) == 0
    captured = capsys.readouterr()
    assert "None (start requires a configuration)" in captured.out


def test_profile_proxy_assign_remove_cli(cli_env, capsys) -> None:
    assert main(["profile", "list"]) == 0  # bootstraps the database
    capsys.readouterr()
    proxy_id = _insert_proxy(cli_env / "data")

    assert main(["profile", "create", "Proxied", "--proxy-id", str(proxy_id)]) == 0
    captured = capsys.readouterr()
    assert "Created profile id=1" in captured.out

    assert main(["profile", "show", "1"]) == 0
    captured = capsys.readouterr()
    assert "STATUS:    WORKING" in captured.out
    assert "ENDPOINT:  HTTP://1.2.3.4:8080" in captured.out

    assert main(["profile", "proxy", "1", "--remove"]) == 0
    captured = capsys.readouterr()
    assert "Removed proxy from profile id=1" in captured.out

    assert main(["profile", "proxy", "1", "--set", str(proxy_id)]) == 0
    capsys.readouterr()
    assert main(["profile", "show", "1"]) == 0
    captured = capsys.readouterr()
    assert "HTTP://1.2.3.4:8080" in captured.out


def test_profile_list_shows_proxy_columns(cli_env, capsys) -> None:
    assert main(["profile", "list"]) == 0
    capsys.readouterr()
    proxy_id = _insert_proxy(cli_env / "data")
    assert main(["profile", "create", "Tabular", "--proxy-id", str(proxy_id)]) == 0
    capsys.readouterr()

    assert main(["profile", "list"]) == 0
    captured = capsys.readouterr()
    for header in ("ID", "NAME", "PROXY", "IP", "COUNTRY", "PING", "STATUS"):
        assert header in captured.out
    assert "1:1.2.3.4:8080" in captured.out


def test_cookies_export_via_cli(cli_env, capsys) -> None:
    assert main(["profile", "create", "CookieBox"]) == 0
    captured = capsys.readouterr()
    profile_path = captured.out.split("path=")[1].strip()
    cookies_db = Path(profile_path) / "Default" / "Cookies"
    cookies_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cookies_db)
    try:
        conn.execute("CREATE TABLE cookies (value TEXT)")
        conn.execute("INSERT INTO cookies VALUES ('secret-cookie-value')")
        conn.commit()
    finally:
        conn.close()

    assert main(["cookies", "export", "1"]) == 0
    captured = capsys.readouterr()
    assert "Exported cookies of profile 1 to" in captured.out
    exported = Path(captured.out.split(" to ")[1].strip())
    assert exported.is_file()

    # The CLI must never print cookie payloads.
    assert "secret-cookie-value" not in captured.out


def test_cookies_export_errors_when_no_cookies(cli_env, capsys) -> None:
    assert main(["profile", "create", "Empty"]) == 0
    capsys.readouterr()
    assert main(["cookies", "export", "1"]) == 1
    captured = capsys.readouterr()
    assert "no cookies" in captured.err


def test_cookies_import_rejects_running_profile(cli_env, capsys) -> None:
    assert main(["profile", "create", "LiveRule"]) == 0
    captured = capsys.readouterr()
    profile_path = Path(captured.out.split("path=")[1].strip())
    source = profile_path / "backup.db"
    source.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(source)
    try:
        conn.execute("CREATE TABLE cookies (value TEXT)")
        conn.execute("INSERT INTO cookies VALUES ('x')")
        conn.commit()
    finally:
        conn.close()

    assert main(["profile", "start", "1"]) == 0
    capsys.readouterr()
    assert main(["cookies", "import", "1", "--from", str(source)]) == 1
    captured = capsys.readouterr()
    assert "stop" in captured.err
    assert main(["profile", "stop", "1"]) == 0


def test_cli_end_to_end_flow(cli_env, capsys) -> None:
    """The Stage-3 acceptance flow beginning-to-end through the CLI:
    config -> profile -> proxy -> start -> stop -> restart -> persisted state."""
    assert main(["config", "generate", "--name", "E2E", "--from-template", "macos-chrome"]) == 0
    capsys.readouterr()

    assert main(["profile", "create", "E2E Profile", "--configuration-id", "2"]) == 0
    capsys.readouterr()

    proxy_id = _insert_proxy(cli_env / "data")
    assert main(["profile", "proxy", "1", "--set", str(proxy_id)]) == 0
    capsys.readouterr()

    assert main(["profile", "start", "1"]) == 0
    captured = capsys.readouterr()
    assert "Started profile id=1 pid=" in captured.out

    assert main(["profile", "show", "1"]) == 0
    captured = capsys.readouterr()
    assert "STATUS:        RUNNING" in captured.out
    assert "E2E" in captured.out

    assert main(["profile", "stop", "1"]) == 0
    capsys.readouterr()

    assert main(["profile", "restart", "1"]) == 0
    captured = capsys.readouterr()
    assert "Restarted profile id=1 pid=" in captured.out
    assert main(["profile", "stop", "1"]) == 0
    capsys.readouterr()

    # Everything is durable: a brand-new CLI invocations sees the same state.
    assert main(["profile", "show", "1"]) == 0
    captured = capsys.readouterr()
    assert "E2E Profile" in captured.out
    assert "macos" in captured.out
    assert "HTTP://1.2.3.4:8080" in captured.out


def test_cookies_import_via_cli(cli_env, capsys) -> None:
    assert main(["profile", "create", "RestoreMe"]) == 0
    captured = capsys.readouterr()
    profile_path = Path(captured.out.split("path=")[1].strip())
    source = profile_path / "backup.db"
    source.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(source)
    try:
        conn.execute("CREATE TABLE cookies (value TEXT)")
        conn.execute("INSERT INTO cookies VALUES ('restored-value')")
        conn.commit()
    finally:
        conn.close()

    assert main(["cookies", "import", "1", "--from", str(source)]) == 0
    captured = capsys.readouterr()
    assert "Imported cookies into profile 1" in captured.out
    assert "restored-value" not in captured.out