from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from antidetect.application.fingerprint import privacy
from antidetect.application.fingerprint.generator import (
    PLATFORMS,
    ConfigurationGenerator,
    country_defaults,
    validate_draft,
)
from antidetect.application.fingerprint.data import host_platform
from antidetect.application.profile_doctor import TIMEZONE_COUNTRY, locale_country
from antidetect.application.ports import (
    BrowserConfigurationRepository,
    BrowserManager,
    ProfileRepository,
    ProxyRepository,
    SettingsRepository,
)
from antidetect.application.profile_path_resolver import ProfilePathResolver
from antidetect.domain.enums.profile_status import ProfileStatus
from antidetect.domain.enums.proxy_status import ProxyStatus
from antidetect.application.profile_doctor import DoctorReport, diagnose
from antidetect.domain.errors import (
    BrowserConfigurationNotFoundError,
    ChromiumError,
    ProfileAlreadyExistsError,
    ProfileAlreadyRunningError,
    ProfileConfigurationMissingError,
    ProfileNotFoundError,
    ProfileNotRunningError,
    ProxyNotFoundError,
    ProxyNotUsableError,
    WorkspaceNotFoundError,
)
from antidetect.domain.models.browser_configuration import BrowserConfiguration
from antidetect.domain.models.profile import Profile
from antidetect.domain.models.proxy import ProxyWithCheck

if TYPE_CHECKING:
    from antidetect.application.ports import ActivitySink, LogSink, WorkspaceRepository
    from antidetect.application.tag_service import TagService

#: how long a profile stays in the trash before it is deleted for good (settings key + default)
TRASH_RETENTION_KEY = "retention.trash_days"
TRASH_RETENTION_DEFAULT = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _geo_matches(configuration: BrowserConfiguration, country: str) -> bool:
    """True when a configuration's locale+timezone already fit ``country``."""
    code = (country or "").upper()
    if locale_country(configuration.locale) != code:
        return False
    return TIMEZONE_COUNTRY.get(configuration.timezone or "") == code


#: Configurations created together with a profile carry this name prefix. They
#: belong to exactly one profile (one fingerprint per profile), are edited in
#: place when geo changes, and are removed with the profile.
DEDICATED_PREFIX = "fp-"
_DIRECT_COUNTRY_TTL = 600.0


def is_dedicated(configuration: BrowserConfiguration | None) -> bool:
    return bool(configuration is not None and configuration.name.startswith(DEDICATED_PREFIX))


class ProfileDetails:
    """A profile joined with its assigned proxy/configuration read models."""

    __slots__ = ("profile", "proxy_check", "configuration")

    def __init__(
        self,
        profile: Profile,
        proxy_check: ProxyWithCheck | None = None,
        configuration: BrowserConfiguration | None = None,
    ) -> None:
        self.profile = profile
        self.proxy_check = proxy_check
        self.configuration = configuration


