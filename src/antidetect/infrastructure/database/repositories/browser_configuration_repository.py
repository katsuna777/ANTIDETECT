from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.infrastructure.database.datetime_utils import SQL_NOW, parse_dt
from antidetect.infrastructure.database.sequence_utils import reset_sequence

if TYPE_CHECKING:
    from antidetect.infrastructure.database.connection import Database

_COLUMNS = (
    "id, name, user_agent, platform, language, locale, timezone, "
    "screen_width, screen_height, device_pixel_ratio, color_depth, "
    "webgl_settings, hardware_settings, client_hints, privacy_settings, created_at, updated_at"
)


def _columns_for_db(conn) -> str:
    """SELECT list that tolerates pre-0006 databases without client_hints."""
    names = {row[1] for row in conn.execute("PRAGMA table_info(browser_configurations)")}
    cols = (
        "id, name, user_agent, platform, language, locale, timezone, "
        "screen_width, screen_height, device_pixel_ratio, color_depth, "
        "webgl_settings, hardware_settings, "
    )
    cols += "client_hints, " if "client_hints" in names else "NULL AS client_hints, "
    cols += "privacy_settings, " if "privacy_settings" in names else "NULL AS privacy_settings, "
    return cols + "created_at, updated_at"


def _load_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _dump_json(settings: dict | None) -> str | None:
    if not settings:
        return None
    return json.dumps(settings, ensure_ascii=False, sort_keys=True)


def _row_to_configuration(row) -> BrowserConfiguration:
    try:
        hints_raw = row["client_hints"]
    except (IndexError, KeyError):
        hints_raw = None
    try:
        privacy_raw = row["privacy_settings"]
    except (IndexError, KeyError):
        privacy_raw = None
    return BrowserConfiguration(
        id=row["id"],
        name=row["name"],
        user_agent=row["user_agent"],
        platform=row["platform"],
        language=row["language"],
        locale=row["locale"],
        timezone=row["timezone"],
        screen_width=row["screen_width"],
        screen_height=row["screen_height"],
        device_pixel_ratio=row["device_pixel_ratio"],
        color_depth=row["color_depth"],
        webgl_settings=_load_json(row["webgl_settings"]),
        hardware_settings=_load_json(row["hardware_settings"]),
        client_hints=_load_json(hints_raw),
        privacy_settings=_load_json(privacy_raw),
        created_at=parse_dt(row["created_at"]),
        updated_at=parse_dt(row["updated_at"]),
    )


