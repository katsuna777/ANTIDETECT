from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE proxies (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            protocol             TEXT NOT NULL
                                 CHECK (protocol IN ('HTTP', 'HTTPS', 'SOCKS5')),
            host                 TEXT NOT NULL,
            port                 INTEGER NOT NULL
                                 CHECK (port BETWEEN 1 AND 65535),
            username             TEXT,
            password             TEXT,
            country              TEXT,
            country_code         TEXT,
            source               TEXT,
            status               TEXT NOT NULL DEFAULT 'UNKNOWN'
                                 CHECK (status IN ('UNKNOWN', 'CHECKING', 'WORKING', 'DEAD', 'ERROR')),
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            last_checked_at      TEXT,
            UNIQUE (protocol, host, port)
        );

        CREATE INDEX idx_proxies_status ON proxies(status);
        CREATE INDEX idx_proxies_protocol ON proxies(protocol);

        CREATE TABLE proxy_checks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            proxy_id     INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE,
            checked_at   TEXT NOT NULL,
            status       TEXT NOT NULL
                         CHECK (status IN ('WORKING', 'ERROR', 'DEAD')),
            latency_ms   INTEGER,
            external_ip  TEXT,
            country      TEXT,
            country_code TEXT,
            anonymity    TEXT,
            error        TEXT
        );

        CREATE INDEX idx_proxy_checks_proxy_id_time ON proxy_checks(proxy_id, checked_at);
        """
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS proxy_checks;
        DROP TABLE IF EXISTS proxies;
        """
    )