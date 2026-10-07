from __future__ import annotations

import json
import sqlite3


def _load(raw: str | None) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def upgrade(conn: sqlite3.Connection) -> None:
    """Profiles now have a colour-scheme setting that defaults to "light", independent of the system.

    Every profile that exists was running with the system's scheme, and the sites it logged in to have
    seen that: it keeps it ("auto") instead of changing under its owner. Only new profiles start light.
    """
    for row in conn.execute("SELECT id, privacy_settings FROM browser_configurations").fetchall():
        settings = _load(row[1])
        settings.setdefault("theme", "auto")
        conn.execute(
            "UPDATE browser_configurations SET privacy_settings = ? WHERE id = ?",
            (json.dumps(settings, ensure_ascii=False, sort_keys=True), row[0]),
        )


def downgrade(conn: sqlite3.Connection) -> None:
    for row in conn.execute("SELECT id, privacy_settings FROM browser_configurations").fetchall():
        settings = _load(row[1])
        if settings.pop("theme", None) is None:
            continue
        conn.execute(
            "UPDATE browser_configurations SET privacy_settings = ? WHERE id = ?",
            (json.dumps(settings, ensure_ascii=False, sort_keys=True) if settings else None, row[0]),
        )
