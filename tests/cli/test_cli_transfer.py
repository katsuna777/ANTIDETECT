"""``profile bulk`` / ``export`` / ``import`` from the command line."""

from __future__ import annotations

import zipfile

import pytest

from antidetect.cli.main import main


def _ids_and_names(capsys) -> list[str]:
    main(["profile", "list"])
    lines = capsys.readouterr().out.splitlines()[1:]
    return [line.split()[1] if len(line.split()) > 1 else "" for line in lines]


def test_bulk_creates_numbered_profiles_and_reports_them(cli_env, capsys) -> None:
    assert main(["profile", "bulk", "Shop", "--count", "3", "--platform", "windows", "--no-geo-auto"]) == 0
    out = capsys.readouterr().out
    assert "Created 3 of 3 profiles (0 with a proxy, 3 without)" in out
    assert "Shop 1" in out and "Shop 3" in out
    main(["profile", "list"])
    assert capsys.readouterr().out.count("STOPPED") == 3


def test_bulk_gives_each_profile_the_next_proxy_from_the_file(cli_env, capsys, tmp_path) -> None:
    proxies = tmp_path / "proxies.txt"
    proxies.write_text("203.0.113.1:8080\n203.0.113.2:8080\n# comment\nnot a proxy\n")
    code = main(["profile", "bulk", "P", "--count", "3", "--proxies-file", str(proxies), "--no-geo-auto"])
    captured = capsys.readouterr()
    assert code == 0 and "(2 with a proxy, 1 without)" in captured.out
    assert "Unreadable proxy line skipped: not a proxy" in captured.err
    main(["profile", "show", "1"])
    assert "203.0.113.1:8080" in capsys.readouterr().out                 # the first proxy goes to the first profile
    main(["profile", "show", "2"])
    assert "203.0.113.2:8080" in capsys.readouterr().out
    main(["profile", "show", "3"])
    assert "None (unproxied browsing)" in capsys.readouterr().out         # the list ran out: none is shared


def test_bulk_applies_the_common_settings(cli_env, capsys) -> None:
    assert main(["profile", "bulk", "A", "--count", "2", "--tags", "eu,shop", "--workspace", "Clients",
                 "--webrtc", "block", "--no-audio-noise", "--no-geo-auto"]) == 0
    capsys.readouterr()
    main(["profile", "show", "1"])
    out = capsys.readouterr().out
    assert "webrtc=block theme=light canvas-noise=on audio-noise=off" in out


@pytest.mark.parametrize("count", ["0", "201", "-3"])
def test_bulk_refuses_a_bad_count(cli_env, capsys, count) -> None:
    assert main(["profile", "bulk", "X", "--count", count]) == 1
    assert "between 1 and 200" in capsys.readouterr().err


def test_bulk_without_a_count_is_a_usage_error(cli_env) -> None:
    with pytest.raises(SystemExit):
        main(["profile", "bulk", "X"])


def test_bulk_reports_a_missing_proxy_file(cli_env, capsys, tmp_path) -> None:
    assert main(["profile", "bulk", "X", "--count", "1", "--proxies-file", str(tmp_path / "nope.txt")]) == 1
    assert "Cannot read" in capsys.readouterr().err


def test_export_then_import_round_trips_a_profile(cli_env, capsys, tmp_path) -> None:
    main(["profile", "create", "Original", "--tags", "eu", "--notes", "keep", "--webrtc", "allow"])
    capsys.readouterr()
    target = tmp_path / "backup.zip"
    assert main(["profile", "export", "1", "--to", str(target)]) == 0
    out = capsys.readouterr().out
    assert f"to {target}" in out and "tied to this computer" in out
    with zipfile.ZipFile(target) as z:
        assert "manifest.json" in z.namelist()

    assert main(["profile", "import", str(target)]) == 0
    assert "name='Original (imported)'" in capsys.readouterr().out
    assert main(["profile", "import", str(target), "--name", "Chosen"]) == 0
    capsys.readouterr()
    main(["profile", "show", "3"])
    shown = capsys.readouterr().out
    assert "Chosen" in shown and "webrtc=allow" in shown


def test_export_into_a_folder_and_the_proxy_warning(cli_env, capsys, tmp_path) -> None:
    main(["proxy", "add", "user:pw@203.0.113.9:8080"])
    main(["profile", "create", "Prox", "--proxy-id", "1", "--no-auto-config", "--no-geo-auto"])
    capsys.readouterr()
    assert main(["profile", "export", "1", "--to", str(tmp_path), "--with-proxy"]) == 0
    out = capsys.readouterr().out
    assert "plain text" in out and (tmp_path / "Prox.zip").is_file()


def test_import_of_something_that_is_not_an_archive_fails_cleanly(cli_env, capsys, tmp_path) -> None:
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"nope")
    assert main(["profile", "import", str(junk)]) == 1
    assert "not a valid archive" in capsys.readouterr().err
    assert main(["profile", "import", str(tmp_path / "missing.zip")]) == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_bulk_can_set_the_colour_scheme_for_all(cli_env, capsys) -> None:
    assert main(["profile", "bulk", "D", "--count", "2", "--theme", "dark", "--no-geo-auto"]) == 0
    capsys.readouterr()
    for profile_id in (1, 2):
        main(["profile", "show", str(profile_id)])
        assert "theme=dark" in capsys.readouterr().out