class ProfileService:
    """Business operations over browser profiles.

    Orchestrates repositories, the browser manager and the filesystem. It knows
    nothing about SQLite, Chromium launch flags or the CLI; it depends only on
    the abstract ports defined in :mod:`antidetect.application.ports`.
    """

    def __init__(
        self,
        profiles: ProfileRepository,
        configurations: BrowserConfigurationRepository,
        settings: SettingsRepository,
        browsers: BrowserManager,
        path_resolver: ProfilePathResolver,
        proxies: ProxyRepository | None = None,
        log_sink: "LogSink | None" = None,
        google_probe=None,
        generator: ConfigurationGenerator | None = None,
        geo_lookup: Callable[[], str | None] | None = None,
        activity: "ActivitySink | None" = None,
        tag_registry: "TagService | None" = None,
        workspaces: "WorkspaceRepository | None" = None,
    ) -> None:
        self._profiles = profiles
        self._configurations = configurations
        self._settings = settings
        self._browsers = browsers
        self._paths = path_resolver
        self._proxies = proxies
        self._log = log_sink
        # End-to-end Google reachability through the assigned proxy (tests stub
        # it; production uses transport.probe_google).
        self._google_probe = google_probe
        # Fingerprint generator for proxy-matched auto-configurations (wired
        # by di/bootstrap; None disables auto-config generation).
        self._generator = generator
        # Country of this machine's own public IP (used for auto-geo when a
        # profile has no proxy). Injected by di; None disables the lookup.
        self._geo_lookup = geo_lookup
        self._direct_country_cache: tuple[float, str | None] | None = None
        # What the Activity page shows; tags are registered (and spelled) through the registry;
        # workspaces are only needed to reject an id that does not exist.
        self._activity = activity
        self._tag_registry = tag_registry
        self._workspaces = workspaces
        self._paths.ensure_root()

    # ------------------------------------------------------------------ reads

    def get_profile(self, profile_id: int, *, include_trashed: bool = False) -> Profile:
        """The profile; one in the trash is "not found" unless ``include_trashed`` (restore / delete for good)."""
        profile = self._profiles.get(profile_id)
        if profile is None or (profile.is_trashed and not include_trashed):
            raise ProfileNotFoundError(profile_id)
        return self._reconcile(profile) if not profile.is_trashed else profile

    def list_profiles(self) -> list[Profile]:
        """Profiles that are not in the trash."""
        return [self._reconcile(p) for p in self._profiles.list()]

    def list_trashed_profiles(self) -> list[Profile]:
        return self._profiles.list_trashed()

    def count_trashed(self) -> int:
        return self._profiles.count_trashed()

    def get_profile_details(self, profile_id: int) -> ProfileDetails:
        profile = self.get_profile(profile_id)
        configuration = None
        if profile.configuration_id is not None:
            configuration = self._configurations.get(profile.configuration_id)
        return ProfileDetails(
            profile=profile,
            proxy_check=self._proxy_check_for(profile),
            configuration=configuration,
        )

    def list_profiles_details(self) -> list[ProfileDetails]:
        profiles = [self._reconcile(p) for p in self._profiles.list()]
        if not profiles or self._proxies is None:
            return [ProfileDetails(profile=p) for p in profiles]

        proxy_ids = [p.proxy_id for p in profiles if p.proxy_id is not None]
        by_id = (
            {row.id: row for row in self._proxies.list_with_latest_check(proxy_ids=proxy_ids)}
            if proxy_ids
            else {}
        )
        return [
            ProfileDetails(profile=p, proxy_check=by_id.get(p.proxy_id))
            for p in profiles
        ]

    def diagnose_profile(self, profile_id: int, *, probe_google: bool = True) -> DoctorReport:
        """Run the pre-launch consistency diagnostics without launching.

        ``probe_google=False`` skips the live Google reachability check and is
        intended for offline use; ``start_profile`` always probes.
        """
        profile = self.get_profile(profile_id)
        configuration = None
        if profile.configuration_id is not None:
            configuration = self._configurations.get(profile.configuration_id)
        proxy_check = self._proxy_check_for(profile)
        proxy = proxy_check.proxy if proxy_check is not None else None
        if proxy is None and profile.proxy_id is not None and self._proxies is not None:
            proxy = self._proxies.get(profile.proxy_id)
        google: bool | None = None
        if proxy is not None and probe_google:
            google = self._google_reachable(proxy)
        return diagnose(
            configuration,
            binary_major=self._browser_major(),
            proxy_country_code=(
                proxy_check.country_code if proxy_check is not None
                else (proxy.country_code if proxy is not None else None)
            ),
            anonymity=(
                proxy_check.anonymity.value if proxy_check is not None and proxy_check.anonymity else None
            ),
            google_reachable=google,
            has_proxy=proxy is not None,
        )

    # ---------------------------------------------------------------- writes

    def create_profile(
        self,
        name: str,
        configuration_id: int | None = None,
        proxy_id: int | None = None,
        auto_config: bool = True,
        *,
        platform: str | None = None,
        notes: str = "",
        tags: list[str] | None = None,
        geo_auto: bool = True,
        start_url: str | None = None,
        workspace_id: int | None = None,
        privacy_settings: dict | None = None,
    ) -> Profile:
        """Create a profile with its own, internally consistent fingerprint.

        Without an explicit ``configuration_id`` a fresh fingerprint is generated
        for ``platform`` (default: the OS this app runs on, which is the most
        natural choice) — profiles never silently share one.
        """
        name = name.strip()
        if not name:
            raise ValueError("Profile name must not be empty.")
        if self._profiles.find_by_name(name) is not None:
            raise ProfileAlreadyExistsError(name)
        if platform is not None and platform not in PLATFORMS:
            raise ValueError(f"Unknown platform {platform!r}; expected one of {PLATFORMS}")
        privacy.validate(privacy_settings)

        proxy_id = self._validate_proxy_id(proxy_id)
        workspace_id = self._validate_workspace_id(workspace_id)
        tags = self._canonical_tags(tags)
        if configuration_id is None and self._generator is not None:
            configuration_id = self._create_dedicated_configuration(name, platform, privacy_settings)
        else:
            configuration_id = self._resolve_configuration(configuration_id)
        now = utcnow()

        # Two-step insert: the on-disk directory name depends on the row id.
        created = self._profiles.create(
            name=name,
            profile_path="",  # placeholder, filled below
            configuration_id=configuration_id,
            proxy_id=proxy_id,
            created_at=now,
            notes=notes,
            tags=tags,
            geo_auto=geo_auto,
            start_url=(start_url or "").strip() or None,
            workspace_id=workspace_id,
        )
        profile_path = str(self._paths.resolve(created.id))
        self._profiles.update(created.id, profile_path=profile_path)
        if auto_config and proxy_id is not None:
            self._maybe_auto_config(created.id)
        finished = self._profiles.get(created.id)
        if finished is not None:
            self._log_info(
                "profiles",
                f"Profile #{finished.id:03d} '{finished.name}' created",
                extra={
                    "profile_id": finished.id,
                    "name": finished.name,
                    "configuration_id": finished.configuration_id,
                    "proxy_id": finished.proxy_id,
                },
            )
            self._record("act.profile.created", finished)
        return finished  # type: ignore[return-value]

    def update_profile(
        self,
        profile_id: int,
        name: str | None = None,
        configuration_id: int | None = None,
        proxy_id: int | None = None,
        auto_config: bool = True,
        *,
        notes: str | None = None,
        tags: list[str] | None = None,
        geo_auto: bool | None = None,
        start_url: str | None = None,
    ) -> Profile:
        before = self.get_profile(profile_id)  # raises ProfileNotFoundError for an unknown id

        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Profile name must not be empty.")
            existing = self._profiles.find_by_name(name)
            if existing is not None and existing.id != profile_id:
                raise ProfileAlreadyExistsError(name)

        if configuration_id is not None:
            if self._configurations.get(configuration_id) is None:
                raise BrowserConfigurationNotFoundError(configuration_id)

        if proxy_id is not None:
            proxy_id = self._validate_proxy_id(proxy_id)
        if tags is not None:
            tags = self._canonical_tags(tags)

        self._profiles.update(
            profile_id,
            name=name,
            configuration_id=configuration_id,
            proxy_id=proxy_id,
            notes=notes,
            tags=tags,
            geo_auto=geo_auto,
            start_url=None if start_url is None else start_url.strip(),
        )
        updated = self._profiles.get(profile_id)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} updated",
            extra={
                "profile_id": profile_id,
                "name": updated.name,
                "configuration_id": updated.configuration_id,
                "proxy_id": updated.proxy_id,
            },
        )
        changed = [
            field for field, differs in (
                ("name", updated.name != before.name),
                ("notes", updated.notes != before.notes),
                ("tags", list(updated.tags) != list(before.tags)),
                ("proxy", updated.proxy_id != before.proxy_id),
            ) if differs
        ]
        if changed:            # a start page set for one launch (open_url) is not worth a line in the feed
            self._record("act.profile.updated", updated, fields=changed, old=before.name if "name" in changed else None)
        if auto_config and configuration_id is None and updated.proxy_id is not None:
            # A proxy (re)assignment without an explicit configuration means
            # "match the fingerprint to the proxy" — same as assign_proxy.
            self._maybe_auto_config(profile_id)
            refreshed = self._profiles.get(profile_id)
            if refreshed is not None:
                return refreshed
        return updated

    def remove_configuration(self, profile_id: int) -> Profile:
        """Detach the profile's configuration (start() then requires one)."""
        self.get_profile(profile_id)
        updated = self._profiles.set_configuration(profile_id, None)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} configuration detached",
            extra={"profile_id": profile_id},
        )
        return updated

    def assign_proxy(
        self, profile_id: int, proxy_id: int | None, auto_config: bool = True
    ) -> Profile:
        """Assign, change or remove (``proxy_id=None``) the profile's proxy.

        With ``auto_config`` (default) assigning a proxy also aligns the
        fingerprint: timezone/locale are matched to the proxy exit country
        (reusing a fitting configuration when one exists, otherwise generating
        ``auto-<CC>-<platform>``). Pass ``auto_config=False`` to keep the
        current configuration untouched.
        """
        self.get_profile(profile_id)
        if proxy_id is not None:
            proxy_id = self._validate_proxy_id(proxy_id)
        updated = self._profiles.set_proxy(profile_id, proxy_id)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
        if proxy_id is None:
            self._log_info(
                "profiles",
                f"Profile #{profile_id:03d} proxy detached",
                extra={"profile_id": profile_id},
            )
        else:
            self._log_info(
                "profiles",
                f"Profile #{profile_id:03d} proxy set to #{proxy_id}",
                extra={"profile_id": profile_id, "proxy_id": proxy_id},
            )
        if auto_config and proxy_id is not None:
            self._maybe_auto_config(profile_id)
            refreshed = self._profiles.get(profile_id)
            if refreshed is not None:
                return refreshed
        return updated

    def _maybe_auto_config(self, profile_id: int) -> None:
        """Align the profile's fingerprint with its proxy exit country."""
        profile = self.get_profile(profile_id)
        if profile.proxy_id is None or self._proxies is None:
            return
        proxy = self._proxies.get(profile.proxy_id)
        if proxy is None:
            return
        country = self._exit_country(proxy)
        if country is None:
            self._log_warn(
                "profiles",
                f"Profile #{profile_id:03d} proxy country unknown — configuration untouched",
                extra={"profile_id": profile_id, "proxy_id": proxy.id},
            )
            return
        self._align_geo(profile, country)

    def _align_geo(self, profile: Profile, country: str) -> bool:
        """Make the profile's language/locale/time zone fit ``country``.

        A dedicated fingerprint is edited in place; a shared/legacy one is left
        alone and the profile gets its own geo-matched copy instead, so a change
        for one profile can never leak into another. Returns True on change.
        """
        defaults = country_defaults(country)
        if defaults is None:
            self._log_warn(
                "profiles",
                f"Profile #{profile.id:03d}: no language/time zone known for {country} — geo untouched",
                extra={"profile_id": profile.id, "country": country},
            )
            return False
        current = (
            self._configurations.get(profile.configuration_id)
            if profile.configuration_id is not None
            else None
        )
        if current is not None and _geo_matches(current, country):
            return False
        language, locale_tag, timezone_id = defaults
        if is_dedicated(current):
            self._configurations.update(
                current.id, language=language, locale=locale_tag, timezone=timezone_id
            )
            self._log_info(
                "profiles",
                f"Profile #{profile.id:03d} geo set to {country} ({timezone_id}, {locale_tag})",
                extra={"profile_id": profile.id, "country": country, "timezone": timezone_id},
            )
            return True
        if self._generator is None:
            return False
        platform = (
            current.platform
            if current is not None and current.platform in PLATFORMS
            else host_platform()
        )
        params = self._generator.generate_for_country(country, platform=platform)
        name = self._unique_config_name(f"{DEDICATED_PREFIX}{profile.name}")
        created = self._configurations.create(name=name, **params)
        self._profiles.set_configuration(profile.id, created.id)
        self._log_info(
            "profiles",
            f"Profile #{profile.id:03d} got a fingerprint for {country}",
            extra={"profile_id": profile.id, "configuration_id": created.id, "country": country},
        )
        return True

    def _create_dedicated_configuration(
        self, profile_name: str, platform: str | None, privacy_settings: dict | None = None
    ) -> int:
        assert self._generator is not None
        params = self._generator.generate_random(platform=platform or host_platform())
        name = self._unique_config_name(f"{DEDICATED_PREFIX}{profile_name}")
        return self._configurations.create(name=name, privacy_settings=privacy_settings, **params).id

    def _unique_config_name(self, base: str) -> str:
        name, index = base, 2
        while self._configurations.find_by_name(name) is not None:
            name = f"{base}-{index}"
            index += 1
        return name

    def _direct_country(self) -> str | None:
        """Country of this machine's own IP (cached; None when unknown/offline)."""
        if self._geo_lookup is None:
            return None
        now = time.monotonic()
        cached = self._direct_country_cache
        if cached is not None and now - cached[0] < _DIRECT_COUNTRY_TTL:
            return cached[1]
        try:
            country = self._geo_lookup()
        except Exception:
            country = None
        country = (country or "").strip().upper() or None
        self._direct_country_cache = (now, country)
        return country

    def _prepare_launch(self, profile: Profile) -> Profile:
        """Repair what can be repaired automatically right before launch."""
        configuration = (
            self._configurations.get(profile.configuration_id)
            if profile.configuration_id is not None
            else None
        )
        if configuration is None and self._generator is not None:
            cid = self._create_dedicated_configuration(profile.name, None)
            self._profiles.set_configuration(profile.id, cid)
            self._log_info(
                "profiles",
                f"Profile #{profile.id:03d} had no fingerprint — generated one",
                extra={"profile_id": profile.id, "configuration_id": cid},
            )
            profile = self._profiles.get(profile.id) or profile
        if profile.geo_auto:
            country = None
            if profile.proxy_id is not None and self._proxies is not None:
                proxy = self._proxies.get(profile.proxy_id)
                country = self._exit_country(proxy) if proxy is not None else None
            elif profile.proxy_id is None:
                country = self._direct_country()
            if country and self._align_geo(profile, country):
                profile = self._profiles.get(profile.id) or profile
        return profile

    def _exit_country(self, proxy) -> str | None:
        """Proxy exit country: latest check first, stored value as fallback."""
        if self._proxies is not None:
            try:
                rows = self._proxies.list_with_latest_check(proxy_ids=[proxy.id])
            except Exception:
                rows = []
            if rows and rows[0].country_code:
                return str(rows[0].country_code).upper()
        if proxy.country_code:
            return str(proxy.country_code).upper()
        return None

    def remove_proxy(self, profile_id: int) -> Profile:
        return self.assign_proxy(profile_id, None)

    # ------------------------------------------------------------ trash
    def trash_profile(self, profile_id: int) -> Profile:
        """Move a profile to the trash: it disappears from every list but nothing on disk is touched.

        A running profile is stopped first. ``restore_profile`` brings it back exactly as it was
        (cookies and fingerprint included); ``delete_profile`` / the retention period remove it for good.
        """
        profile = self.get_profile(profile_id)
        if profile.status is ProfileStatus.RUNNING:
            self.stop_profile(profile_id)
        self._profiles.trash([profile_id], utcnow())
        trashed = self._profiles.get(profile_id)
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} '{profile.name}' moved to the trash",
            extra={"profile_id": profile_id, "name": profile.name},
        )
        self._record("act.profile.trashed", profile)
        return trashed  # type: ignore[return-value]

    def restore_profile(self, profile_id: int) -> Profile:
        """Take a profile out of the trash. If its name is taken meanwhile it comes back as ``Name (2)``."""
        profile = self.get_profile(profile_id, include_trashed=True)
        if not profile.is_trashed:
            return profile
        name = None
        if self._profiles.find_by_name(profile.name) is not None:
            n = 2
            while self._profiles.find_by_name(f"{profile.name} ({n})") is not None:
                n += 1
            name = f"{profile.name} ({n})"
        restored = self._profiles.restore(profile_id, name)
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} '{restored.name if restored else profile.name}' restored from the trash",
            extra={"profile_id": profile_id},
        )
        self._record("act.profile.restored", restored or profile)
        return restored  # type: ignore[return-value]

    def delete_profile(self, profile_id: int) -> None:
        """Delete a profile for good: its folder (cookies, history, everything) and its record.

        A profile in the trash can be deleted this way too. For the everyday "delete" use
        :meth:`trash_profile`, which can be undone.
        """
        profile = self.get_profile(profile_id, include_trashed=True)
        if profile.status is ProfileStatus.RUNNING:
            self.stop_profile(profile_id)

        profile_path = Path(profile.profile_path)
        if profile_path.exists():
            shutil.rmtree(profile_path, ignore_errors=True)
        self._profiles.delete(profile_id)
        self._drop_orphan_configuration(profile.configuration_id)
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} '{profile.name}' deleted",
            extra={"profile_id": profile_id, "name": profile.name},
        )
        self._record("act.profile.purged", profile)

    def empty_trash(self) -> int:
        """Delete everything in the trash for good; returns how many profiles went."""
        trashed = self._profiles.list_trashed()
        for profile in trashed:
            self.delete_profile(profile.id)
        if trashed:
            self._record_raw("act.trash.emptied", count=len(trashed))
        return len(trashed)

    def purge_expired(self, days: int | None = None) -> int:
        """Delete the profiles that have been in the trash longer than ``days`` (0 = keep forever)."""
        days = self.trash_retention_days() if days is None else days
        if days <= 0:
            return 0
        cutoff = utcnow().replace(tzinfo=None)
        removed = 0
        for profile in self._profiles.list_trashed():
            if profile.deleted_at is not None and (cutoff - profile.deleted_at).days >= days:
                self.delete_profile(profile.id)
                removed += 1
        if removed:
            self._record_raw("act.trash.expired", count=removed, days=days)
        return removed

    def trash_retention_days(self) -> int:
        setting = self._settings.get(TRASH_RETENTION_KEY)
        try:
            return max(0, int(setting.value)) if setting is not None and setting.value not in (None, "") \
                else TRASH_RETENTION_DEFAULT
        except ValueError:
            return TRASH_RETENTION_DEFAULT

    def set_trash_retention_days(self, days: int) -> None:
        self._settings.set(TRASH_RETENTION_KEY, str(max(0, int(days))))

    def _drop_orphan_configuration(self, configuration_id: int | None) -> None:
        """Remove a dedicated fingerprint nobody references any more."""
        if configuration_id is None:
            return
        configuration = self._configurations.get(configuration_id)
        if not is_dedicated(configuration):
            return
        if any(p.configuration_id == configuration_id for p in self._profiles.list_all()):
            return
        self._configurations.delete(configuration_id)

    def duplicate_profile(self, profile_id: int, name: str | None = None) -> Profile:
        source = self.get_profile(profile_id)
        new_name = (name or f"{source.name} (copy)").strip()
        if self._profiles.find_by_name(new_name) is not None:
            raise ProfileAlreadyExistsError(new_name)

        # Copy from a quiesced profile: the source browser must be stopped so
        # its SQLite-backed state (cookies, localStorage) is copied consistently.
        if self._browsers.is_running(Path(source.profile_path), source.pid):
            self.stop_profile(profile_id)

        now = utcnow()
        # A dedicated fingerprint is cloned so edits to the copy never touch the
        # original; a shared (preset) one is simply referenced again.
        configuration_id = source.configuration_id
        source_config = (
            self._configurations.get(configuration_id) if configuration_id is not None else None
        )
        if is_dedicated(source_config):
            clone = self._unique_config_name(f"{DEDICATED_PREFIX}{new_name}")
            configuration_id = self._configurations.create(
                name=clone,
                user_agent=source_config.user_agent,
                platform=source_config.platform,
                language=source_config.language,
                locale=source_config.locale,
                timezone=source_config.timezone,
                screen_width=source_config.screen_width,
                screen_height=source_config.screen_height,
                device_pixel_ratio=source_config.device_pixel_ratio,
                color_depth=source_config.color_depth,
                webgl_settings=source_config.webgl_settings,
                hardware_settings=source_config.hardware_settings,
                client_hints=source_config.client_hints,
                privacy_settings=source_config.privacy_settings,
            ).id
        created = self._profiles.create(
            name=new_name,
            profile_path="",
            configuration_id=configuration_id,
            proxy_id=source.proxy_id,
            created_at=now,
            notes=source.notes,
            tags=source.tags,
            geo_auto=source.geo_auto,
            start_url=source.start_url,
            workspace_id=source.workspace_id,
        )
        new_path = self._paths.resolve(created.id)
        self._profiles.update(created.id, profile_path=str(new_path))

        source_path = Path(source.profile_path)
        if source_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_path, new_path, dirs_exist_ok=True)
            # The copy must not share the original's per-profile noise seed.
            try:
                (new_path / ".antidetect-seed").unlink()
            except OSError:
                pass
        # A note on correctness: copying the source *directory* duplicates its
        # browser state (cookies, localStorage, cache). The new profile keeps a
        # completely separate directory, so storage is never shared, while the
        # configuration and proxy references are copied (= the documented
        # duplicate semantics) and remain changeable afterwards.

        finished = self._profiles.get(created.id)
        if finished is not None:
            self._log_info(
                "profiles",
                f"Profile #{source.id:03d} duplicated to "
                f"#{finished.id:03d} '{finished.name}'",
                extra={
                    "profile_id": finished.id,
                    "name": finished.name,
                    "source_id": source.id,
                },
            )
            self._record("act.profile.duplicated", finished, source=source.name)
        return finished  # type: ignore[return-value]

    def is_protected(self, profile_id: int) -> bool:
        """Whether this process holds the live fingerprint layer for the profile."""
        profile = self.get_profile(profile_id)
        check = getattr(self._browsers, "is_protected", None)
        return bool(check is not None and profile.pid and check(profile.pid))

    def sync_geo(self, profile_id: int) -> Profile:
        """Align language/time zone with the exit IP now (when auto-geo is on)."""
        profile = self.get_profile(profile_id)
        return self._prepare_launch(profile) if profile.geo_auto else profile

    def open_url(self, profile_id: int, url: str) -> None:
        """Open ``url`` in a new tab of a running profile."""
        profile = self.get_profile(profile_id)
        if not self._browsers.is_running(Path(profile.profile_path), profile.pid):
            raise ProfileNotRunningError(profile_id)
        opener = getattr(self._browsers, "open_url", None)
        if opener is None or not opener(profile.pid or 0, url):
            raise ChromiumError("This profile cannot open pages from the app.")

    def regenerate_configuration(
        self, profile_id: int, platform: str | None = None
    ) -> BrowserConfiguration:
        """Give the profile a brand-new fingerprint (same geo, optionally another OS)."""
        profile = self.get_profile(profile_id)
        if self._generator is None:
            raise ChromiumError("Fingerprint generation is not available.")
        current = (
            self._configurations.get(profile.configuration_id)
            if profile.configuration_id is not None
            else None
        )
        target = platform or (current.platform if current is not None else None) or host_platform()
        if target not in PLATFORMS:
            raise ValueError(f"Unknown platform {target!r}; expected one of {PLATFORMS}")
        params = self._generator.generate_random(platform=target)
        if current is not None:
            for key in ("language", "locale", "timezone"):
                if getattr(current, key):
                    params[key] = getattr(current, key)
        if is_dedicated(current):
            updated = self._configurations.update(current.id, **params)
        else:
            name = self._unique_config_name(f"{DEDICATED_PREFIX}{profile.name}")
            updated = self._configurations.create(
                name=name, privacy_settings=current.privacy_settings if current is not None else None, **params
            )
            self._profiles.set_configuration(profile.id, updated.id)
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} got a new {target} fingerprint",
            extra={"profile_id": profile_id, "platform": target},
        )
        return updated

    def set_privacy(self, profile_id: int, settings: dict, *, replace: bool = False) -> dict:
        """Change a profile's protection switches (WebRTC mode, canvas / audio noise).

        ``settings`` is merged into what is stored; with ``replace`` it is the whole set, so a
        switch left out goes back to its default. Only differences from the defaults are stored.
        A configuration shared with other profiles is first copied for this one: its switches are
        this profile's own business. Returns the full set now in effect.
        """
        privacy.validate(settings)
        profile = self.get_profile(profile_id)
        if profile.configuration_id is None:
            raise ProfileConfigurationMissingError(profile.id)
        stored = self._configurations.get(profile.configuration_id)
        if stored is None:
            raise BrowserConfigurationNotFoundError(profile.configuration_id)
        merged = dict(settings) if replace else {**privacy.resolve(stored.privacy_settings), **settings}
        wanted = privacy.minimal(merged)
        if privacy.minimal(stored.privacy_settings) == wanted:
            return privacy.resolve(wanted)
        if is_dedicated(stored):
            self._configurations.update(stored.id, privacy_settings=wanted)      # {} puts the defaults back
        else:
            clone = self._configurations.create(
                name=self._unique_config_name(f"{DEDICATED_PREFIX}{profile.name}"),
                user_agent=stored.user_agent, platform=stored.platform, language=stored.language,
                locale=stored.locale, timezone=stored.timezone, screen_width=stored.screen_width,
                screen_height=stored.screen_height, device_pixel_ratio=stored.device_pixel_ratio,
                color_depth=stored.color_depth, webgl_settings=stored.webgl_settings,
                hardware_settings=stored.hardware_settings, client_hints=stored.client_hints,
                privacy_settings=wanted or None,
            )
            self._profiles.set_configuration(profile.id, clone.id)
        self._log_info(
            "profiles", f"Profile #{profile_id:03d} protection switches changed",
            extra={"profile_id": profile_id, "privacy": wanted},
        )
        return privacy.resolve(wanted)

    # ---------------------------------------------------------------- runtime

    def start_profile(self, profile_id: int) -> Profile:
        try:
            started = self._start(profile_id)
        except (ProfileAlreadyRunningError, ProfileNotFoundError):
            raise
        except Exception as exc:
            stored = self._profiles.get(profile_id)
            if stored is not None:
                self._record("act.profile.start_failed", stored, level="ERROR", error=str(exc)[:300])
            raise
        self._record("act.profile.started", started)
        return started

    def _start(self, profile_id: int) -> Profile:
        profile = self.get_profile(profile_id)
        if self._browsers.is_running(Path(profile.profile_path), profile.pid):
            self._log_warn(
                "profiles",
                f"Profile #{profile_id:03d} '{profile.name}' already running",
                extra={"profile_id": profile_id, "pid": profile.pid},
            )
            raise ProfileAlreadyRunningError(profile_id, profile.pid)

        profile = self._prepare_launch(profile)
        configuration = self._configuration_to_launch(profile)
        proxy = self._proxy_to_launch(profile)
        self._enforce_doctor_gate(profile.id, configuration, proxy)
        self._log_info(
            "profiles",
            f"Starting profile #{profile_id:03d} '{profile.name}'",
            extra={
                "profile_id": profile_id,
                "name": profile.name,
                "configuration": configuration.name,
                "proxy_id": proxy.id if proxy else None,
            },
        )

        profile_path = Path(profile.profile_path)
        profile_path.mkdir(parents=True, exist_ok=True)

        try:
            if profile.start_url:
                pid = self._browsers.start(
                    profile_path, configuration, proxy, start_url=profile.start_url
                )
            else:
                pid = self._browsers.start(profile_path, configuration, proxy)
        except Exception:
            self._log_error(
                "profiles",
                f"Profile #{profile_id:03d} '{profile.name}' failed to start",
                extra={"profile_id": profile_id, "name": profile.name},
            )
            raise
        started_at = utcnow()
        self._profiles.update_runtime(
            profile_id,
            status=ProfileStatus.RUNNING,
            pid=pid,
            started_at=started_at,
        )
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} '{profile.name}' is running",
            extra={"profile_id": profile_id, "pid": pid},
        )
        updated = self._profiles.get(profile_id)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
        return updated

    def stop_profile(self, profile_id: int) -> Profile:
        profile = self.get_profile(profile_id)
        self._log_info(
            "profiles",
            f"Stopping profile #{profile_id:03d} '{profile.name}'",
            extra={"profile_id": profile_id, "pid": profile.pid},
        )
        if not self._browsers.is_running(Path(profile.profile_path), profile.pid):
            self._profiles.update_runtime(
                profile_id,
                status=ProfileStatus.STOPPED,
                pid=None,
                stopped_at=utcnow(),
            )
            updated = self._profiles.get(profile_id)
            self._log_info(
                "profiles",
                f"Profile #{profile_id:03d} already stopped",
                extra={"profile_id": profile_id},
            )
            return updated  # type: ignore[return-value]

        self._browsers.stop(Path(profile.profile_path), profile.pid or 0)
        stopped_at = utcnow()
        self._profiles.update_runtime(
            profile_id,
            status=ProfileStatus.STOPPED,
            pid=None,
            stopped_at=stopped_at,
        )
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} '{profile.name}' stopped",
            extra={"profile_id": profile_id},
        )
        self._record("act.profile.stopped", profile)
        updated = self._profiles.get(profile_id)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
        return updated

    def restart_profile(self, profile_id: int) -> Profile:
        profile = self.get_profile(profile_id)
        self._log_info(
            "profiles",
            f"Restarting profile #{profile_id:03d} '{profile.name}'",
            extra={"profile_id": profile_id, "pid": profile.pid},
        )
        if self._browsers.is_running(Path(profile.profile_path), profile.pid):
            self.stop_profile(profile_id)
        return self.start_profile(profile_id)

    # --------------------------------------------------------------- helpers

    def _enforce_doctor_gate(self, profile_id: int, configuration, proxy) -> None:
        """Fail-closed consistency gate: blocks provably-broken launches.

        Warnings are logged and the launch proceeds; blocks raise
        ``ChromiumError`` with a fix for every finding.
        """
        proxy_check = None
        if proxy is not None and self._proxies is not None:
            rows = self._proxies.list_with_latest_check(proxy_ids=[proxy.id])
            proxy_check = rows[0] if rows else None
        google: bool | None = None
        if proxy is not None:
            google = self._google_reachable(proxy)
        report = diagnose(
            configuration,
            binary_major=self._browser_major(),
            proxy_country_code=(
                proxy_check.country_code if proxy_check is not None
                else (proxy.country_code if proxy is not None else None)
            ),
            anonymity=(
                proxy_check.anonymity.value if proxy_check is not None and proxy_check.anonymity else None
            ),
            google_reachable=google,
            has_proxy=proxy is not None,
        )
        for finding in report.warns:
            self._log_warn(
                "profiles",
                f"Profile #{profile_id:03d} doctor warn [{finding.code}]: {finding.message}",
                extra={"profile_id": profile_id, "code": finding.code},
            )
        if not report.ok:
            details = "; ".join(
                f"[{finding.code}] {finding.message} Fix: {finding.fix}"
                for finding in report.blocks
            )
            self._log_error(
                "profiles",
                f"Profile #{profile_id:03d} blocked by doctor gate: {details}",
                extra={"profile_id": profile_id},
            )
            raise ChromiumError(
                f"Profile #{profile_id:03d} failed pre-launch diagnostics "
                f"({len(report.blocks)} blocking issue(s)). "
                f"Run 'app profile doctor {profile_id}' for details. {details}"
            )

    def _browser_major(self) -> int | None:
        probe = getattr(self._browsers, "binary_major", None)
        if probe is None:
            return None
        try:
            return probe()
        except Exception:
            return None

    def _google_reachable(self, proxy) -> bool:
        probe = self._google_probe
        if probe is None:
            from antidetect.infrastructure.proxy.transport import probe_google

            probe = probe_google
        try:
            return bool(probe(proxy, 8.0))
        except Exception:
            return False

    def _configuration_to_launch(self, profile: Profile) -> BrowserConfiguration:
        if profile.configuration_id is None:
            raise ProfileConfigurationMissingError(profile.id)
        configuration = self._configurations.get(profile.configuration_id)
        if configuration is None:
            raise BrowserConfigurationNotFoundError(profile.configuration_id)
        if not isinstance(configuration, BrowserConfiguration):
            return configuration  # pragma: no cover — defensive for stubs
        # Structural validation catches corrupt hand-edited rows before launch.
        validate_draft(
            {
                "user_agent": configuration.user_agent,
                "platform": configuration.platform,
                "screen_width": configuration.screen_width,
                "screen_height": configuration.screen_height,
                "device_pixel_ratio": configuration.device_pixel_ratio,
                "color_depth": configuration.color_depth,
            }
        )
        return configuration

    def _proxy_to_launch(self, profile: Profile):
        if profile.proxy_id is None:
            return None
        if self._proxies is None:
            return None
        proxy = self._proxies.get(profile.proxy_id)
        if proxy is None:
            raise ProxyNotFoundError(profile.proxy_id)
        # A proxy the user bought stays usable even when the (strict) pool check
        # flagged it: the launch-time probe is the real gate.
        if proxy.status is ProxyStatus.DEAD and (proxy.source or "") != "manual":
            raise ProxyNotUsableError(profile.proxy_id, "proxy is DEAD")
        return proxy

    def _proxy_check_for(self, profile: Profile) -> ProxyWithCheck | None:
        if profile.proxy_id is None or self._proxies is None:
            return None
        rows = self._proxies.list_with_latest_check(proxy_ids=[profile.proxy_id])
        return rows[0] if rows else None

    def _resolve_configuration(self, configuration_id: int | None) -> int:
        if configuration_id is not None:
            if self._configurations.get(configuration_id) is None:
                raise BrowserConfigurationNotFoundError(configuration_id)
            return configuration_id
        default = self._configurations.get_default()
        if default is None:
            raise ChromiumError(
                "No browser configurations exist at all. Recreate one with: "
                "app config generate --platform windows"
            )
        return default.id

    def _validate_proxy_id(self, proxy_id: int | None) -> int | None:
        if proxy_id is None:
            return None
        if self._proxies is None or self._proxies.get(proxy_id) is None:
            raise ProxyNotFoundError(proxy_id)
        return proxy_id

    def _reconcile(self, profile: Profile) -> Profile:
        """Synchronize the stored status with the real process when it differs.

        A crash or a manual kill leaves the row marked RUNNING; we detect the
        dead pid and flip back to STOPPED so the CLI always reports truth.
        """
        if profile.status is ProfileStatus.RUNNING:
            pid = profile.pid
            running = self._browsers.is_running(Path(profile.profile_path), pid)
            if not running:
                self._profiles.update_runtime(
                    profile.id,
                    status=ProfileStatus.STOPPED,
                    pid=None,
                    stopped_at=utcnow(),
                )
                self._log_info(
                    "profiles",
                    f"Profile #{profile.id:03d} reconciled to STOPPED (pid {pid} gone)",
                    extra={"profile_id": profile.id, "pid": pid},
                )
                self._record("act.profile.stopped", profile, closed=True)    # the user closed the browser window
                stored = self._profiles.get(profile.id)
                if stored is not None:
                    return stored
        return profile

    def _validate_workspace_id(self, workspace_id: int | None) -> int | None:
        if workspace_id is None:
            return None
        if self._workspaces is None or self._workspaces.get(workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        return workspace_id

    def _canonical_tags(self, tags: list[str] | None) -> list[str] | None:
        """Tag names as the registry spells them (new names are registered on the way)."""
        if tags is None or self._tag_registry is None:
            return tags
        return self._tag_registry.ensure(tags)

    # --------------------------------------------------------------- activity / logging

    def _record(self, kind: str, profile: Profile, **data) -> None:
        if self._activity is not None:
            self._activity.record(kind, profile.name, profile_id=profile.id, **data)

    def _record_raw(self, kind: str, subject: str = "", **data) -> None:
        if self._activity is not None:
            self._activity.record(kind, subject, **data)

    def _log_info(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.info(source, message, extra)

    def _log_warn(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.warn(source, message, extra)

    def _log_error(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.error(source, message, extra)