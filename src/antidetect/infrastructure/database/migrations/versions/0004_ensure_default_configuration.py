from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Guarantee at least one browser configuration exists.

    ``0001`` seeds a ``default`` configuration for brand-new databases, but a
    database created before that seed (or one whose row was deleted) may be
    left with zero configurations. Profile creation / launch then fails with
    ``BrowserConfigurationNotFoundError(0)`` because there is no default to
    fall back on. This migration inserts one when the table is empty.
    """
    conn.execute(
        """
        INSERT INTO browser_configurations
            (name, user_agent, platform, language, locale, timezone,
             screen_width, screen_height, device_pixel_ratio, color_depth,
             webgl_settings, hardware_settings, created_at, updated_at)
        SELECT 'default', NULL, NULL, NULL, NULL, NULL,
               NULL, NULL, NULL, NULL,
               NULL, NULL,
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