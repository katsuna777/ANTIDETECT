from __future__ import annotations

import sqlite3

from antidetect.infrastructure.database.sequence_utils import reset_sequence


def upgrade(conn: sqlite3.Connection) -> None:
    """Remove the free-list proxies that were stored without being verified.

    A free-list refresh used to write every collected address (tens of thousands) into the
    table before checking any of them, so a stopped run left the rest behind as ``UNKNOWN``.
    Collected proxies are now written only after they pass a check. This clears the old
    leftovers: anything that is not ``WORKING``, was not typed in by the user and is not used
    by a profile. (Failed ones go too: a collected proxy that did not pass has no value.)
    """
    conn.execute(
        """
        DELETE FROM proxies
        WHERE status != 'WORKING'
          AND COALESCE(source, '') != 'manual'
          AND id NOT IN (SELECT proxy_id FROM profiles WHERE proxy_id IS NOT NULL)
        """
    )
    reset_sequence(conn, "proxies")


def downgrade(conn: sqlite3.Connection) -> None:
    """Nothing to restore: the deleted rows were unverified leftovers."""
