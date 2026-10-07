from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database

# Modules are resolved relative to this package:
#   antidetect.infrastructure.database.migrations.versions.<filename>
MIGRATIONS = [
    "0001_initial",
    "0002_proxies",
    "0003_profiles_and_configurations",
    "0004_ensure_default_configuration",
    "0005_app_logs",
    "0006_client_hints",
    "0007_ensure_default_after_purge",
    "0008_profile_extras",
    "0009_drop_unchecked_proxies",
    "0010_trash_workspaces_tags",
    "0011_mac_color_depth",
    "0012_privacy_settings",
    "0013_theme_follows_system",
]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    filename: str

    @property
    def full_path(self) -> str:
        return f"{__package__}.versions.{self.filename}"


def discover() -> list[Migration]:
    """Build an ordered migration list from the registry above.

    Order is explicit on purpose: SQLite schema upgrades must never be
    sorted implicitly, so changes arrive in exactly the sequence we ship.
    """
    discovered: list[Migration] = []
    for filename in MIGRATIONS:
        parts = filename.split("_", 1)
        version = int(parts[0])
        name = parts[1] if len(parts) > 1 else ""
        discovered.append(Migration(version=version, name=name, filename=filename))
    discovered.sort(key=lambda m: m.version)
    return discovered


def run_migrations(db: "Database") -> list[Migration]:
    """Apply all pending migrations idempotently; returns the applied ones."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    db.commit()

    applied = {row["version"] for row in db.execute("SELECT version FROM schema_migrations")}
    ran: list[Migration] = []
    for migration in discover():
        if migration.version in applied:
            continue
        module = importlib.import_module(migration.full_path)
        with db.transaction() as conn:
            module.upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
        ran.append(migration)
    return ran