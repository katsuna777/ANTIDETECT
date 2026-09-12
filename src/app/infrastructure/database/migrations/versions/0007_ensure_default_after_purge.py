from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Re-seed the bare `default` configuration if the purge left none.

    Migration 0006 deletes every legacy (Chrome 120-127) fingerprint. On
    databases whose only rows were legacy, the table ends up empty and every
    profile creation fails with ``BrowserConfigurationNotFoundError(0)``.
    A bare default (all NULLs = no spoofing) is always safe to launch, so it
    is re-inserted when the table is empty — same invariant as 0004.
    """
    conn.execute(
        """
        INSERT INTO browser_configurations
            (name, user_agent, platform, language, locale, timezone,
             screen_width, screen_height, device_pixel_ratio, color_depth,
             webgl_settings, hardware_settings, client_hints,
             created_at, updated_at)
        SELECT 'default', NULL, NULL, NULL, NULL, NULL,
                NULL, NULL, NULL, NULL,
                NULL, NULL, NULL,
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE NOT EXISTS (
            SELECT 1 FROM browser_configurations
        )
        """
    )


def downgrade(conn: sqlite3.Connection) -> None:
    """Intentionally a no-op: removing the last configuration would break the
    very invariant this migration establishes."""
