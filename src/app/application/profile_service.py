from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.application.configuration_generator import (
    PLATFORMS,
    ConfigurationGenerator,
    country_defaults,
    ua_chrome_major,
    validate_draft,
)
from app.application.profile_doctor import TIMEZONE_COUNTRY, locale_country
from app.application.ports import (
    BrowserConfigurationRepository,
    BrowserManager,
    ProfileRepository,
    ProxyRepository,
    SettingsRepository,
)
from app.application.profile_path_resolver import ProfilePathResolver
from app.domain.enums.profile_status import ProfileStatus
from app.domain.enums.proxy_status import ProxyStatus
from app.application.profile_doctor import DoctorReport, diagnose
from app.domain.errors import (
    BrowserConfigurationNotFoundError,
    ChromiumError,
    ProfileAlreadyExistsError,
    ProfileAlreadyRunningError,
    ProfileConfigurationMissingError,
    ProfileNotFoundError,
    ProfileNotRunningError,
    ProxyNotFoundError,
    ProxyNotUsableError,
)
from app.domain.models.browser_configuration import BrowserConfiguration
from app.domain.models.profile import Profile
from app.domain.models.proxy import ProxyWithCheck

if TYPE_CHECKING:
    from app.application.ports import LogSink


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _legacy_majors() -> tuple[int, ...]:
    from app.application.configuration_generator import LEGACY_CHROME_MAJORS

    return LEGACY_CHROME_MAJORS


