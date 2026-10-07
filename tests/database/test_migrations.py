from __future__ import annotations

import importlib
import sqlite3

import pytest

from antidetect.infrastructure.database.connection import Database
from antidetect.infrastructure.database.migrations import discover, run_migrations


def test_discover_returns_ordered_migrations():
    migrations = discover()
    assert migrations
    versions = [m.version for m in migrations]
    assert versions == sorted(versions)
    assert versions[0] == 1


def test_migrations_apply_once_on_fresh_database(tmp_path):
    db = Database(tmp_path / "fresh.db")
    try:
        first = run_migrations(db)
        assert first, "expected at least one pending migration on a fresh database"
        second = run_migrations(db)
        assert second == []
    finally:
        db.close()


def test_migrations_are_idempotent(db):
    assert run_migrations(db) == []
    assert run_migrations(db) == []


def test_initial_schema_tables_exist(db):
    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"profiles", "browser_configurations", "settings", "schema_migrations"} <= tables


def test_proxy_tables_exist_and_enforce_constraints(db):
    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"proxies", "proxy_checks"} <= tables
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(proxies)").fetchall()
    }
    assert {
        "protocol", "host", "port", "username", "password", "country",
        "country_code", "source", "status", "consecutive_failures",
        "created_at", "updated_at", "last_checked_at",
    } <= columns

    from antidetect.domain.enums.proxy_status import ProxyProtocol

    db.executemany(
        """
        INSERT INTO proxies (protocol, host, port, created_at, updated_at)
        VALUES (?, ?, ?, 'now', 'now')
        """,
        [
            (ProxyProtocol.HTTP.value, "1.1.1.1", 8080),
            (ProxyProtocol.SOCKS5.value, "2.2.2.2", 1080),
        ],
    )
    db.commit()
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            db.execute(
                "INSERT INTO proxies (protocol, host, port, created_at, updated_at) "
                "VALUES ('HTTP', '1.1.1.1', 8080, 'now', 'now')"
            )


def test_default_browser_configuration_is_seeded(db):
    row = db.execute(
        "SELECT id, name FROM browser_configurations WHERE name='default'"
    ).fetchone()
    assert row is not None
    assert row["id"] == 1


def test_0003_widened_browser_configurations(db):
    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(browser_configurations)").fetchall()
    }
    assert {
        "platform", "locale", "screen_width", "screen_height",
        "device_pixel_ratio", "color_depth", "webgl_settings", "hardware_settings",
    } <= columns


def test_0003_profiles_gain_proxy_id_and_nullable_configuration(db):
    info = {
        row["name"]: row
        for row in db.execute("PRAGMA table_info(profiles)").fetchall()
    }
    assert "proxy_id" in info
    assert info["configuration_id"]["notnull"] == 0
    foreign_keys = {
        row["from"]: row["table"]
        for row in db.execute("PRAGMA foreign_key_list(profiles)").fetchall()
    }
    assert foreign_keys["configuration_id"] == "browser_configurations"
    assert foreign_keys["proxy_id"] == "proxies"


