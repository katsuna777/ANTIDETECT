"""Business operations over browser configurations.

Orchestrates the repository and the generator; owns unique-name resolution,
manual edits and duplication. Knows nothing about SQLite or the CLI.
"""

from __future__ import annotations

import re
from typing import Any

from app.application.configuration_generator import ConfigurationGenerator
from app.application.ports import BrowserConfigurationRepository
from app.domain.errors import BrowserConfigurationNotFoundError
from app.domain.models.browser_configuration import BrowserConfiguration

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.application.ports import LogSink

_NAME_SAFE = re.compile(r"[\w .()\[\]-]+")


class ConfigurationService:
    def __init__(
        self,
        configurations: BrowserConfigurationRepository,
        generator: ConfigurationGenerator,
        log_sink: "LogSink | None" = None,
    ) -> None:
        self._configurations = configurations
        self._generator = generator
        self._log = log_sink

    # ---------------------------------------------------------------- reads

    def get_configuration(self, configuration_id: int) -> BrowserConfiguration:
        configuration = self._configurations.get(configuration_id)
        if configuration is None:
            raise BrowserConfigurationNotFoundError(configuration_id)
        return configuration

    def list_configurations(self) -> list[BrowserConfiguration]:
        return self._configurations.list()

    def get_default(self) -> BrowserConfiguration | None:
        return self._configurations.get_default()

    # --------------------------------------------------------------- writes

    def create_configuration(
        self, name: str, **params: Any
    ) -> BrowserConfiguration:
        name = self._normalize_name(name)
        self._reject_duplicate_name(name)
        self._validate_timezone(params.get("timezone"))
        self._validate_spoof_fields(None, params)
        created = self._configurations.create(name=name, **params)
        self._log_info(
            "configurations",
            f"Configuration #{created.id} '{created.name}' created",
            extra={
                "configuration_id": created.id,
                "name": created.name,
                "platform": created.platform,
                "timezone": created.timezone,
            },
        )
        return created

    def update_configuration(
        self,
        configuration_id: int,
        *,
        name: str | None = None,
        **params: Any,
    ) -> BrowserConfiguration:
        current = self.get_configuration(configuration_id)
        if name is not None:
            name = self._normalize_name(name)
            if name != current.name:
                self._reject_duplicate_name(name)
        if "timezone" in params:
            self._validate_timezone(params["timezone"])
        params = self._realign_platform_dependents(current, params)
        self._validate_spoof_fields(current, params)
        updated = self._configurations.update(configuration_id, name=name, **params)
        if updated is None:
            raise BrowserConfigurationNotFoundError(configuration_id)
        changed = sorted(
            key for key, value in params.items() if value is not None
        )
        if name is not None and name != current.name:
            changed = sorted(set(changed) | {"name"})
        self._log_info(
            "configurations",
            f"Configuration #{configuration_id} '{updated.name}' updated",
            extra={
                "configuration_id": configuration_id,
                "name": updated.name,
                "changed": changed,
            },
        )
        return updated

    def align_configuration_geo(
        self, configuration_id: int, country_code: str
    ) -> BrowserConfiguration:
        """Auto-fix a configuration's geo fields to a proxy exit country.

        Sets timezone + locale + language to the country's defaults so the
        doctor geo-gate (exit == timezone == locale) passes. Raises
        ValueError for countries without known defaults.
        """
        from app.application.configuration_generator import country_defaults

        code = (country_code or "").strip().upper()
        defaults = country_defaults(code)
        if defaults is None:
            raise ValueError(
                f"Unknown country {country_code!r}: no known language/locale/timezone. "
                "Pick the timezone manually from the supported list."
            )
        language, locale, timezone = defaults
        updated = self.update_configuration(
            configuration_id,
            language=language,
            locale=locale,
            timezone=timezone,
        )
        self._log_info(
            "configurations",
            f"Configuration #{configuration_id} geo auto-fixed to {code}",
            extra={
                "configuration_id": configuration_id,
                "country": code,
                "timezone": timezone,
                "locale": locale,
            },
        )
        return updated

    @staticmethod
    def _validate_timezone(timezone: Any) -> None:
        """Reject timezones the doctor cannot map to an exit country.

        Runs on every create/update (even without a User-Agent), so a typo
        like ``UTC+3`` or ``Moscow`` fails fast with the full supported
        list instead of surfacing later as a doctor BLOCKED at launch.
        """
        from app.application.profile_doctor import SUPPORTED_TIMEZONES

        if timezone is None:
            return
        if timezone in SUPPORTED_TIMEZONES:
            return
        raise ValueError(
            f"Unknown timezone {timezone!r}. "
            f"Supported timezones: {', '.join(SUPPORTED_TIMEZONES)}"
        )

    def align_browser_version(
        self, configuration_id: int, major: int
    ) -> BrowserConfiguration:
        """Auto-fix a UA/binary drift: rebuild UA + Client Hints for ``major``.

        Used by the one-click fix offered when the doctor blocks a launch
        with ``ua-binary-drift`` (fingerprint says Chrome/150, installed
        binary is Chrome/152). Raises ValueError when the stored
        configuration has no Chrome User-Agent to patch.
        """
        import re

        from app.application.configuration_generator import (
            build_client_hints,
            chrome_major,
            ua_chrome_major,
        )

        current = self.get_configuration(configuration_id)
        old_major = ua_chrome_major(current.user_agent or "")
        if old_major is None:
            raise ValueError(
                "Configuration has no Chrome User-Agent to align; "
                "regenerate it instead."
            )
        major = int(major)
        if major == old_major:
            return current
        hints = dict(current.client_hints or {})
        base_version = str(hints.get("fullVersion") or "")
        if chrome_major(base_version) == old_major and "." in base_version:
            version = f"{major}." + base_version.split(".", 1)[1]
        else:
            version = f"{major}.0.0.0"
        user_agent = re.sub(
            r"Chrome/\d+\.", f"Chrome/{major}.", current.user_agent or ""
        )
        user_agent = re.sub(r"Edg/\d+\.", f"Edg/{major}.", user_agent)
        browser = "edge" if "Edg/" in user_agent else "chrome"
        platform = current.platform
        if platform not in ("windows", "macos", "linux"):
            platform = _infer_platform(user_agent)
        if platform is not None:
            client_hints: Any = build_client_hints(browser, platform, version)
        else:
            client_hints = dict(hints)
            client_hints["fullVersion"] = version
            patched_brands = []
            for brand in client_hints.get("brands") or []:
                brand = dict(brand)
                if brand.get("brand") != "Not-A.Brand":
                    brand["version"] = str(major)
                patched_brands.append(brand)
            client_hints["brands"] = patched_brands
        updated = self.update_configuration(
            configuration_id,
            user_agent=user_agent,
            client_hints=client_hints,
        )
        self._log_info(
            "configurations",
            f"Configuration #{configuration_id} browser version auto-fixed "
            f"to Chrome/{major}",
            extra={"configuration_id": configuration_id, "chrome_major": major},
        )
        return updated

    @staticmethod
    def _validate_spoof_fields(
        current: BrowserConfiguration | None, params: dict[str, Any]
    ) -> None:
        """Fail fast on legacy/contradictory spoof fields (creation-time gate).

        Only runs when the effective User-Agent is non-empty; bare
        non-spoofed configurations are unaffected. Raises ValueError.
        """
        from app.application.configuration_generator import validate_draft

        def effective(key: str) -> Any:
            if key in params and params[key] is not None:
                return params[key]
            return getattr(current, key, None) if current is not None else None

        if not effective("user_agent"):
            return
        validate_draft(
            {
                "user_agent": effective("user_agent"),
                "platform": effective("platform"),
                "language": effective("language"),
                "locale": effective("locale"),
                "timezone": effective("timezone"),
                "screen_width": effective("screen_width"),
                "screen_height": effective("screen_height"),
                "device_pixel_ratio": effective("device_pixel_ratio"),
                "color_depth": effective("color_depth"),
                "webgl_settings": effective("webgl_settings"),
                "hardware_settings": effective("hardware_settings"),
                "client_hints": effective("client_hints"),
            }
        )

    def generate_configuration(
        self,
        name: str | None = None,
        template: str | None = None,
        platform: str | None = None,
    ) -> BrowserConfiguration:
        """Generate a coherent configuration and persist it immediately."""
        if template is not None:
            params = self._generator.generate_from_template(template)
        else:
            params = self._generator.generate_random(platform=platform)
        name = name or self._default_generated_name(base=template or "random")
        name = self._normalize_name(name)
        self._reject_duplicate_name(name)
        created = self._configurations.create(name=name, **params)
        self._log_info(
            "configurations",
            f"Configuration #{created.id} '{created.name}' generated"
            + (f" from template '{template}'" if template else " (random)")
            + (f" for {platform}" if platform else ""),
            extra={
                "configuration_id": created.id,
                "name": created.name,
                "template": template,
                "platform": created.platform,
                "timezone": created.timezone,
            },
        )
        return created

    def duplicate_configuration(
        self,
        configuration_id: int,
        name: str | None = None,
    ) -> BrowserConfiguration:
        source = self.get_configuration(configuration_id)
        name = name or f"{source.name} (copy)"
        name = self._normalize_name(name)
        self._reject_duplicate_name(name)
        created = self._configurations.create(
            name=name,
            user_agent=source.user_agent,
            platform=source.platform,
            language=source.language,
            locale=source.locale,
            timezone=source.timezone,
            screen_width=source.screen_width,
            screen_height=source.screen_height,
            device_pixel_ratio=source.device_pixel_ratio,
            color_depth=source.color_depth,
            webgl_settings=source.webgl_settings,
            hardware_settings=source.hardware_settings,
            client_hints=source.client_hints,
        )
        self._log_info(
            "configurations",
            f"Configuration #{source.id} duplicated to "
            f"#{created.id} '{created.name}'",
            extra={
                "configuration_id": created.id,
                "name": created.name,
                "source_id": source.id,
            },
        )
        return created

    def delete_configuration(self, configuration_id: int) -> None:
        if self._configurations.get(configuration_id) is None:
            raise BrowserConfigurationNotFoundError(configuration_id)
        # Profiles referencing this configuration are detached (ON DELETE SET
        # NULL), so deleting a configuration never orphans a profile.
        self._configurations.delete(configuration_id)
        self._log_info(
            "configurations",
            f"Configuration #{configuration_id} deleted",
            extra={"configuration_id": configuration_id},
        )

    def list_templates(self) -> list[str]:
        return self._generator.list_templates()

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _normalize_name(name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Configuration name must not be empty.")
        if not _NAME_SAFE.fullmatch(name):
            raise ValueError(
                f"Configuration name {name!r} contains unsupported characters."
            )
        return name

    def _reject_duplicate_name(self, name: str) -> None:
        if self._configurations.find_by_name(name) is not None:
            raise ValueError(f"A configuration named {name!r} already exists.")

    def _default_generated_name(self, base: str) -> str:
        candidate = base
        index = 2
        while self._configurations.find_by_name(candidate) is not None:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    @staticmethod
    def _realign_platform_dependents(
        current: BrowserConfiguration, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Rebuild UA / Client Hints / WebGL when the platform changes.

        A macOS fingerprint switched to ``linux`` keeps its old Apple UA and
        macOS hints, which ``validate_draft`` then rejects
        (``platform 'linux' mismatches client_hints platform 'macOS'``).
        Instead of failing, rebuild the derived fields for the new platform
        — unless the caller passed any of them explicitly (explicit values
        win and go through validation untouched).
        """
        new_platform = params.get("platform")
        if (
            new_platform is None
            or new_platform == current.platform
            or new_platform not in ("windows", "macos", "linux")
        ):
            return params
        if (
            "user_agent" in params
            or "client_hints" in params
            or "webgl_settings" in params
        ):
            return params
        if not current.user_agent:
            return params

        from app.application.configuration_generator import (
            _WEBGL,
            build_client_hints,
            build_user_agent,
            chrome_major,
            ua_chrome_major,
        )

        hints = current.client_hints if isinstance(current.client_hints, dict) else {}
        base_version = str(hints.get("fullVersion") or "")
        ua_major = ua_chrome_major(current.user_agent or "")
        if chrome_major(base_version) and (
            ua_major is None or chrome_major(base_version) == ua_major
        ):
            version = base_version
        elif ua_major is not None:
            version = f"{ua_major}.0.0.0"
        else:
            return params

        browser = "edge" if "Edg/" in (current.user_agent or "") else "chrome"
        params = dict(params)
        params["user_agent"] = build_user_agent(browser, new_platform, version)
        params["client_hints"] = build_client_hints(browser, new_platform, version)
        old_webgl = (
            current.webgl_settings
            if isinstance(current.webgl_settings, dict)
            else None
        )
        if old_webgl is not None:
            vendor, renderer = _WEBGL[new_platform][0]
            params["webgl_settings"] = {
                **old_webgl,
                "vendor": vendor,
                "renderer": renderer,
            }
        return params

    def _log_info(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.info(source, message, extra)


def _infer_platform(user_agent: str) -> str | None:
    """Guess windows/macos/linux from a User-Agent string (best effort)."""
    ua = user_agent or ""
    if "Windows NT" in ua:
        return "windows"
    if "Macintosh" in ua:
        return "macos"
    if "Linux" in ua or "X11" in ua:
        return "linux"
    return None