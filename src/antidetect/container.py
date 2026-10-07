"""Composition root.

Wires the concrete infrastructure (SQLite, Chromium, proxy pipeline) into the
application layer and hands out fully constructed services. Both the CLI
(``antidetect.cli``) and any future GUI use this same factory, guaranteeing the
business logic never changes between entry points.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from antidetect.application.fingerprint.generator import ConfigurationGenerator
from antidetect.application.activity_service import ActivityService
from antidetect.application.configuration_service import ConfigurationService
from antidetect.application.cookie_service import CookieService
from antidetect.application.log_service import LogService
from antidetect.application.profile_path_resolver import ProfilePathResolver
from antidetect.application.profile_service import ProfileService
from antidetect.application.proxy_service import ProxyService
from antidetect.application.tag_service import TagService
from antidetect.application.workspace_service import WorkspaceService
from antidetect.application.browser_service import BrowserService
from antidetect.application.bulk_service import BulkService
from antidetect.application.transfer_service import TransferService
from antidetect.config import AppConfig
from antidetect.infrastructure.chromium.chromium_manager import ChromiumManager
from antidetect.infrastructure.chromium.downloader import ManagedBrowsers
from antidetect.infrastructure.database.connection import Database
from antidetect.infrastructure.database.migrations import run_migrations
from antidetect.infrastructure.database.repositories.activity_repository import SqliteActivityRepository
from antidetect.infrastructure.database.repositories.browser_configuration_repository import (
    SqliteBrowserConfigurationRepository,
)
from antidetect.infrastructure.database.repositories.log_repository import SqliteLogRepository
from antidetect.infrastructure.database.repositories.profile_repository import (
    SqliteProfileRepository,
)
from antidetect.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from antidetect.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from antidetect.infrastructure.database.repositories.settings_repository import (
    SqliteSettingsRepository,
)
from antidetect.infrastructure.database.repositories.tag_repository import SqliteTagRepository
from antidetect.infrastructure.database.repositories.workspace_repository import SqliteWorkspaceRepository
from antidetect.infrastructure.proxy import ip_providers as ip_prov
from antidetect.infrastructure.proxy.checker import ProxyChecker
from antidetect.infrastructure.proxy.collector import ProxyCollector
from antidetect.infrastructure.proxy.sources import (
    build_sources,
    default_sources,
)


@dataclass
class Container:
    config: AppConfig
    db: Database
    profiles: ProfileService
    proxies: ProxyService
    configurations: ConfigurationService
    cookies: CookieService
    settings: SqliteSettingsRepository
    logs: LogService
    browser: ChromiumManager
    tags: TagService
    workspaces: WorkspaceService
    activity: ActivityService
    bulk: BulkService
    transfer: TransferService
    browsers: BrowserService

    #: settings key holding a browser location the user picked in the GUI
    BROWSER_PATH_KEY = "browser.path"

    def set_browser_path(self, path: str | None) -> None:
        """Persist and apply the browser location (``None``/empty = auto)."""
        value = (path or "").strip()
        self.settings.set(self.BROWSER_PATH_KEY, value)
        self.browser.set_chromium_path(Path(value) if value else None)

    def use_downloaded_browser(self) -> bool:
        """Let the Chrome the app downloaded run the profiles: a browser path chosen earlier would still
        win, so it is cleared. Returns whether there was one."""
        stored = self.settings.get(self.BROWSER_PATH_KEY)
        if stored is None or not (stored.value or "").strip():
            return False
        self.set_browser_path(None)
        return True

    def browser_info(self) -> tuple[Path | None, str | None]:
        """(path, full version) of the browser that will run profiles."""
        return self.browser.resolved_binary(), self.browser.binary_full_version()

    def close(self) -> None:
        self.logs.close()
        self.db.close()


def bootstrap(config: AppConfig | None = None) -> Container:
    config = config or AppConfig.from_env()
    config.data_dir.mkdir(parents=True, exist_ok=True)

    db = Database(config.database_path)
    run_migrations(db)

    profile_repo = SqliteProfileRepository(db)
    configuration_repo = SqliteBrowserConfigurationRepository(db)
    settings_repo = SqliteSettingsRepository(db)
    log_repo = SqliteLogRepository(db)

    logs = LogService(log_repo)
    activity = ActivityService(SqliteActivityRepository(db), settings_repo)
    tag_repo = SqliteTagRepository(db)
    workspace_repo = SqliteWorkspaceRepository(db)
    tag_service = TagService(tag_repo, profile_repo, activity=activity, log_sink=logs)
    workspace_service = WorkspaceService(workspace_repo, profile_repo, activity=activity, log_sink=logs)
    # Stored UI language wins before the first log row, so even the
    # "session started" entry is written in the user's language.
    try:
        from antidetect.i18n import normalize as _normalize_lang
        from antidetect.i18n import set_language as _set_language

        _stored = settings_repo.get("gui.language")
        _set_language(
            _normalize_lang(_stored.value if _stored is not None else None)
        )
    except Exception:
        pass
    # Every launch starts a clean slate: wipe the previous session's rows so
    # the live Log page only ever shows this run. Past sessions survive export.
    logs.reset()

    stored_path = settings_repo.get(Container.BROWSER_PATH_KEY)
    chosen = config.chromium_path
    if chosen is None and stored_path is not None and (stored_path.value or "").strip():
        candidate = Path(stored_path.value.strip()).expanduser()
        chosen = candidate if candidate.is_file() else None

    managed_browsers = ManagedBrowsers(config.data_dir / "browsers")
    manager = ChromiumManager(
        chromium_path=chosen,
        logs_dir=config.logs_dir,
        log_sink=logs,
        managed_browsers=managed_browsers,
        # Test harness only: ANTIDETECT_DISABLE_STEALTH=1 skips CDP injection
        # because stub browser binaries expose no DevTools endpoint.
        enable_stealth=not config.disable_stealth,
    )

    proxy_repo = SqliteProxyRepository(db)

    def _direct_country() -> str | None:
        """Country of this machine's own public IP (for auto-geo without a proxy)."""
        ip = ip_prov.fetch_direct_ip(timeout=6.0)
        if not ip:
            return None
        _, code = ip_prov.resolve_country_consensus(ip, None, timeout=6.0)
        return code

    generator = ConfigurationGenerator(browser_version=manager.binary_full_version)
    service = ProfileService(
        profiles=profile_repo,
        configurations=configuration_repo,
        settings=settings_repo,
        browsers=manager,
        path_resolver=ProfilePathResolver(config.profiles_dir),
        proxies=proxy_repo,
        log_sink=logs,
        generator=generator,
        geo_lookup=_direct_country,
        activity=activity,
        tag_registry=tag_service,
        workspaces=workspace_repo,
    )

    configuration_service = ConfigurationService(
        configurations=configuration_repo,
        generator=generator,
        log_sink=logs,
    )
    cookie_service = CookieService(
        profiles=profile_repo,
        browsers=manager,
        export_dir=config.data_dir / "cookie-backups",
        log_sink=logs,
    )

    proxy_check_repo = SqliteProxyCheckRepository(db)
    if config.proxy_sources:
        sources = build_sources(list(config.proxy_sources))
    else:
        sources = default_sources()
    checker = ProxyChecker(
        timeout=config.proxy_check_timeout,
        workers=config.proxy_workers,
        max_failures=config.proxy_max_failures,
        # Country labels are cross-checked across ipwho.is + ipinfo.io + ip-api
        # and only accepted on majority agreement: a single (stale) database
        # cannot label e.g. a Swedish exit as Hong Kong anymore.
        geo_reviewer=ip_prov.resolve_country_consensus,
        # Resolve the real IP lazily on the first check, not at startup:
        # bootstrap() must never block on the network (GUI cold start, CLI
        # latency when offline). ensure_direct_ip() covers the first check.
        resolve_direct_ip=False,
        # Strict pool quality: country-less proxies break geo matching
        # (autoconfig, doctor gate) and sluggish ones stall browsing,
        # so both fail the check instead of entering the pool as WORKING.
        require_country=True,
        max_latency_ms=4000,
    )
    proxy_service = ProxyService(
        proxies=proxy_repo,
        checks=proxy_check_repo,
        collector=ProxyCollector(sources),
        checker=checker,
        dead_policy=config.proxy_dead_policy,
        max_failures=config.proxy_max_failures,
        log_sink=logs,
        activity=activity,
    )
    return Container(
        config=config,
        db=db,
        profiles=service,
        proxies=proxy_service,
        configurations=configuration_service,
        cookies=cookie_service,
        settings=settings_repo,
        logs=logs,
        browser=manager,
        tags=tag_service,
        workspaces=workspace_service,
        activity=activity,
        bulk=BulkService(service, proxy_service),
        transfer=TransferService(service, configuration_service, proxy_service, workspace_service, activity=activity),
        browsers=BrowserService(manager, managed_browsers, log_sink=logs, activity=activity),
    )