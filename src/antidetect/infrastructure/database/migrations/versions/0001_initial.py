from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE browser_configurations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            user_agent TEXT,
            language   TEXT,
            timezone   TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        INSERT INTO browser_configurations (id, name, user_agent, language, timezone, created_at, updated_at)
        VALUES (1, 'default', NULL, NULL, NULL,
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

        CREATE TABLE profiles (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT NOT NULL UNIQUE,
            profile_path      TEXT NOT NULL,
            configuration_id  INTEGER NOT NULL REFERENCES browser_configurations(id),
            status            TEXT NOT NULL DEFAULT 'STOPPED',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            last_started_at   TEXT,
            last_stopped_at   TEXT,
            pid               INTEGER
        );

        CREATE INDEX idx_profiles_configuration_id ON profiles(configuration_id);

        CREATE TABLE settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS settings;
        DROP TABLE IF EXISTS profiles;
        DROP TABLE IF EXISTS browser_configurations;
        """
    )