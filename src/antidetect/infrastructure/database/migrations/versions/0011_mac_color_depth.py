from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Retina Macs report a colour depth of 30, not 24.

    Until now ``color_depth`` was stored but never applied, so pages saw whatever the host's
    display said. The value is applied from now on, and macOS profiles on a 2x screen must keep
    the 30 (and the wide gamut that goes with it) pages have been seeing, instead of silently
    becoming 24. Other platforms stay 24 on purpose: that is what their displays report.
    """
    conn.execute(
        """
        UPDATE browser_configurations
           SET color_depth = 30
         WHERE platform = 'macos'
           AND COALESCE(device_pixel_ratio, 1) >= 2
           AND COALESCE(color_depth, 24) = 24
        """
    )


def downgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE browser_configurations SET color_depth = 24 WHERE platform = 'macos' AND color_depth = 30"
    )
