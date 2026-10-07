from __future__ import annotations


import pytest

from antidetect.cli import main as cli_mod
from antidetect.cli.main import build_parser, main
from antidetect.domain.errors import ChromiumNotFoundError, ProfileNotFoundError


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


def test_delete_moves_to_the_trash_and_restore_brings_it_back(cli_env, capsys) -> None:
    main(["profile", "create", "Beta"])
    assert main(["profile", "delete", "1"]) == 0
    assert "trash" in capsys.readouterr().out
    main(["profile", "list"])
    assert "Beta" not in capsys.readouterr().out
    assert main(["profile", "trash"]) == 0
    assert "Beta" in capsys.readouterr().out
    assert main(["profile", "restore", "1"]) == 0
    capsys.readouterr()
    main(["profile", "list"])
    assert "Beta" in capsys.readouterr().out


def test_permanent_delete_requires_confirmation(cli_env, capsys, monkeypatch) -> None:
    main(["profile", "create", "Beta"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "n\n")
    assert main(["profile", "delete", "1", "--permanent"]) == 0
    assert "Aborted" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda _prompt: "y\n")
    assert main(["profile", "delete", "1", "--permanent"]) == 0
    assert "for good" in capsys.readouterr().out
    main(["profile", "trash"])
    assert "empty" in capsys.readouterr().out


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

    monkeypatch.setattr("antidetect.cli.main.bootstrap", boom)
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

# ------------------------------------------------------------ protection switches

def _protection_line(capsys, profile_id: int = 1) -> str:
    assert main(["profile", "show", str(profile_id)]) == 0
    return next(line for line in capsys.readouterr().out.splitlines() if "PROTECTION" in line).strip()


def test_a_new_profile_shows_the_default_protection(cli_env, capsys) -> None:
    main(["profile", "create", "Plain"])
    capsys.readouterr()
    assert _protection_line(capsys) == "PROTECTION:  webrtc=auto theme=light canvas-noise=on audio-noise=on"


def test_the_switches_are_chosen_on_create_and_changed_on_update(cli_env, capsys) -> None:
    assert main(["profile", "create", "Careful", "--webrtc", "block", "--no-canvas-noise"]) == 0
    capsys.readouterr()
    assert _protection_line(capsys) == "PROTECTION:  webrtc=block theme=light canvas-noise=off audio-noise=on"

    assert main(["profile", "update", "1", "--webrtc", "allow", "--canvas-noise", "--no-audio-noise"]) == 0
    capsys.readouterr()
    assert _protection_line(capsys) == "PROTECTION:  webrtc=allow theme=light canvas-noise=on audio-noise=off"


def test_contradicting_switches_are_refused(cli_env, capsys) -> None:
    main(["profile", "create", "Same"])
    capsys.readouterr()
    assert main(["profile", "update", "1", "--canvas-noise", "--no-canvas-noise"]) != 0
    assert "contradict" in capsys.readouterr().err
    assert _protection_line(capsys) == "PROTECTION:  webrtc=auto theme=light canvas-noise=on audio-noise=on"


def test_an_unknown_webrtc_mode_is_rejected_by_the_parser(cli_env) -> None:
    with pytest.raises(SystemExit):
        main(["profile", "create", "X", "--webrtc", "maybe"])


def test_the_colour_scheme_is_chosen_on_create_changed_on_update_and_is_light_by_default(cli_env, capsys) -> None:
    main(["profile", "create", "Plain"])
    capsys.readouterr()
    assert "theme=light" in _protection_line(capsys)
    assert main(["profile", "create", "Dark one", "--theme", "dark"]) == 0
    capsys.readouterr()
    assert "theme=dark" in _protection_line(capsys, 2)
    assert main(["profile", "update", "1", "--theme", "auto"]) == 0
    capsys.readouterr()
    assert "theme=auto" in _protection_line(capsys, 1)
    with pytest.raises(SystemExit):
        main(["profile", "update", "1", "--theme", "blue"])
