"""Composition root.

Wires the concrete infrastructure (SQLite, Chromium, proxy pipeline) into the
application layer and hands out fully constructed services. Both the CLI
(``app.cli``) and any future GUI use this same factory, guaranteeing the
business logic never changes between entry points.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.configuration_generator import ConfigurationGenerator
from app.application.configuration_service import ConfigurationService
from app.application.cookie_service import CookieService
from app.application.log_service import LogService
from app.application.profile_path_resolver import ProfilePathResolver
from app.application.profile_service import ProfileService
from app.application.proxy_service import ProxyService
from app.config.settings import AppConfig
from app.infrastructure.chromium.chromium_manager import ChromiumManager
from app.infrastructure.database.connection import Database
from app.infrastructure.database.migrations import run_migrations
from app.infrastructure.database.repositories.browser_configuration_repository import (
    SqliteBrowserConfigurationRepository,
)
from app.infrastructure.database.repositories.log_repository import SqliteLogRepository
from app.infrastructure.database.repositories.profile_repository import (
    SqliteProfileRepository,
)
from app.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from app.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)
from app.infrastructure.database.repositories.settings_repository import (
    SqliteSettingsRepository,
)
from app.infrastructure.proxy import ip_providers as ip_prov
from app.infrastructure.proxy.checker import ProxyChecker
from app.infrastructure.proxy.collector import ProxyCollector
from app.infrastructure.proxy.sources import (
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
    # Every launch starts a clean slate: wipe the previous session's rows so
    # the live Log page only ever shows this run. Past sessions survive export.
    logs.reset()

    manager = ChromiumManager(
        chromium_path=config.chromium_path,
        logs_dir=config.logs_dir,
        log_sink=logs,
        # Test harness only: ANTIDETECT_DISABLE_STEALTH=1 skips CDP injection
        # because stub browser binaries expose no DevTools endpoint.
        enable_stealth=not config.disable_stealth,
    )

    proxy_repo = SqliteProxyRepository(db)

    service = ProfileService(
        profiles=profile_repo,
        configurations=configuration_repo,
        settings=settings_repo,
        browsers=manager,
        path_resolver=ProfilePathResolver(config.profiles_dir),
        proxies=proxy_repo,
        log_sink=logs,
        generator=ConfigurationGenerator(),
    )

    configuration_service = ConfigurationService(
        configurations=configuration_repo,
        generator=ConfigurationGenerator(),
    )
    cookie_service = CookieService(
        profiles=profile_repo,
        browsers=manager,
        export_dir=config.data_dir / "cookie-backups",
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
    )
    proxy_service = ProxyService(
        proxies=proxy_repo,
        checks=proxy_check_repo,
        collector=ProxyCollector(sources),
        checker=checker,
        dead_policy=config.proxy_dead_policy,
        max_failures=config.proxy_max_failures,
        log_sink=logs,
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
    )