def test_profile_configuration_delete_sets_null(db):
    cursor = db.execute(
        "INSERT INTO profiles (name, profile_path, configuration_id, created_at, updated_at) "
        "VALUES ('P1', '/tmp/p1', 1, 'now', 'now')"
    )
    profile_id = cursor.lastrowid
    db.commit()
    db.execute("DELETE FROM browser_configurations WHERE id = 1")
    db.commit()
    row = db.execute(
        "SELECT configuration_id FROM profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    assert row["configuration_id"] is None


def test_profile_proxy_delete_sets_null(db):
    from antidetect.domain.enums.proxy_status import ProxyProtocol

    db.execute(
        "INSERT INTO proxies (protocol, host, port, created_at, updated_at) "
        "VALUES (?, ?, ?, 'now', 'now')",
        (ProxyProtocol.HTTP.value, "1.1.1.1", 8080),
    )
    db.commit()
    proxy_id = db.execute("SELECT id FROM proxies LIMIT 1").fetchone()["id"]
    cursor = db.execute(
        "INSERT INTO profiles (name, profile_path, configuration_id, proxy_id, created_at, updated_at) "
        "VALUES ('P2', '/tmp/p2', 1, ?, 'now', 'now')",
        (proxy_id,),
    )
    profile_id = cursor.lastrowid
    db.commit()
    db.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
    db.commit()
    row = db.execute(
        "SELECT proxy_id FROM profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    assert row["proxy_id"] is None


def test_0004_reseeds_default_configuration_when_table_empty(db):
    """A database left without any configuration (e.g. one created before the
    0001 default seed, or whose row was deleted) must gain a usable default so
    profile creation/launch no longer fails with configuration id=0."""
    db.execute("DELETE FROM browser_configurations")
    db.commit()
    assert db.execute(
        "SELECT COUNT(*) FROM browser_configurations"
    ).fetchone()[0] == 0

    module = importlib.import_module(
        "antidetect.infrastructure.database.migrations.versions.0004_ensure_default_configuration"
    )
    with db.transaction() as conn:
        module.upgrade(conn)

    row = db.execute(
        "SELECT name FROM browser_configurations"
    ).fetchone()
    assert row is not None
    assert row["name"] == "default"

    with db.transaction() as conn:
        module.upgrade(conn)
    assert db.execute(
        "SELECT COUNT(*) FROM browser_configurations"
    ).fetchone()[0] == 1


def test_0004_is_noop_when_configuration_exists(db):
    module = importlib.import_module(
        "antidetect.infrastructure.database.migrations.versions.0004_ensure_default_configuration"
    )
    with db.transaction() as conn:
        module.upgrade(conn)
    assert db.execute(
        "SELECT COUNT(*) FROM browser_configurations"
    ).fetchone()[0] == 1


def test_0005_creates_app_logs_table(db):
    tables = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "app_logs" in tables
    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(app_logs)").fetchall()
    }
    assert {"id", "ts", "level", "source", "message", "extra"} <= columns

    db.execute(
        "INSERT INTO app_logs (ts, level, source, message) VALUES ('now', 'INFO', 'app', 'hello')"
    )
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM app_logs").fetchone()[0] == 1

    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            db.execute(
                "INSERT INTO app_logs (ts, level, source, message) VALUES ('now', 'BOGUS', 'app', 'x')"
            )


def test_0007_reseeds_default_when_purge_emptied_table(db):
    """Regression: 0006 purging every legacy row must not leave creation
    broken with BrowserConfigurationNotFoundError(0)."""
    db.execute("DELETE FROM browser_configurations")
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM browser_configurations").fetchone()[0] == 0

    module = importlib.import_module(
        "antidetect.infrastructure.database.migrations.versions.0007_ensure_default_after_purge"
    )
    with db.transaction() as conn:
        module.upgrade(conn)
    row = db.execute(
        "SELECT id, name, user_agent FROM browser_configurations"
    ).fetchone()
    assert row is not None and row["name"] == "default" and row["user_agent"] is None

    with db.transaction() as conn:
        module.upgrade(conn)
    assert db.execute("SELECT COUNT(*) FROM browser_configurations").fetchone()[0] == 1


def test_0003_downgrade_restores_previous_schema(db):
    module = importlib.import_module(
        "antidetect.infrastructure.database.migrations.versions.0003_profiles_and_configurations"
    )
    with db.transaction() as conn:
        module.downgrade(conn)
    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(profiles)").fetchall()
    }
    assert "proxy_id" not in columns
    assert columns == {
        "id", "name", "profile_path", "configuration_id", "status",
        "created_at", "updated_at", "last_started_at", "last_stopped_at", "pid",
    }
    config_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(browser_configurations)").fetchall()
    }
    assert "webgl_settings" not in config_columns

