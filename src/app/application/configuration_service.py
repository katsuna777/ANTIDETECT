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

_NAME_SAFE = re.compile(r"[\w .()\[\]-]+")


class ConfigurationService:
    def __init__(
        self,
        configurations: BrowserConfigurationRepository,
        generator: ConfigurationGenerator,
    ) -> None:
        self._configurations = configurations
        self._generator = generator

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
        self._validate_spoof_fields(None, params)
        return self._configurations.create(name=name, **params)

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
        self._validate_spoof_fields(current, params)
        updated = self._configurations.update(configuration_id, name=name, **params)
        if updated is None:
            raise BrowserConfigurationNotFoundError(configuration_id)
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
        return self._configurations.create(name=name, **params)

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
        return created

    def delete_configuration(self, configuration_id: int) -> None:
        if self._configurations.get(configuration_id) is None:
            raise BrowserConfigurationNotFoundError(configuration_id)
        # Profiles referencing this configuration are detached (ON DELETE SET
        # NULL), so deleting a configuration never orphans a profile.
        self._configurations.delete(configuration_id)

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