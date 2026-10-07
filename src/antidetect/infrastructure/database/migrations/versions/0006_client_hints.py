from __future__ import annotations

import sqlite3


_LEGACY_UA_PATTERNS = (
    "%Chrome/120.%",
    "%Chrome/121.%",
    "%Chrome/122.%",
    "%Chrome/123.%",
    "%Chrome/124.%",
    "%Chrome/125.%",
    "%Chrome/126.%",
)


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(browser_configurations)")}


def upgrade(conn: sqlite3.Connection) -> None:
    """Add client_hints JSON and purge legacy 120-126 fingerprints.

    Client Hints (Sec-CH-UA) must match the spoofed User-Agent or Google
    flags the profile as automation ("browser is not secure"). Configs
    generated with Chrome 120-126 while the real binary is 139+ are therefore
    deleted (except the NULL `default` row which performs no spoofing).
    """
    if "client_hints" not in _columns(conn):
        conn.execute("ALTER TABLE browser_configurations ADD COLUMN client_hints TEXT")
    for pattern in _LEGACY_UA_PATTERNS:
        conn.execute(
            "DELETE FROM browser_configurations WHERE user_agent LIKE ?",
            (pattern,),
        )


def downgrade(conn: sqlite3.Connection) -> None:
    if "client_hints" in _columns(conn):
        conn.execute("ALTER TABLE browser_configurations DROP COLUMN client_hints")
