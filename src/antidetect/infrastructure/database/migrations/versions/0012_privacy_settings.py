from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(browser_configurations)")}


def upgrade(conn: sqlite3.Connection) -> None:
    """Per-profile protection switches (WebRTC mode, canvas / audio noise) as one JSON blob.

    NULL means "the defaults" (WebRTC follows the proxy, both noises on), so every profile that
    exists keeps behaving exactly as before.
    """
    if "privacy_settings" not in _columns(conn):
        conn.execute("ALTER TABLE browser_configurations ADD COLUMN privacy_settings TEXT")


def downgrade(conn: sqlite3.Connection) -> None:
    if "privacy_settings" in _columns(conn):
        conn.execute("ALTER TABLE browser_configurations DROP COLUMN privacy_settings")
