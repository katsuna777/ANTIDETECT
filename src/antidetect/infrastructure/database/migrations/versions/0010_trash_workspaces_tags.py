from __future__ import annotations

import json
import sqlite3

from antidetect.application.palette import SLOTS, least_used

_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _remembered_colors(conn: sqlite3.Connection) -> dict[str, int]:
    """The colours the GUI used to keep in its preferences (``{tag: slot}``)."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'gui.tag_colors'").fetchone()
    try:
        data = json.loads(row[0]) if row and row[0] else {}
    except ValueError:
        return {}
    return {str(k).casefold(): int(v) for k, v in data.items() if isinstance(v, int) and 0 <= v < SLOTS}


def upgrade(conn: sqlite3.Connection) -> None:
    """Trash, workspaces, a tag registry and a persistent activity feed.

    * ``profiles`` is rebuilt: ``deleted_at`` (NULL = alive, otherwise the moment it went to the trash)
      and ``workspace_id`` are new, and the table-wide ``UNIQUE(name)`` becomes a unique index over the
      profiles that are not in the trash, so a deleted name can be used again.
    * ``tags`` is the registry (name + colour slot); a profile still stores its tag names in
      ``profiles.tags``, so scripts and the CLI keep working. Every tag already in use is registered.
    * ``activity`` is what the Activity page shows; unlike ``app_logs`` it survives restarts.
    """
    conn.executescript(
        f"""
        CREATE TABLE workspaces (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            key        TEXT NOT NULL UNIQUE,
            color      INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT ({_NOW})
        );

        CREATE TABLE tags (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            key        TEXT NOT NULL UNIQUE,
            color      INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT ({_NOW})
        );

        CREATE TABLE activity (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            kind    TEXT NOT NULL,
            level   TEXT NOT NULL DEFAULT 'INFO',
            subject TEXT NOT NULL DEFAULT '',
            data    TEXT
        );
        CREATE INDEX idx_activity_kind ON activity(kind, id);

        CREATE TABLE profiles_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT NOT NULL,
            profile_path      TEXT NOT NULL,
            configuration_id  INTEGER REFERENCES browser_configurations(id) ON DELETE SET NULL,
            proxy_id          INTEGER REFERENCES proxies(id) ON DELETE SET NULL,
            status            TEXT NOT NULL DEFAULT 'STOPPED',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            last_started_at   TEXT,
            last_stopped_at   TEXT,
            pid               INTEGER,
            notes             TEXT NOT NULL DEFAULT '',
            tags              TEXT NOT NULL DEFAULT '',
            start_url         TEXT,
            geo_auto          INTEGER NOT NULL DEFAULT 1,
            workspace_id      INTEGER REFERENCES workspaces(id) ON DELETE SET NULL,
            deleted_at        TEXT
        );

        INSERT INTO profiles_new
            (id, name, profile_path, configuration_id, proxy_id, status, created_at, updated_at,
             last_started_at, last_stopped_at, pid, notes, tags, start_url, geo_auto)
        SELECT id, name, profile_path, configuration_id, proxy_id, status, created_at, updated_at,
               last_started_at, last_stopped_at, pid, notes, tags, start_url, geo_auto
        FROM profiles;

        DROP TABLE profiles;
        ALTER TABLE profiles_new RENAME TO profiles;

        CREATE INDEX idx_profiles_configuration_id ON profiles(configuration_id);
        CREATE INDEX idx_profiles_proxy_id ON profiles(proxy_id);
        CREATE INDEX idx_profiles_workspace_id ON profiles(workspace_id);
        CREATE UNIQUE INDEX idx_profiles_name_alive ON profiles(name) WHERE deleted_at IS NULL;
        CREATE INDEX idx_profiles_deleted_at ON profiles(deleted_at) WHERE deleted_at IS NOT NULL;
        """
    )

    # Register the tags that profiles already carry, keeping the colours the user has seen so far.
    remembered = _remembered_colors(conn)
    seen: dict[str, str] = {}
    for (raw,) in conn.execute("SELECT tags FROM profiles WHERE tags != ''").fetchall():
        for part in (raw or "").split(","):
            name = part.strip()
            if name and name.casefold() not in seen:
                seen[name.casefold()] = name
    taken = [remembered[key] for key in seen if key in remembered]
    for key, name in sorted(seen.items()):
        slot = remembered.get(key)
        if slot is None:
            slot = least_used(taken)
            taken.append(slot)
        conn.execute("INSERT INTO tags (name, key, color) VALUES (?, ?, ?)", (name, key, slot))


def downgrade(conn: sqlite3.Connection) -> None:
    """Hand the table back as it was: profiles in the trash are dropped, the new tables go."""
    conn.executescript(
        """
        CREATE TABLE profiles_old (
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
            pid               INTEGER,
            notes             TEXT NOT NULL DEFAULT '',
            tags              TEXT NOT NULL DEFAULT '',
            start_url         TEXT,
            geo_auto          INTEGER NOT NULL DEFAULT 1
        );
        INSERT INTO profiles_old
            (id, name, profile_path, configuration_id, proxy_id, status, created_at, updated_at,
             last_started_at, last_stopped_at, pid, notes, tags, start_url, geo_auto)
        SELECT id, name, profile_path, configuration_id, proxy_id, status, created_at, updated_at,
               last_started_at, last_stopped_at, pid, notes, tags, start_url, geo_auto
        FROM profiles WHERE deleted_at IS NULL;
        DROP TABLE profiles;
        ALTER TABLE profiles_old RENAME TO profiles;
        CREATE INDEX idx_profiles_configuration_id ON profiles(configuration_id);
        CREATE INDEX idx_profiles_proxy_id ON profiles(proxy_id);
        DROP TABLE IF EXISTS activity;
        DROP TABLE IF EXISTS tags;
        DROP TABLE IF EXISTS workspaces;
        """
    )