class SqliteBrowserConfigurationRepository:
    def __init__(self, db: "Database") -> None:
        self._db = db

    def _has_column(self, column: str) -> bool:
        try:
            names = {row[1] for row in self._db.execute("PRAGMA table_info(browser_configurations)")}
        except Exception:
            return False
        return column in names

    def _has_client_hints(self) -> bool:
        return self._has_column("client_hints")

    def create(
        self,
        name: str,
        *,
        user_agent: str | None = None,
        platform: str | None = None,
        language: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        screen_width: int | None = None,
        screen_height: int | None = None,
        device_pixel_ratio: float | None = None,
        color_depth: int | None = None,
        webgl_settings: dict | None = None,
        hardware_settings: dict | None = None,
        client_hints: dict | None = None,
        privacy_settings: dict | None = None,
    ) -> BrowserConfiguration:
        has_hints = self._has_client_hints()
        columns = (
            "name, user_agent, platform, language, locale, timezone,"
            " screen_width, screen_height, device_pixel_ratio, color_depth,"
            " webgl_settings, hardware_settings,"
        )
        values = (
            name,
            user_agent,
            platform,
            language,
            locale,
            timezone,
            screen_width,
            screen_height,
            device_pixel_ratio,
            color_depth,
            _dump_json(webgl_settings),
            _dump_json(hardware_settings),
        )
        if has_hints:
            columns += " client_hints,"
            values += (_dump_json(client_hints),)
        if self._has_column("privacy_settings"):
            columns += " privacy_settings,"
            values += (_dump_json(privacy_settings),)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO browser_configurations
                    ({columns} created_at, updated_at)
                VALUES ({", ".join(["?"] * len(values))}, {SQL_NOW}, {SQL_NOW})
                """,
                values,
            )
            configuration_id = int(cursor.lastrowid)
        created = self.get(configuration_id)
        if created is None:
            raise RuntimeError("Failed to load freshly created configuration.")
        return created

    def get(self, configuration_id: int) -> BrowserConfiguration | None:
        row = self._db.execute(
            f"SELECT {_columns_for_db(self._db)} FROM browser_configurations WHERE id = ?",
            (configuration_id,),
        ).fetchone()
        return _row_to_configuration(row) if row else None

    def list(self) -> list[BrowserConfiguration]:
        rows = self._db.execute(
            f"SELECT {_columns_for_db(self._db)} FROM browser_configurations ORDER BY id"
        ).fetchall()
        return [_row_to_configuration(row) for row in rows]

    def find_by_name(self, name: str) -> BrowserConfiguration | None:
        row = self._db.execute(
            f"SELECT {_columns_for_db(self._db)} FROM browser_configurations WHERE name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return _row_to_configuration(row) if row else None

    def get_default(self) -> BrowserConfiguration | None:
        row = self._db.execute(
            f"SELECT {_columns_for_db(self._db)} FROM browser_configurations ORDER BY id LIMIT 1"
        ).fetchone()
        return _row_to_configuration(row) if row else None

    def update(
        self,
        configuration_id: int,
        *,
        name: str | None = None,
        user_agent: str | None = None,
        platform: str | None = None,
        language: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        screen_width: int | None = None,
        screen_height: int | None = None,
        device_pixel_ratio: float | None = None,
        color_depth: int | None = None,
        webgl_settings: dict | None = None,
        hardware_settings: dict | None = None,
        client_hints: dict | None = None,
        privacy_settings: dict | None = None,
    ) -> BrowserConfiguration | None:
        """Update a configuration.

        ``None`` means "leave untouched"; callers that want to clear an
        optional scalar field must pass the empty string, and to clear a JSON
        blob must pass ``{}`` (the empty dict is stored as NULL-equivalent and
        read back as ``None``).
        """
        updates: list[str] = []
        params: list[Any] = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if user_agent is not None:
            updates.append("user_agent = ?")
            params.append(user_agent or None)
        if platform is not None:
            updates.append("platform = ?")
            params.append(platform or None)
        if language is not None:
            updates.append("language = ?")
            params.append(language or None)
        if locale is not None:
            updates.append("locale = ?")
            params.append(locale or None)
        if timezone is not None:
            updates.append("timezone = ?")
            params.append(timezone or None)
        if screen_width is not None:
            updates.append("screen_width = ?")
            params.append(screen_width)
        if screen_height is not None:
            updates.append("screen_height = ?")
            params.append(screen_height)
        if device_pixel_ratio is not None:
            updates.append("device_pixel_ratio = ?")
            params.append(device_pixel_ratio)
        if color_depth is not None:
            updates.append("color_depth = ?")
            params.append(color_depth)
        if webgl_settings is not None:
            updates.append("webgl_settings = ?")
            params.append(_dump_json(webgl_settings))
        if hardware_settings is not None:
            updates.append("hardware_settings = ?")
            params.append(_dump_json(hardware_settings))
        if client_hints is not None and self._has_client_hints():
            updates.append("client_hints = ?")
            params.append(_dump_json(client_hints))
        if privacy_settings is not None and self._has_column("privacy_settings"):
            updates.append("privacy_settings = ?")
            params.append(_dump_json(privacy_settings))
        if not updates:
            return self.get(configuration_id)
        updates.append(f"updated_at = {SQL_NOW}")
        params.append(configuration_id)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE browser_configurations SET {', '.join(updates)} "
                "WHERE id = ?",
                params,
            )
        return self.get(configuration_id)

    def delete(self, configuration_id: int) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM browser_configurations WHERE id = ?",
                (configuration_id,),
            )
            reset_sequence(conn, "browser_configurations")
            return cursor.rowcount > 0