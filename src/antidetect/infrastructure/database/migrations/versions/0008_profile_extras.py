from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(profiles)")}


def upgrade(conn: sqlite3.Connection) -> None:
    """Profile notes, tags, auto-geo flag and start URL.

    ``geo_auto`` means "keep language / time zone / locale in line with the
    exit IP". Profiles that already existed were configured by hand, so they
    keep their geo untouched (``geo_auto = 0``); new profiles default to 1.
    """
    existing = _columns(conn)
    if "notes" not in existing:
        conn.execute("ALTER TABLE profiles ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
    if "tags" not in existing:
        conn.execute("ALTER TABLE profiles ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
    if "start_url" not in existing:
        conn.execute("ALTER TABLE profiles ADD COLUMN start_url TEXT")
    if "geo_auto" not in existing:
        conn.execute("ALTER TABLE profiles ADD COLUMN geo_auto INTEGER NOT NULL DEFAULT 1")
        conn.execute("UPDATE profiles SET geo_auto = 0")


def downgrade(conn: sqlite3.Connection) -> None:
    existing = _columns(conn)
    for column in ("geo_auto", "start_url", "tags", "notes"):
        if column in existing:
            conn.execute(f"ALTER TABLE profiles DROP COLUMN {column}")
