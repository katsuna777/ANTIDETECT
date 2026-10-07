from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE app_logs (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            level   TEXT NOT NULL DEFAULT 'INFO'
                    CHECK (level IN ('DEBUG', 'INFO', 'WARN', 'ERROR')),
            source  TEXT NOT NULL DEFAULT 'app',
            message TEXT NOT NULL,
            extra   TEXT
        );

        CREATE INDEX idx_app_logs_ts ON app_logs(ts);
        """
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS app_logs;
        """
    )