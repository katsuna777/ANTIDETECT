from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Widen browser_configurations and link profiles to proxies.

    * ``browser_configurations`` gains the full fingerprint parameter set
      (platform / locale / screen geometry / DPR / color depth / JSON blobs).
    * ``profiles`` is rebuilt so ``proxy_id`` can reference a proxy and
      ``configuration_id`` becomes nullable (a profile may temporarily have no
      configuration assigned; the start flow validates it before launch).
    """
    for statement in (
        "ALTER TABLE browser_configurations ADD COLUMN platform TEXT",
        "ALTER TABLE browser_configurations ADD COLUMN locale TEXT",
        "ALTER TABLE browser_configurations ADD COLUMN screen_width INTEGER",
        "ALTER TABLE browser_configurations ADD COLUMN screen_height INTEGER",
        "ALTER TABLE browser_configurations ADD COLUMN device_pixel_ratio REAL",
        "ALTER TABLE browser_configurations ADD COLUMN color_depth INTEGER",
        "ALTER TABLE browser_configurations ADD COLUMN webgl_settings TEXT",
        "ALTER TABLE browser_configurations ADD COLUMN hardware_settings TEXT",
    ):
        conn.execute(statement)

    conn.executescript(
        """
        CREATE TABLE profiles_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT NOT NULL UNIQUE,
            profile_path      TEXT NOT NULL,
            configuration_id  INTEGER REFERENCES browser_configurations(id) ON DELETE SET NULL,
            proxy_id          INTEGER REFERENCES proxies(id) ON DELETE SET NULL,
            status            TEXT NOT NULL DEFAULT 'STOPPED',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            last_started_at   TEXT,
            last_stopped_at   TEXT,
            pid               INTEGER
        );

        INSERT INTO profiles_new
            (id, name, profile_path, configuration_id, proxy_id, status,
             created_at, updated_at, last_started_at, last_stopped_at, pid)
        SELECT id, name, profile_path, configuration_id, NULL, status,
               created_at, updated_at, last_started_at, last_stopped_at, pid
        FROM profiles;

        DROP TABLE profiles;
        ALTER TABLE profiles_new RENAME TO profiles;

        CREATE INDEX idx_profiles_configuration_id ON profiles(configuration_id);
        CREATE INDEX idx_profiles_proxy_id ON profiles(proxy_id);
        """
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE profiles_old (
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

        INSERT INTO profiles_old
            (id, name, profile_path, configuration_id, status,
             created_at, updated_at, last_started_at, last_stopped_at, pid)
        SELECT id, name, profile_path,
               COALESCE(configuration_id, 1), status,
               created_at, updated_at, last_started_at, last_stopped_at, pid
        FROM profiles;

        DROP TABLE profiles;
        ALTER TABLE profiles_old RENAME TO profiles;
        CREATE INDEX idx_profiles_configuration_id ON profiles(configuration_id);
        """
    )
    for statement in (
        "ALTER TABLE browser_configurations DROP COLUMN hardware_settings",
        "ALTER TABLE browser_configurations DROP COLUMN webgl_settings",
        "ALTER TABLE browser_configurations DROP COLUMN color_depth",
        "ALTER TABLE browser_configurations DROP COLUMN device_pixel_ratio",
        "ALTER TABLE browser_configurations DROP COLUMN screen_height",
        "ALTER TABLE browser_configurations DROP COLUMN screen_width",
        "ALTER TABLE browser_configurations DROP COLUMN locale",
        "ALTER TABLE browser_configurations DROP COLUMN platform",
    ):
        conn.execute(statement)