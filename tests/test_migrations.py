from __future__ import annotations

import importlib
import sqlite3

import pytest

from app.infrastructure.database.connection import Database
from app.infrastructure.database.migrations import discover, run_migrations


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

    from app.domain.enums.proxy_status import ProxyProtocol

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
    from app.domain.enums.proxy_status import ProxyProtocol

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
        "app.infrastructure.database.migrations.versions.0004_ensure_default_configuration"
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
        "app.infrastructure.database.migrations.versions.0004_ensure_default_configuration"
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
        "app.infrastructure.database.migrations.versions.0007_ensure_default_after_purge"
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
        "app.infrastructure.database.migrations.versions.0003_profiles_and_configurations"
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