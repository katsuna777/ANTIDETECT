from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class _LockingCursor:
    """Proxy around a sqlite3 cursor that holds the owning Database's lock for
    every operation, so readers never race against a thread closing the
    connection."""

    def __init__(self, owner: "Database", cursor: sqlite3.Cursor) -> None:
        self._owner = owner
        self._cursor = cursor

    def fetchone(self):
        with self._owner._lock:
            return self._cursor.fetchone()

    def fetchmany(self, size: int = 1):
        with self._owner._lock:
            return self._cursor.fetchmany(size)

    def fetchall(self):
        with self._owner._lock:
            return self._cursor.fetchall()

    def __iter__(self) -> "_LockingCursor":
        return self

    def __next__(self):
        with self._owner._lock:
            row = self._cursor.fetchone()
        if row is None:
            raise StopIteration
        return row

    @property
    def rowcount(self) -> int:
        with self._owner._lock:
            return self._cursor.rowcount

    @property
    def lastrowid(self) -> int:
        with self._owner._lock:
            return self._cursor.lastrowid

    @property
    def description(self):
        with self._owner._lock:
            return self._cursor.description

    def close(self) -> None:
        with self._owner._lock:
            self._cursor.close()

    def copy(self) -> "_LockingCursor":
        with self._owner._lock:
            return _LockingCursor(self._owner, self._cursor.copy())


class Database:
    """Thin wrapper around a single SQLite connection.

    Owns connection pragmas and transaction handling. Each :class:`Database`
    instance owns exactly one connection, which keeps business writes atomic
    and is safe for the CLI's single-threaded use. To let a future GUI run
    service calls from worker threads off the UI event loop, the connection is
    opened with ``check_same_thread=False`` (the sqlite3 module serializes
    statements internally) and a reentrant lock makes each logical transaction
    atomic against accesses from other threads.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.RLock()

    def execute(self, sql: str, params: tuple = ()) -> _LockingCursor:
        with self._lock:
            return _LockingCursor(self, self._conn.execute(sql, params))

    def executemany(self, sql: str, seq_of_params: list[tuple]) -> None:
        with self._lock:
            self._conn.executemany(sql, seq_of_params)

    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)

    def commit(self) -> None:
        """Flush any pending changes when a transaction is open (no-op otherwise)."""
        with self._lock:
            self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager that commits on success, rolls back on error."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()