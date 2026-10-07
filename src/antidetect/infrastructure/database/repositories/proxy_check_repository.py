from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from antidetect.domain.enums.proxy_status import Anonymity, ProxyStatus
from antidetect.domain.models.proxy_check import ProxyCheck
from antidetect.infrastructure.database.datetime_utils import parse_dt, serialize_dt

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database


def _anonymity_value(anonymity: Anonymity | str | None) -> str | None:
    if anonymity is None:
        return None
    return anonymity.value if isinstance(anonymity, Anonymity) else str(anonymity)


class SqliteProxyCheckRepository:
    def __init__(self, db: "Database") -> None:
        self._db = db

    def insert_many(self, checks: Iterable[ProxyCheck]) -> None:
        rows = [
            (
                check.proxy_id,
                serialize_dt(check.checked_at),
                check.status.value,
                check.latency_ms,
                check.external_ip,
                check.country,
                check.country_code,
                _anonymity_value(check.anonymity),
                check.error,
            )
            for check in checks
        ]
        if not rows:
            return
        with self._db.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO proxy_checks (proxy_id, checked_at, status, latency_ms,
                                          external_ip, country, country_code,
                                          anonymity, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def latest_for(self, proxy_id: int) -> ProxyCheck | None:
        row = self._db.execute(
            "SELECT * FROM proxy_checks WHERE proxy_id = ? "
            "ORDER BY checked_at DESC, id DESC LIMIT 1",
            (proxy_id,),
        ).fetchone()
        if not row:
            return None
        return ProxyCheck(
            id=row["id"],
            proxy_id=row["proxy_id"],
            checked_at=parse_dt(row["checked_at"]),
            status=ProxyStatus.from_string(row["status"]),
            latency_ms=row["latency_ms"],
            external_ip=row["external_ip"],
            country=row["country"],
            country_code=row["country_code"],
            anonymity=Anonymity.from_string(row["anonymity"]),
            error=row["error"],
        )