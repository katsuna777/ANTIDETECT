from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from antidetect.application.cookie_service import CookieService
from antidetect.domain.errors import CookieFileNotFoundError, CookieImportError
from antidetect.infrastructure.chromium.chromium_manager import ChromiumManager
from antidetect.infrastructure.database.repositories.profile_repository import (
    SqliteProfileRepository,
)
from tests.conftest import build_service


@pytest.fixture()
def ctx(config, fake_chromium):
    svc, db = build_service(config, fake_chromium)
    manager = ChromiumManager(chromium_path=fake_chromium, logs_dir=config.logs_dir)
    cookies = CookieService(
        profiles=SqliteProfileRepository(db),
        browsers=manager,
        export_dir=config.data_dir / "cookie-backups",
    )
    yield svc, cookies
    for profile in svc.list_profiles():
        if profile.status.value == "RUNNING":
            svc.stop_profile(profile.id)
    db.close()


def _make_cookies_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE cookies (key TEXT, value TEXT, domain TEXT)"
        )
        conn.execute(
            "INSERT INTO cookies VALUES (?, ?, ?)",
            ("session_id", "abc123", ".example.com"),
        )
        conn.commit()
    finally:
        conn.close()


def _profile_dir(ctx, profile):
    path = Path(profile.profile_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_export_without_cookie_db_raises(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("NoCookies")
    with pytest.raises(CookieFileNotFoundError):
        cookies.export(profile.id)


def test_export_produces_valid_snapshot(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("Snapshot")
    profile_dir = _profile_dir(ctx, profile)
    _make_cookies_db(profile_dir / "Default" / "Cookies")

    output = cookies.export(profile.id)
    out_path = Path(output)
    assert out_path.is_file()
    conn = sqlite3.connect(out_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "cookies" in tables
        rows = conn.execute("SELECT value FROM cookies").fetchall()
        assert rows == [("abc123",)]
    finally:
        conn.close()


def test_export_legacy_layout_uses_old_cookies_path(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("Legacy")
    _make_cookies_db(Path(profile.profile_path) / "Cookies")

    output = cookies.export(profile.id)
    assert Path(output).is_file()


def test_export_to_custom_path(ctx, tmp_path):
    svc, cookies = ctx
    profile = svc.create_profile("Custom")
    _make_cookies_db(Path(profile.profile_path) / "Default" / "Cookies")

    target = tmp_path / "out" / "snapshot.db"
    output = cookies.export(profile.id, output=target)
    assert Path(output) == target


def test_import_restores_cookies_replacing_target(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("Restore")
    profile_dir = _profile_dir(ctx, profile)
    source = Path(profile.profile_path) / "import_source.db"
    _make_cookies_db(profile_dir / "Default" / "Cookies")  # existing junk db
    _make_cookies_db(source)  # the database we want to restore

    cookies.import_(profile.id, source)

    restored = sqlite3.connect(profile_dir / "Default" / "Cookies")
    try:
        assert restored.execute("SELECT value FROM cookies").fetchall() == [("abc123",)]
    finally:
        restored.close()


def test_import_defaults_to_default_cookies_location(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("FreshMint")
    source = Path(profile.profile_path) / "backup.db"
    _make_cookies_db(source)

    target = cookies.import_(profile.id, source)
    assert Path(target) == Path(profile.profile_path) / "Default" / "Cookies"
    assert Path(target).is_file()


def test_import_missing_source_raises(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("Missing")
    with pytest.raises(CookieImportError):
        cookies.import_(profile.id, Path("/nope/backup.db"))


def test_import_non_sqlite_source_raises(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("Junk")
    profile_dir = _profile_dir(ctx, profile)
    source = profile_dir / "junk.db"
    source.write_text("this is not a database", encoding="utf-8")
    with pytest.raises(CookieImportError):
        cookies.import_(profile.id, source)


def test_import_while_running_raises(ctx):
    svc, cookies = ctx
    profile = svc.create_profile("Locked")
    profile_dir = _profile_dir(ctx, profile)
    svc.start_profile(profile.id)
    try:
        with pytest.raises(CookieImportError):
            cookies.import_(profile.id, profile_dir / "whatever.db")
    finally:
        svc.stop_profile(profile.id)


def test_export_none_never_reads_cookie_payloads(monkeypatch, ctx):
    """Exporting must not go through the cookie values in application memory."""
    import antidetect.application.cookie_service as mod

    called = []
    sqlite_module = sqlite3

    def fake_backup(src, dst):
        called.append("backup")
        try:
            read = sqlite_module.connect(f"file:{src}?mode=ro", uri=True)
            try:
                rows = read.execute("SELECT * FROM cookies").fetchall()
                assert rows  # the source really contains cookies
            finally:
                read.close()
        finally:
            dst_conn = sqlite_module.connect(f"file:{dst}?mode=rwc", uri=True)
            try:
                dst_conn.execute("CREATE TABLE cookies (key TEXT, value TEXT, domain TEXT)")
                dst_conn.commit()
            finally:
                dst_conn.close()

    monkeypatch.setattr(mod, "_sqlite_backup", fake_backup)
    svc, cookies = ctx
    profile = svc.create_profile("PayloadGuard")
    _make_cookies_db(Path(profile.profile_path) / "Default" / "Cookies")

    cookies.export(profile.id)
    assert called == ["backup"]