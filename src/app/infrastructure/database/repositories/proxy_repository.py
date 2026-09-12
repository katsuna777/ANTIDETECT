from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Iterable

from app.domain.enums.proxy_status import Anonymity, ProxyProtocol, ProxyStatus
from app.domain.models.proxy import Proxy, ProxyWithCheck
from app.domain.models.proxy_entry import ProxyEntry
from app.infrastructure.database.datetime_utils import SQL_NOW, parse_dt, serialize_dt
from app.infrastructure.database.sequence_utils import reset_sequence

if TYPE_CHECKING:
    from app.infrastructure.database.connection import Database

_COLUMNS = (
    "id, protocol, host, port, username, password, country, country_code, source, "
    "status, consecutive_failures, created_at, updated_at, last_checked_at"
)


class _RowProxy:
    def __init__(self, row) -> None:
        self._row = row

    def to_proxy(self) -> Proxy:
        row = self._row
        return Proxy(
            id=row["id"],
            protocol=ProxyProtocol.from_string(row["protocol"]),
            host=row["host"],
            port=row["port"],
            username=row["username"],
            password=row["password"],
            country=row["country"],
            country_code=row["country_code"],
            source=row["source"],
            status=ProxyStatus.from_string(row["status"]),
            consecutive_failures=row["consecutive_failures"],
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
            last_checked_at=parse_dt(row["last_checked_at"]),
        )


