from __future__ import annotations

import sqlite3

TABLE_NAMES = {
    "profiles",
    "browser_configurations",
    "proxies",
    "proxy_checks",
}


def reset_sequence(conn: sqlite3.Connection, table: str) -> None:
    """Re-align an AUTOINCREMENT counter with the rows that actually exist.

    ``INTEGER PRIMARY KEY AUTOINCREMENT`` keeps a permanent counter in
    ``sqlite_sequence``, so deleting rows never lowers the next allocated id.
    After any delete we shrink the counter back to the current maximum (or to
    zero when the table is empty) inside the same transaction: after clearing
    a whole list, the next row created starts again from id 1.
    """
    if table not in TABLE_NAMES:
        raise ValueError(f"Unsafe sequence reset for table: {table!r}")
    conn.execute(
        f"UPDATE sqlite_sequence "
        f"SET seq = COALESCE((SELECT MAX(id) FROM {table}), 0) "
        f"WHERE name = ?",
        (table,),
    )