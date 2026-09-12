from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import cli as cli_mod
from app.cli.cli import build_parser, main
from app.domain.errors import ChromiumNotFoundError, ProfileNotFoundError


@pytest.fixture()
def cli_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    binary = tmp_path / "chrome.sh"
    binary.write_text("#!/bin/sh\ntrap 'exit 0' TERM\nwhile :; do sleep 0.05; done\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(binary))
    # Stub binaries expose no DevTools endpoint, so CDP stealth injection is
    # disabled for CLI-level tests (unit-covered separately in test_stealth_cdp).
    monkeypatch.setenv("ANTIDETECT_DISABLE_STEALTH", "1")
    return tmp_path


def test_create_and_list(cli_env, tmp_path, capsys) -> None:
    code = main(["profile", "create", "Test 01", "--configuration-id", "1"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Created profile id=1" in captured.out

    code = main(["profile", "list"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Test 01" in captured.out
    assert "STOPPED" in captured.out


def test_duplicate_then_list(cli_env, capsys) -> None:
    main(["profile", "create", "Alpha"])
    assert main(["profile", "duplicate", "1"]) == 0
    captured = capsys.readouterr()
    assert "Alpha (copy)" in captured.out

    main(["profile", "list"])
    capsys.readouterr()


def test_delete_requires_confirmation(cli_env, capsys, monkeypatch) -> None:
    main(["profile", "create", "Beta"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "y\n")
    assert main(["profile", "delete", "1"]) == 0
    captured = capsys.readouterr()
    assert "Deleted profile" in captured.out


def test_unknown_command_raises_system_exit(cli_env) -> None:
    with pytest.raises(SystemExit):
        main(["profile", "frobnicate"])


def test_edit_alias_updates(cli_env, capsys) -> None:
    main(["profile", "create", "OldName"])
    assert main(["profile", "edit", "1", "NewName"]) == 0
    capsys.readouterr()
    main(["profile", "list"])
    captured = capsys.readouterr()
    assert "NewName" in captured.out
    assert "OldName" not in captured.out


def test_update_configuration_id_through_cli(cli_env, capsys) -> None:
    main(["profile", "create", "CfgSwap"])
    assert main(["profile", "update", "1", "--configuration-id", "1"]) == 0
    capsys.readouterr()


def test_error_is_reported_to_stderr(cli_env, capsys) -> None:
    assert main(["profile", "start", "999"]) == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_main_returns_2_when_chromium_undiscovered(cli_env, capsys, monkeypatch) -> None:
    def boom():
        raise ChromiumNotFoundError()

    monkeypatch.setattr("app.cli.cli.bootstrap", boom)
    assert main(["profile", "list"]) == 2
    captured = capsys.readouterr()
    assert "ANTIDETECT_CHROMIUM_PATH" in captured.err


def test_main_returns_1_on_domain_error(cli_env, capsys, monkeypatch) -> None:
    def raiser(service, args):
        raise ProfileNotFoundError(args.id)

    monkeypatch.setitem(cli_mod._HANDLERS, "show", raiser)
    assert main(["profile", "show", "1"]) == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_main_returns_1_on_value_error(cli_env, capsys, monkeypatch) -> None:
    def raiser(service, args):
        raise ValueError("bad value")

    monkeypatch.setitem(cli_mod._HANDLERS, "create", raiser)
    assert main(["profile", "create", "X"]) == 1
    captured = capsys.readouterr()
    assert "Error: bad value" in captured.err


def test_build_parser_has_all_commands() -> None:
    parser = build_parser()
    profile = parser._subparsers._group_actions[0].choices["profile"]  # type: ignore[union-attr]
    commands = {action.dest: action.choices for action in profile._actions if hasattr(action, "choices")}
    names = set()
    for choices in commands.values():
        if choices:
            names.update(choices)
    assert {"create", "list", "show", "update", "edit", "start", "stop", "restart", "duplicate", "delete"} <= names