def _geo_matches(configuration: BrowserConfiguration, country: str) -> bool:
    """True when a configuration's locale+timezone already fit ``country``."""
    code = (country or "").upper()
    if locale_country(configuration.locale) != code:
        return False
    return TIMEZONE_COUNTRY.get(configuration.timezone or "") == code


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
    the abstract ports defined in :mod:`app.application.ports`.
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
        self._paths.ensure_root()

    # ------------------------------------------------------------------ reads

    def get_profile(self, profile_id: int) -> Profile:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)
        return self._reconcile(profile)

    def list_profiles(self) -> list[Profile]:
        return [self._reconcile(p) for p in self._profiles.list()]

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
    ) -> Profile:
        name = name.strip()
        if not name:
            raise ValueError("Profile name must not be empty.")
        if self._profiles.find_by_name(name) is not None:
            raise ProfileAlreadyExistsError(name)

        configuration_id = self._resolve_configuration(configuration_id)
        proxy_id = self._validate_proxy_id(proxy_id)
        now = utcnow()

        # Two-step insert: the on-disk directory name depends on the row id.
        created = self._profiles.create(
            name=name,
            profile_path="",  # placeholder, filled below
            configuration_id=configuration_id,
            proxy_id=proxy_id,
            created_at=now,
        )
        profile_path = str(self._paths.resolve(created.id))
        self._profiles.update(created.id, profile_path=profile_path)
        if auto_config and proxy_id is not None:
            self._maybe_auto_config(created.id)
        return self._profiles.get(created.id)  # type: ignore[return-value]

    def update_profile(
        self,
        profile_id: int,
        name: str | None = None,
        configuration_id: int | None = None,
        proxy_id: int | None = None,
        auto_config: bool = True,
    ) -> Profile:
        profile = self.get_profile(profile_id)

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

        self._profiles.update(
            profile_id,
            name=name,
            configuration_id=configuration_id,
            proxy_id=proxy_id,
        )
        updated = self._profiles.get(profile_id)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
        if auto_config and configuration_id is None and updated.proxy_id is not None:
            # A proxy (re)assignment without an explicit configuration means
            # "match the fingerprint to the proxy" — same as assign_proxy.
            self._maybe_auto_config(profile_id)
            refreshed = self._profiles.get(profile_id)
            if refreshed is not None:
                return refreshed
        return updated

    def assign_configuration(self, profile_id: int, configuration_id: int) -> Profile:
        """Assign or change the profile's browser configuration."""
        self.get_profile(profile_id)
        if self._configurations.get(configuration_id) is None:
            raise BrowserConfigurationNotFoundError(configuration_id)
        updated = self._profiles.set_configuration(profile_id, configuration_id)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
        return updated

    def remove_configuration(self, profile_id: int) -> Profile:
        """Detach the profile's configuration (start() then requires one)."""
        self.get_profile(profile_id)
        updated = self._profiles.set_configuration(profile_id, None)
        if updated is None:
            raise ProfileNotFoundError(profile_id)
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
        if auto_config and proxy_id is not None:
            self._maybe_auto_config(profile_id)
            refreshed = self._profiles.get(profile_id)
            if refreshed is not None:
                return refreshed
        return updated

    def _maybe_auto_config(self, profile_id: int) -> None:
        """Align the profile's configuration with its proxy exit country."""
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
        current = None
        if profile.configuration_id is not None:
            current = self._configurations.get(profile.configuration_id)
        if current is not None and _geo_matches(current, country):
            self._log_info(
                "profiles",
                f"Profile #{profile_id:03d} configuration {current.name!r} already matches {country}",
                extra={"profile_id": profile_id, "country": country},
            )
            return
        reused = self._find_geo_configuration(country)
        if reused is not None:
            self._profiles.set_configuration(profile_id, reused.id)
            self._log_info(
                "profiles",
                f"Profile #{profile_id:03d} reused configuration {reused.name!r} for {country}",
                extra={"profile_id": profile_id, "configuration_id": reused.id, "country": country},
            )
            return
        if self._generator is None or country_defaults(country) is None:
            self._log_warn(
                "profiles",
                f"Profile #{profile_id:03d} has no matching configuration for {country} "
                "and none can be generated — configuration untouched",
                extra={"profile_id": profile_id, "country": country},
            )
            return
        platform = (
            current.platform
            if current is not None and current.platform in PLATFORMS
            else "windows"
        )
        params = self._generator.generate_for_country(country, platform=platform)
        name = self._unique_auto_name(country, platform)
        created = self._configurations.create(name=name, **params)
        self._profiles.set_configuration(profile_id, created.id)
        self._log_info(
            "profiles",
            f"Profile #{profile_id:03d} generated configuration {name!r} for {country}",
            extra={"profile_id": profile_id, "configuration_id": created.id, "country": country},
        )

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

    def _find_geo_configuration(self, country: str):
        """An existing configuration whose geo already fits ``country``."""
        for candidate in self._configurations.list():
            if not _geo_matches(candidate, country):
                continue
            if ua_chrome_major(candidate.user_agent or "") in _legacy_majors():
                continue
            return candidate
        return None

    def _unique_auto_name(self, country: str, platform: str) -> str:
        base = f"auto-{country.lower()}-{platform}"
        name = base
        index = 2
        while self._configurations.find_by_name(name) is not None:
            name = f"{base}-{index}"
            index += 1
        return name

    def remove_proxy(self, profile_id: int) -> Profile:
        return self.assign_proxy(profile_id, None)

    def delete_profile(self, profile_id: int) -> None:
        profile = self.get_profile(profile_id)
        if profile.status is ProfileStatus.RUNNING:
            self.stop_profile(profile_id)

        profile_path = Path(profile.profile_path)
        if profile_path.exists():
            shutil.rmtree(profile_path, ignore_errors=True)
        self._profiles.delete(profile_id)

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
        created = self._profiles.create(
            name=new_name,
            profile_path="",
            configuration_id=source.configuration_id,
            proxy_id=source.proxy_id,
            created_at=now,
        )
        new_path = self._paths.resolve(created.id)
        self._profiles.update(created.id, profile_path=str(new_path))

        source_path = Path(source.profile_path)
        if source_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_path, new_path, dirs_exist_ok=True)
        # A note on correctness: copying the source *directory* duplicates its
        # browser state (cookies, localStorage, cache). The new profile keeps a
        # completely separate directory, so storage is never shared, while the
        # configuration and proxy references are copied (= the documented
        # duplicate semantics) and remain changeable afterwards.

        return self._profiles.get(created.id)  # type: ignore[return-value]

    # ---------------------------------------------------------------- runtime

    def start_profile(self, profile_id: int) -> Profile:
        profile = self.get_profile(profile_id)
        if self._browsers.is_running(Path(profile.profile_path), profile.pid):
            self._log_warn(
                "profiles",
                f"Profile #{profile_id:03d} '{profile.name}' already running",
                extra={"profile_id": profile_id, "pid": profile.pid},
            )
            raise ProfileAlreadyRunningError(profile_id, profile.pid)

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
            from app.infrastructure.proxy.transport import probe_google

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
        if proxy.status is ProxyStatus.DEAD:
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
                stored = self._profiles.get(profile.id)
                if stored is not None:
                    return stored
        return profile

    # --------------------------------------------------------------- logging

    def _log_info(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.info(source, message, extra)

    def _log_warn(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.warn(source, message, extra)

    def _log_error(self, source: str, message: str, extra: dict | None = None) -> None:
        if self._log is not None:
            self._log.error(source, message, extra)