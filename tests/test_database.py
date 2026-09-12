from __future__ import annotations

import sqlite3

import pytest

from app.infrastructure.database.connection import Database


def test_creates_parent_directories(tmp_path):
    nested = tmp_path / "a" / "b" / "db.sqlite"
    Database(nested)
    assert nested.parent.is_dir()


def test_row_factory_returns_row_objects(db: Database):
    row = db.execute("SELECT 1 AS answer").fetchone()
    assert row["answer"] == 1


def test_foreign_keys_are_enforced(db: Database):
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            db.execute(
                "INSERT INTO profiles (name, profile_path, configuration_id) "
                "VALUES ('orphan', '/x', 9999)"
            )


def test_wal_journal_mode_is_active(db: Database):
    row = db.execute("PRAGMA journal_mode").fetchone()
    assert row[0].lower() == "wal"


def test_transaction_rolls_back_on_error(db: Database):
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute(
                "INSERT INTO settings (key, value) VALUES ('tx', '1')"
            )
            raise RuntimeError("boom")

    assert db.execute("SELECT COUNT(*) AS c FROM settings WHERE key='tx'").fetchone()["c"] == 0


def test_transaction_commits_on_success(db: Database):
    with db.transaction():
        db.execute("INSERT INTO settings (key, value) VALUES ('ok', '1')")
    assert db.execute("SELECT value FROM settings WHERE key='ok'").fetchone()["value"] == "1"


def test_executemany_batch_inserts(db: Database):
    db.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        [("k1", "v1"), ("k2", "v2")],
    )
    db.commit()
    assert db.execute("SELECT COUNT(*) AS c FROM settings").fetchone()["c"] == 2


def test_close_is_idempotent(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.close()
    db.close()


def test_usable_from_worker_threads(tmp_path):
    """GUI scenario: services are called from QThread worker threads while the
    same Database instance is shared; must not raise ProgrammingError."""
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.database.migrations import run_migrations

    db = Database(tmp_path / "db.sqlite")
    run_migrations(db)

    def worker(n: int) -> None:
        with db.transaction():
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (f"k{n}", str(n)),
            )
        db.execute("SELECT value FROM settings WHERE key = ?", (f"k{n}",)).fetchone()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(8)))
    assert db.execute("SELECT COUNT(*) AS c FROM settings").fetchone()["c"] == 8
    db.close()


def test_multiple_profiles_share_no_state_between_db_files(tmp_path):
    first = Database(tmp_path / "first.db")
    second = Database(tmp_path / "second.db")
    from app.infrastructure.database.migrations import run_migrations

    run_migrations(first)
    run_migrations(second)

    from app.infrastructure.database.repositories.browser_configuration_repository import (
        SqliteBrowserConfigurationRepository,
    )

    SqliteBrowserConfigurationRepository(second).create("only-in-second")
    assert first.execute(
        "SELECT COUNT(*) AS c FROM browser_configurations WHERE name='only-in-second'"
    ).fetchone()["c"] == 0
    first.close()
    second.close()