def test_migration_0009_drops_unverified_free_proxies_but_keeps_the_rest(tmp_path):
    db = Database(tmp_path / "old.db")
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT '')"
    )
    for migration in discover():
        if migration.version >= 9:
            continue
        with db.transaction() as conn:
            importlib.import_module(migration.full_path).upgrade(conn)
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (migration.version, migration.name))
    rows = [
        ("free-unchecked", "UNKNOWN", "http-1"), ("free-dead", "DEAD", "http-1"), ("free-working", "WORKING", "http-1"),
        ("manual-unchecked", "UNKNOWN", "manual"), ("free-in-use", "UNKNOWN", "http-1"), ("no-source", "UNKNOWN", None),
    ]
    with db.transaction() as conn:
        for host, status, source in rows:
            conn.execute(
                "INSERT INTO proxies (protocol, host, port, status, source, created_at, updated_at) "
                "VALUES ('HTTP', ?, 80, ?, ?, 'n', 'n')", (host, status, source),
            )
        in_use = conn.execute("SELECT id FROM proxies WHERE host = 'free-in-use'").fetchone()["id"]
        conn.execute(
            "INSERT INTO profiles (name, profile_path, proxy_id, status, created_at, updated_at) "
            "VALUES ('p', '/x', ?, 'STOPPED', 'n', 'n')", (in_use,),
        )
    migration = next(m for m in discover() if m.version == 9)
    module = importlib.import_module(migration.full_path)
    with db.transaction() as conn:
        module.upgrade(conn)
        module.upgrade(conn)  # idempotent
    left = {r["host"] for r in db.execute("SELECT host FROM proxies")}
    assert left == {"free-working", "manual-unchecked", "free-in-use"}
    assert db.execute("SELECT proxy_id FROM profiles").fetchone()["proxy_id"] == in_use  # the assignment survived
    db.close()


def _database_before(tmp_path, version: int) -> Database:
    db = Database(tmp_path / "old.db")
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT '')"
    )
    for migration in discover():
        if migration.version >= version:
            continue
        with db.transaction() as conn:
            importlib.import_module(migration.full_path).upgrade(conn)
            conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (migration.version, migration.name))
    return db


def test_migration_0010_keeps_profiles_registers_their_tags_and_frees_deleted_names(tmp_path):
    db = _database_before(tmp_path, 10)
    with db.transaction() as conn:
        for name, tags in (("one", "Work, Dev"), ("two", "work"), ("three", "")):
            conn.execute(
                "INSERT INTO profiles (name, profile_path, status, created_at, updated_at, tags) "
                "VALUES (?, '/x', 'STOPPED', 'n', 'n', ?)", (name, tags),
            )
        conn.execute("INSERT INTO settings (key, value) VALUES ('gui.tag_colors', '{\"work\": 4, \"dev\": 2}')")
    migration = next(m for m in discover() if m.version == 10)
    module = importlib.import_module(migration.full_path)
    with db.transaction() as conn:
        module.upgrade(conn)

    assert [r["name"] for r in db.execute("SELECT name FROM profiles ORDER BY id")] == ["one", "two", "three"]
    tags = {r["name"]: r["color"] for r in db.execute("SELECT name, color FROM tags")}
    assert tags == {"Work": 4, "Dev": 2}                       # one registry row per tag, the colours the user saw
    cols = {r["name"] for r in db.execute("PRAGMA table_info(profiles)")}
    assert {"deleted_at", "workspace_id"} <= cols

    with pytest.raises(sqlite3.IntegrityError):               # a live name is still unique
        with db.transaction() as conn:
            conn.execute("INSERT INTO profiles (name, profile_path, status, created_at, updated_at) "
                         "VALUES ('one', '/y', 'STOPPED', 'n', 'n')")
    with db.transaction() as conn:                            # ...but a name in the trash is free
        conn.execute("UPDATE profiles SET deleted_at = 'now' WHERE name = 'one'")
        conn.execute("INSERT INTO profiles (name, profile_path, status, created_at, updated_at) "
                     "VALUES ('one', '/y', 'STOPPED', 'n', 'n')")
    assert db.execute("SELECT COUNT(*) FROM profiles WHERE name = 'one'").fetchone()[0] == 2
    db.close()


def test_migration_0010_downgrade_returns_the_old_table(tmp_path):
    db = _database_before(tmp_path, 11)
    with db.transaction() as conn:
        conn.execute("INSERT INTO profiles (name, profile_path, status, created_at, updated_at) "
                     "VALUES ('alive', '/x', 'STOPPED', 'n', 'n')")
        conn.execute("INSERT INTO profiles (name, profile_path, status, created_at, updated_at, deleted_at) "
                     "VALUES ('trashed', '/y', 'STOPPED', 'n', 'n', 'now')")
        importlib.import_module(next(m for m in discover() if m.version == 10).full_path).downgrade(conn)
    assert [r["name"] for r in db.execute("SELECT name FROM profiles")] == ["alive"]
    assert "deleted_at" not in {r["name"] for r in db.execute("PRAGMA table_info(profiles)")}
    assert not db.execute("SELECT name FROM sqlite_master WHERE name = 'tags'").fetchall()
    db.close()