class SqliteProxyRepository:
    def __init__(self, db: "Database") -> None:
        self._db = db

    # --------------------------------------------------------------- reads

    def keys(self) -> set[tuple[str, str, int]]:
        rows = self._db.execute("SELECT protocol, host, port FROM proxies").fetchall()
        return {(row["protocol"], row["host"], row["port"]) for row in rows}

    def get(self, proxy_id: int) -> Proxy | None:
        row = self._db.execute(
            f"SELECT {_COLUMNS} FROM proxies WHERE id = ?", (proxy_id,)
        ).fetchone()
        return _RowProxy(row).to_proxy() if row else None

    def list(self) -> list[Proxy]:
        rows = self._db.execute(f"SELECT {_COLUMNS} FROM proxies ORDER BY id").fetchall()
        return [_RowProxy(row).to_proxy() for row in rows]

    def list_for_check(self, stale_before: datetime | None = None) -> list[Proxy]:
        if stale_before is None:
            rows = self._db.execute(
                f"SELECT {_COLUMNS} FROM proxies ORDER BY id"
            ).fetchall()
        else:
            rows = self._db.execute(
                f"SELECT {_COLUMNS} FROM proxies "
                "WHERE status = 'UNKNOWN' OR status = 'DEAD' "
                "OR last_checked_at IS NULL OR last_checked_at < ? "
                "ORDER BY id",
                (serialize_dt(stale_before),),
            ).fetchall()
        return [_RowProxy(row).to_proxy() for row in rows]

    def list_with_latest_check(
        self,
        status: ProxyStatus | None = None,
        limit: int | None = None,
        proxy_ids: list[int] | None = None,
    ) -> list[ProxyWithCheck]:
        prefixed = ", ".join(f"p.{name}" for name in _COLUMNS.split(", "))
        sql = [
            f"SELECT {prefixed},",
            "c.checked_at AS check_checked_at, c.latency_ms, c.external_ip,",
            "c.country AS check_country, c.country_code AS check_country_code,",
            "c.anonymity, c.error AS check_error",
            "FROM proxies p",
            "LEFT JOIN proxy_checks c ON c.id = (",
            "    SELECT pc.id FROM proxy_checks pc",
            "    WHERE pc.proxy_id = p.id",
            "    ORDER BY pc.checked_at DESC, pc.id DESC LIMIT 1)",
        ]
        params: list = []
        filters: list[str] = []
        if status is not None:
            filters.append("p.status = ?")
            params.append(status.value)
        if proxy_ids is not None and proxy_ids:
            placeholders = ",".join("?" for _ in proxy_ids)
            filters.append(f"p.id IN ({placeholders})")
            params.extend(proxy_ids)
        if filters:
            sql.append("WHERE " + " AND ".join(filters))
        sql.append("ORDER BY p.id")
        if limit is not None:
            sql.append("LIMIT ?")
            params.append(limit)
        rows = self._db.execute(" ".join(sql), tuple(params)).fetchall()
        return [self._to_with_check(row) for row in rows]

    def _to_with_check(self, row) -> ProxyWithCheck:
        proxy = _RowProxy(row).to_proxy()
        return ProxyWithCheck(
            proxy=proxy,
            checked_at=parse_dt(row["check_checked_at"]),
            latency_ms=row["latency_ms"],
            external_ip=row["external_ip"],
            country=row["check_country"],
            country_code=row["check_country_code"],
            anonymity=Anonymity.from_string(row["anonymity"]),
            check_error=row["check_error"],
        )

    # -------------------------------------------------------------- writes

    def upsert_many(self, entries: Iterable[ProxyEntry]) -> int:
        """Insert new proxies, updating `source` on existing rows.

        Returns the number of newly created rows. Deduplication against rows
        already in the database is enforced by the UNIQUE(protocol, host, port)
        constraint, so callers may pass the whole collected batch.
        """
        rows = [
            (
                entry.protocol.value,
                entry.host,
                entry.port,
                entry.username,
                entry.password,
                entry.source,
            )
            for entry in entries
        ]
        if not rows:
            return 0
        with self._db.transaction() as conn:
            before = conn.execute("SELECT COUNT(*) AS c FROM proxies").fetchone()["c"]
            conn.executemany(
                f"""
                INSERT INTO proxies (protocol, host, port, username, password,
                                     source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, {SQL_NOW}, {SQL_NOW})
                ON CONFLICT (protocol, host, port) DO UPDATE SET
                    source = COALESCE(excluded.source, proxies.source),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                rows,
            )
            after = conn.execute("SELECT COUNT(*) AS c FROM proxies").fetchone()["c"]
        return int(after - before)

    def apply_outcomes(
        self, updates: list[tuple[int, ProxyStatus, int, datetime]]
    ) -> None:
        """Batch-update proxy status after a check round.

        ``updates`` is a list of ``(proxy_id, status, consecutive_failures, checked_at)``
        applied atomically in one transaction.
        """
        if not updates:
            return
        rows = [
            (status.value, failures, serialize_dt(checked_at), proxy_id)
            for proxy_id, status, failures, checked_at in updates
        ]
        with self._db.transaction() as conn:
            conn.executemany(
                """
                UPDATE proxies
                SET status = ?, consecutive_failures = ?, last_checked_at = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                rows,
            )

    def delete(self, proxy_id: int) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
            reset_sequence(conn, "proxies")
            return cursor.rowcount > 0

    def delete_many(self, proxy_ids: list[int]) -> int:
        """Delete a batch of proxies (their checks cascade) in one transaction.

        Returns the number of rows removed. The AUTOINCREMENT counter is
        re-aligned afterwards so the pool does not keep climbing forever. The
        id list is chunked to stay under SQLite's variable-number limit.
        """
        if not proxy_ids:
            return 0
        _CHUNK = 500
        removed = 0
        with self._db.transaction() as conn:
            for start in range(0, len(proxy_ids), _CHUNK):
                chunk = proxy_ids[start : start + _CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                cursor = conn.execute(
                    f"DELETE FROM proxies WHERE id IN ({placeholders})",
                    tuple(chunk),
                )
                removed += int(cursor.rowcount)
            reset_sequence(conn, "proxies")
            return removed

    def delete_all(self) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM proxies")
            reset_sequence(conn, "proxies")
            return int(cursor.rowcount)

    def delete_dead(self) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM proxies WHERE status = 'DEAD'")
            reset_sequence(conn, "proxies")
            return int(cursor.rowcount)