"""Product behaviour added around the engine: per-profile fingerprints, auto-geo,
manual proxies, notes/tags, and one-shot CLI conveniences."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from antidetect.application.fingerprint import data as fd
from antidetect.application.profile_service import DEDICATED_PREFIX
from antidetect.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from antidetect.domain.errors import ChromiumError, ProfileNotRunningError, ProxyNotUsableError
from antidetect.domain.models.proxy_check import ProxyCheck
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.database.repositories.proxy_check_repository import SqliteProxyCheckRepository
from antidetect.infrastructure.proxy.proxy_parser import parse_line
from tests.conftest import build_service


@pytest.fixture()
def ctx(config, fake_chromium):
    svc, db = build_service(config, fake_chromium)
    yield svc, db
    for profile in svc.list_profiles():
        if profile.status.value == "RUNNING":
            svc.stop_profile(profile.id)
    db.close()


# ---------------------------------------------------------------- proxy formats


@pytest.mark.parametrize(
    "line, expected",
    [
        ("1.2.3.4:8080", (ProxyProtocol.HTTP, "1.2.3.4", 8080, None, None)),
        ("1.2.3.4:8080:user:pa55", (ProxyProtocol.HTTP, "1.2.3.4", 8080, "user", "pa55")),
        ("user:pa55:1.2.3.4:8080", (ProxyProtocol.HTTP, "1.2.3.4", 8080, "user", "pa55")),
        ("1.2.3.4:8080@user:pa55", (ProxyProtocol.HTTP, "1.2.3.4", 8080, "user", "pa55")),
        ("user:pa55@1.2.3.4:8080", (ProxyProtocol.HTTP, "1.2.3.4", 8080, "user", "pa55")),
        ("socks5://1.2.3.4:1080:user:pa55", (ProxyProtocol.SOCKS5, "1.2.3.4", 1080, "user", "pa55")),
        ("http://u:p@proxy.example.com:3128", (ProxyProtocol.HTTP, "proxy.example.com", 3128, "u", "p")),
        ("proxy.example.com:3128:me:secret", (ProxyProtocol.HTTP, "proxy.example.com", 3128, "me", "secret")),
    ],
)
def test_seller_style_proxy_layouts_are_understood(line, expected):
    entry = parse_line(line)
    assert (entry.protocol, entry.host, entry.port, entry.username, entry.password) == expected


@pytest.mark.parametrize("line", ["", "# comment", "nonsense", "1.2.3.4", "1.2.3.4:99999", "a:b:c", "1.2.3.4:80:u"])
def test_unreadable_proxy_lines_are_rejected(line):
    assert parse_line(line) is None


# ------------------------------------------------------------- manual proxies


def test_import_text_adds_dedupes_and_reports(ctx):
    svc, db = ctx
    from antidetect.infrastructure.database.repositories.proxy_repository import SqliteProxyRepository

    from antidetect.application.proxy_service import ProxyService

    proxies = ProxyService(
        proxies=SqliteProxyRepository(db), checks=SqliteProxyCheckRepository(db),
        collector=None, checker=None,
    )
    first = proxies.import_text("1.1.1.1:80\n2.2.2.2:80:u:p\nbad line\n# note", ProxyProtocol.SOCKS5)
    assert (first.added, first.existing, len(first.ids), first.invalid) == (2, 0, 2, ["bad line"])
    again = proxies.import_text("1.1.1.1:80", ProxyProtocol.SOCKS5)
    assert (again.added, again.existing) == (0, 1)
    rows = SqliteProxyRepository(db).list()
    assert all(p.source == "manual" and p.protocol is ProxyProtocol.SOCKS5 for p in rows)


def test_reimporting_updates_credentials_and_keeps_manual_ownership(ctx):
    svc, db = ctx
    from antidetect.application.proxy_service import ProxyService
    from antidetect.infrastructure.database.repositories.proxy_repository import SqliteProxyRepository

    repo = SqliteProxyRepository(db)
    repo.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host="3.3.3.3", port=80, source="free-list")])
    proxies = ProxyService(proxies=repo, checks=SqliteProxyCheckRepository(db), collector=None, checker=None)
    proxies.import_text("3.3.3.3:80:me:pw", ProxyProtocol.HTTP)
    (row,) = repo.list()
    assert (row.source, row.username, row.password) == ("manual", "me", "pw")
    repo.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host="3.3.3.3", port=80, source="free-list")])
    assert repo.list()[0].source == "manual"  # a later pool refresh never demotes it


def test_manual_proxy_is_not_blocked_when_the_pool_check_called_it_dead(ctx):
    svc, db = ctx
    from antidetect.infrastructure.database.repositories.proxy_repository import SqliteProxyRepository

    repo = SqliteProxyRepository(db)
    repo.upsert_many([
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="4.4.4.4", port=80, source="manual"),
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="5.5.5.5", port=80, source="free-list"),
    ])
    for proxy in repo.list():
        repo.apply_outcomes([(proxy.id, ProxyStatus.DEAD, 9, datetime.now(timezone.utc))])
    manual, free = repo.list()
    ok = svc.create_profile("Mine", proxy_id=manual.id, auto_config=False)
    assert svc.start_profile(ok.id).status.value == "RUNNING"  # launch-time probe is the real gate
    svc.stop_profile(ok.id)
    blocked = svc.create_profile("Pool", proxy_id=free.id, auto_config=False)
    with pytest.raises(ProxyNotUsableError):
        svc.start_profile(blocked.id)
    assert repo.delete_dead() == 1 and [p.host for p in repo.list()] == ["4.4.4.4"]


# ---------------------------------------------------------------- fingerprints


def test_new_profiles_get_distinct_dedicated_fingerprints_for_the_host_os(ctx):
    svc, _ = ctx
    a, b = svc.create_profile("A"), svc.create_profile("B")
    ca, cb = (svc._configurations.get(p.configuration_id) for p in (a, b))
    assert ca.id != cb.id and ca.name.startswith(DEDICATED_PREFIX) and cb.name.startswith(DEDICATED_PREFIX)
    assert ca.platform == cb.platform == fd.host_platform()
    # (the pools are finite, so two draws may coincide in values — separate records is the contract)


def test_explicit_platform_is_honoured_and_validated(ctx):
    svc, _ = ctx
    for platform in fd.PLATFORMS:
        profile = svc.create_profile(f"p-{platform}", platform=platform)
        assert svc._configurations.get(profile.configuration_id).platform == platform
    with pytest.raises(ValueError):
        svc.create_profile("bad", platform="beos")


def test_deleting_a_profile_removes_its_dedicated_fingerprint_but_not_a_preset(ctx):
    svc, _ = ctx
    own = svc.create_profile("Own")
    preset = svc._configurations.get_default()
    shared = svc.create_profile("Shared", configuration_id=preset.id)
    own_cfg = own.configuration_id
    svc.delete_profile(own.id)
    assert svc._configurations.get(own_cfg) is None
    svc.delete_profile(shared.id)
    assert svc._configurations.get(preset.id) is not None


def test_regenerate_keeps_geo_and_can_switch_system(ctx):
    svc, _ = ctx
    profile = svc.create_profile("Regen", platform="windows")
    before = svc._configurations.get(profile.configuration_id)
    after = svc.regenerate_configuration(profile.id, "macos")
    assert after.id == before.id and after.platform == "macos" and "Macintosh" in after.user_agent
    assert (after.timezone, after.locale) == (before.timezone, before.locale)


def test_start_without_a_fingerprint_repairs_itself(ctx):
    svc, _ = ctx
    profile = svc.create_profile("Heal")
    svc.remove_configuration(profile.id)
    started = svc.start_profile(profile.id)
    assert started.configuration_id is not None
    assert svc._configurations.get(started.configuration_id).name.startswith(DEDICATED_PREFIX)


# ------------------------------------------------------------------- auto geo


def test_auto_geo_follows_the_machines_own_country_without_a_proxy(config, fake_chromium):
    calls = []
    svc, db = build_service(config, fake_chromium, geo_lookup=lambda: calls.append(1) or "DE")
    try:
        profile = svc.create_profile("Local", geo_auto=True)
        started = svc.start_profile(profile.id)
        cfg = svc._configurations.get(started.configuration_id)
        assert (cfg.locale, cfg.timezone, cfg.language) == ("de-DE", "Europe/Berlin", "de")
        svc.stop_profile(profile.id)
        svc.start_profile(profile.id)
        svc.stop_profile(profile.id)
        assert len(calls) == 1  # looked up once, then cached
    finally:
        db.close()


def test_geo_auto_off_leaves_the_fingerprint_alone(config, fake_chromium):
    svc, db = build_service(config, fake_chromium, geo_lookup=lambda: "JP")
    try:
        profile = svc.create_profile("Manual", geo_auto=False)
        before = svc._configurations.get(profile.configuration_id)
        started = svc.start_profile(profile.id)
        after = svc._configurations.get(started.configuration_id)
        assert (after.timezone, after.locale) == (before.timezone, before.locale)
        svc.stop_profile(profile.id)
    finally:
        db.close()


def test_a_failing_geo_lookup_never_blocks_launch(config, fake_chromium):
    def boom():
        raise OSError("offline")

    svc, db = build_service(config, fake_chromium, geo_lookup=boom)
    try:
        profile = svc.create_profile("Offline", geo_auto=True)
        assert svc.start_profile(profile.id).status.value == "RUNNING"
        svc.stop_profile(profile.id)
    finally:
        db.close()


def test_proxy_country_wins_over_the_machines_own(config, fake_chromium):
    svc, db = build_service(config, fake_chromium, geo_lookup=lambda: "JP")
    try:
        svc._proxies.upsert_many([ProxyEntry(protocol=ProxyProtocol.HTTP, host="8.8.4.4", port=80, source="manual")])
        proxy = svc._proxies.list()[0]
        SqliteProxyCheckRepository(db).insert_many([ProxyCheck(
            id=0, proxy_id=proxy.id, checked_at=datetime.now(timezone.utc), status=ProxyStatus.WORKING,
            latency_ms=40, external_ip="8.8.4.4", country="France", country_code="FR", anonymity=None,
        )])
        profile = svc.create_profile("Proxied", proxy_id=proxy.id)
        started = svc.start_profile(profile.id)
        assert svc._configurations.get(started.configuration_id).timezone == "Europe/Paris"
        svc.stop_profile(profile.id)
    finally:
        db.close()


# --------------------------------------------------------------- profile extras


def test_notes_tags_start_url_roundtrip_and_normalisation(ctx):
    svc, _ = ctx
    profile = svc.create_profile("Meta", notes="hello", tags=["Work", "work", " eu ", ",bad,"], start_url=" https://x.test ")
    assert profile.notes == "hello" and profile.start_url == "https://x.test"
    assert profile.tags == ["Work", "eu", "bad"]  # trimmed, comma-free, case-insensitively unique
    updated = svc.update_profile(profile.id, notes="", tags=[], start_url="", auto_config=False)
    assert (updated.notes, updated.tags, updated.start_url) == ("", [], None)


def test_last_started_survives_a_stop(ctx):
    svc, _ = ctx
    profile = svc.create_profile("Clock")
    svc.start_profile(profile.id)
    started_at = svc.get_profile(profile.id).last_started_at
    assert started_at is not None
    svc.stop_profile(profile.id)
    stopped = svc.get_profile(profile.id)
    assert stopped.last_started_at == started_at and stopped.last_stopped_at is not None


def test_duplicate_copies_extras_and_gets_its_own_seed(ctx, tmp_path):
    svc, _ = ctx
    original = svc.create_profile("Orig", notes="n", tags=["t"], geo_auto=False, start_url="https://s.test")
    seed = Path(original.profile_path) / ".antidetect-seed"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("12345")
    copy = svc.duplicate_profile(original.id)
    assert (copy.notes, copy.tags, copy.geo_auto, copy.start_url) == ("n", ["t"], False, "https://s.test")
    assert not (Path(copy.profile_path) / ".antidetect-seed").exists()  # noise seed is never shared


def test_open_url_requires_a_running_profile(ctx):
    svc, _ = ctx
    profile = svc.create_profile("Idle")
    with pytest.raises(ProfileNotRunningError):
        svc.open_url(profile.id, "https://example.com/")
    svc.start_profile(profile.id)
    with pytest.raises(ChromiumError):  # the stub browser has no stealth layer to open tabs
        svc.open_url(profile.id, "https://example.com/")


def test_is_protected_is_false_without_a_stealth_layer(ctx):
    svc, _ = ctx
    profile = svc.create_profile("Plain")
    svc.start_profile(profile.id)
    assert svc.is_protected(profile.id) is False


# -------------------------------------------------------------------- migration


def test_migration_0008_adds_columns_and_keeps_existing_profiles_manual(tmp_path):
    from antidetect.infrastructure.database.connection import Database
    from antidetect.infrastructure.database.migrations import discover

    db = Database(tmp_path / "old.db")
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT '')")
    import importlib

    for migration in discover():
        if migration.version >= 8:
            continue
        module = importlib.import_module(migration.full_path)
        with db.transaction() as conn:
            module.upgrade(conn)
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (migration.version, migration.name))
    db.execute("INSERT INTO profiles (name, profile_path, status, created_at, updated_at) VALUES ('legacy', '/x', 'STOPPED', 'n', 'n')")
    db.commit()
    module = importlib.import_module("antidetect.infrastructure.database.migrations.versions.0008_profile_extras")
    with db.transaction() as conn:
        module.upgrade(conn)
        module.upgrade(conn)  # idempotent
    row = db.execute("SELECT notes, tags, start_url, geo_auto FROM profiles").fetchone()
    assert (row["notes"], row["tags"], row["start_url"], row["geo_auto"]) == ("", "", None, 0)
    with db.transaction() as conn:
        conn.execute("INSERT INTO profiles (name, profile_path, status, created_at, updated_at) VALUES ('new', '/y', 'STOPPED', 'n', 'n')")
    assert db.execute("SELECT geo_auto FROM profiles WHERE name = 'new'").fetchone()["geo_auto"] == 1
    db.close()


# -------------------------------------------------------------------------- CLI


def _cli(tmp_path, fake, monkeypatch, *argv):
    from antidetect.cli.main import main

    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(fake))
    return main(list(argv))


def test_cli_create_with_platform_tags_notes_and_proxy_add(tmp_path, fake_chromium, monkeypatch, capsys):
    run = lambda *a: _cli(tmp_path, fake_chromium, monkeypatch, *a)  # noqa: E731
    assert run("proxy", "add", "9.9.9.9:80:user:pw", "garbage", "--type", "socks5") == 0
    out = capsys.readouterr().out
    assert "Added 1 new" in out and "skipped: garbage" in out
    assert run("profile", "create", "Cli", "--platform", "linux", "--tags", "a,b", "--notes", "hi", "--proxy-id", "1") == 0
    capsys.readouterr()
    assert run("profile", "show", "1") == 0
    shown = capsys.readouterr().out
    assert "Cli" in shown
    assert run("config", "list") == 0
    assert "fp-Cli" in capsys.readouterr().out


def test_cli_start_returns_immediately_when_unprotected(tmp_path, fake_chromium, monkeypatch, capsys):
    run = lambda *a: _cli(tmp_path, fake_chromium, monkeypatch, *a)  # noqa: E731
    assert run("profile", "create", "Quick") == 0
    assert run("profile", "start", "1") == 0  # stub browser: no stealth layer, so no waiting
    assert run("profile", "start", "1", "--detach") in (0, 1)  # already running: reported, not hung
    assert run("profile", "stop", "1") == 0