def test_migration_0011_keeps_retina_macs_at_30_bit_colour_and_leaves_the_rest(tmp_path):
    db = _database_before(tmp_path, 11)
    rows = (("mac-retina", "macos", 2.0, 24), ("mac-external", "macos", 1.0, 24), ("mac-chosen", "macos", 2.0, 16),
            ("win", "windows", 2.0, 24), ("lin", "linux", 1.0, 24), ("bare", None, None, None))
    with db.transaction() as conn:
        for name, platform, dpr, depth in rows:
            conn.execute(
                "INSERT INTO browser_configurations (name, platform, device_pixel_ratio, color_depth, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'n', 'n')",
                (name, platform, dpr, depth),
            )
    migration = next(m for m in discover() if m.version == 11)
    module = importlib.import_module(migration.full_path)
    with db.transaction() as conn:
        module.upgrade(conn)

    depth = {r["name"]: r["color_depth"] for r in db.execute("SELECT name, color_depth FROM browser_configurations")}
    assert depth["mac-retina"] == 30                          # what pages have been seeing from a retina Mac
    assert depth["mac-external"] == 24 and depth["mac-chosen"] == 16
    assert depth["win"] == 24 and depth["lin"] == 24 and depth["bare"] is None

    with db.transaction() as conn:
        module.downgrade(conn)
    assert db.execute("SELECT color_depth FROM browser_configurations WHERE name = 'mac-retina'").fetchone()[0] == 24
    db.close()


def test_migration_0012_adds_privacy_settings_and_existing_profiles_keep_the_defaults(tmp_path):
    db = _database_before(tmp_path, 12)
    with db.transaction() as conn:
        conn.execute("INSERT INTO browser_configurations (name, platform, created_at, updated_at) VALUES ('old', 'windows', 'n', 'n')")
    migration = next(m for m in discover() if m.version == 12)
    module = importlib.import_module(migration.full_path)
    with db.transaction() as conn:
        module.upgrade(conn)
        module.upgrade(conn)                                  # running it twice changes nothing

    assert "privacy_settings" in {r["name"] for r in db.execute("PRAGMA table_info(browser_configurations)")}
    assert db.execute("SELECT privacy_settings FROM browser_configurations WHERE name = 'old'").fetchone()[0] is None

    with db.transaction() as conn:
        module.downgrade(conn)
    assert "privacy_settings" not in {r["name"] for r in db.execute("PRAGMA table_info(browser_configurations)")}
    db.close()



def test_migration_0013_keeps_every_existing_profile_on_the_systems_colour_scheme(tmp_path):
    db = _database_before(tmp_path, 13)
    with db.transaction() as conn:
        for name, raw in (("plain", None), ("chose", '{"webrtc": "block"}'), ("had-theme", '{"theme": "dark"}'), ("broken", "{oops")):
            conn.execute(
                "INSERT INTO browser_configurations (name, platform, privacy_settings, created_at, updated_at) "
                "VALUES (?, 'windows', ?, 'n', 'n')", (name, raw),
            )
    migration = next(m for m in discover() if m.version == 13)
    module = importlib.import_module(migration.full_path)
    with db.transaction() as conn:
        module.upgrade(conn)
        module.upgrade(conn)                                   # twice changes nothing

    import json

    stored = {r["name"]: json.loads(r["privacy_settings"]) for r in db.execute("SELECT name, privacy_settings FROM browser_configurations")}
    assert stored["plain"] == {"theme": "auto"}                # it showed the system's scheme: it still does
    assert stored["chose"] == {"webrtc": "block", "theme": "auto"}
    assert stored["had-theme"] == {"theme": "dark"}            # a choice already made is not overwritten
    assert stored["broken"] == {"theme": "auto"}

    with db.transaction() as conn:
        module.downgrade(conn)
    after = {r["name"]: r["privacy_settings"] for r in db.execute("SELECT name, privacy_settings FROM browser_configurations")}
    assert after["plain"] is None and json.loads(after["chose"]) == {"webrtc": "block"}
    db.close()
