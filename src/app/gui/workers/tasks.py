"""Task factories — thin, sync callables that map the GUI onto services.

Every function here returns a ``(progress) -> result`` callable suitable for
:meth:`app.gui.workers.task_runner.TaskRunner.submit`. They are pure Python:
no Qt, no widgets. The GUI thread stays idle while these run on pool threads.

Convention — heavy operations that the spec requires off the UI thread:
profile start / stop / restart, proxy refresh / check / check-all, IP lookup,
cookie import / export and configuration generation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from app.domain.enums.profile_status import ProfileStatus
from app.domain.enums.proxy_status import ProxyStatus
from app.gui.models import EntitySummary
from app.gui.workers.worker import ProgressCallback, TaskFunction

if TYPE_CHECKING:
    from app.di import Container

# ---------------------------------------------------------------------- #
# Reads
# ---------------------------------------------------------------------- #


def summary(factory_container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> EntitySummary:
        profiles = factory_container.profiles.list_profiles()
        proxies = factory_container.proxies.list_proxies()
        configurations = factory_container.configurations.list_configurations()
        return EntitySummary(
            profiles=len(profiles),
            running_profiles=sum(
                1 for p in profiles if p.status is ProfileStatus.RUNNING
            ),
            proxies=len(proxies),
            working_proxies=sum(
                1 for row in proxies if row.proxy.status is ProxyStatus.WORKING
            ),
            configurations=len(configurations),
        )

    return run


def list_profiles(factory_container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.list_profiles()

    return run


def create_profile(
    factory_container: "Container",
    name: str,
    *,
    configuration_id: int | None = None,
    proxy_id: int | None = None,
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.create_profile(
            name, configuration_id=configuration_id, proxy_id=proxy_id
        )

    return run


def update_profile(
    factory_container: "Container",
    profile_id: int,
    *,
    name: str | None = None,
    configuration_id: int | None = None,
    proxy_id: int | None = None,
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.update_profile(
            profile_id,
            name=name,
            configuration_id=configuration_id,
            proxy_id=proxy_id,
        )

    return run


def assign_configuration(
    factory_container: "Container",
    profile_id: int,
    configuration_id: int,
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.assign_configuration(
            profile_id, configuration_id
        )

    return run


def assign_proxy(
    factory_container: "Container",
    profile_id: int,
    proxy_id: int | None,
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.assign_proxy(profile_id, proxy_id)

    return run


def delete_profile(factory_container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        factory_container.profiles.delete_profile(profile_id)
        return None

    return run


def duplicate_profile(
    factory_container: "Container", profile_id: int
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.duplicate_profile(profile_id)

    return run


def delete_configuration(
    factory_container: "Container", configuration_id: int
) -> TaskFunction:
    def run(progress: ProgressCallback):
        factory_container.configurations.delete_configuration(configuration_id)
        return None

    return run


def create_configuration(
    factory_container: "Container", name: str, **params
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.configurations.create_configuration(
            name, **params
        )

    return run


def update_configuration(
    factory_container: "Container", configuration_id: int, **params
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.configurations.update_configuration(
            configuration_id, **params
        )

    return run


def align_configuration_geo(
    factory_container: "Container", configuration_id: int, country_code: str
) -> TaskFunction:
    """Auto-fix a configuration's timezone/locale/language to a country."""

    def run(progress: ProgressCallback):
        return factory_container.configurations.align_configuration_geo(
            configuration_id, country_code
        )

    return run


def list_proxies(factory_container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.proxies.list_proxies()

    return run


def list_configurations(factory_container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.configurations.list_configurations()

    return run


def get_configuration(
    factory_container: "Container", configuration_id: int
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.configurations.get_configuration(configuration_id)

    return run


def list_templates(factory_container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.configurations.list_templates()

    return run

# ---------------------------------------------------------------------- #
# Profiles lifecycle
# ---------------------------------------------------------------------- #


def start_profile(factory_container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.start_profile(profile_id)

    return run


def stop_profile(factory_container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.stop_profile(profile_id)

    return run


def diagnose_profile(
    factory_container: "Container", profile_id: int, *, probe_google: bool = True
) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.diagnose_profile(
            profile_id, probe_google=probe_google
        )

    return run


def restart_profile(factory_container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.profiles.restart_profile(profile_id)

    return run

# ---------------------------------------------------------------------- #
# Proxies
# ---------------------------------------------------------------------- #


def check_proxy(factory_container: "Container", proxy_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.proxies.check_proxy(proxy_id)

    return run


def recheck_proxies(
    factory_container: "Container",
    *,
    workers: int | None = None,
    timeout: float | None = None,
) -> TaskFunction:
    """Re-check the whole pool with a fresh worklist and drop failures.

    Used by the profile-edit dialog's Refresh: the backend re-validates every
    proxy and purges the ones that failed, then the caller re-reads the pool so
    the list always matches what the last check actually proved.
    """

    def run(progress: ProgressCallback) -> object:
        return factory_container.proxies.check_all(
            force=True,
            workers=workers,
            timeout=timeout,
            on_progress=progress,
            purge_failed=True,
        )

    return run


def refresh_proxies(
    factory_container: "Container",
    *,
    collect: bool = True,
    reset: bool = False,
    workers: int | None = None,
    timeout: float | None = None,
    on_proxy: object | None = None,
    stop_event=None,
) -> TaskFunction:
    def run(progress: ProgressCallback) -> object:
        return factory_container.proxies.refresh(
            collect=collect,
            reset=reset,
            force=True,
            workers=workers,
            timeout=timeout,
            on_progress=progress,
            on_proxy=on_proxy,
            stop_event=stop_event,
            purge_failed=True,
        )

    return run


def lookup_ip(factory_container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.proxies.lookup_ip()

    return run

# ---------------------------------------------------------------------- #
# Cookies
# ---------------------------------------------------------------------- #


def export_cookies(
    factory_container: "Container", profile_id: int, output: Path | None = None
) -> TaskFunction:
    def run(progress: ProgressCallback) -> object:
        return factory_container.cookies.export(profile_id, output)

    return run


def import_cookies(
    factory_container: "Container", profile_id: int, source: Path
) -> TaskFunction:
    def run(progress: ProgressCallback) -> object:
        return factory_container.cookies.import_(profile_id, source)

    return run

# ---------------------------------------------------------------------- #
# Configurations
# ---------------------------------------------------------------------- #


def generate_configuration(
    factory_container: "Container",
    *,
    name: str | None = None,
    platform: str | None = None,
) -> TaskFunction:
    def run(progress: ProgressCallback) -> object:
        return factory_container.configurations.generate_configuration(
            name=name, platform=platform
        )

    return run


def generate_configuration_with_size(
    factory_container: "Container",
    *,
    platform: str | None = None,
    template: str | None = None,
    screen_width: int | None = None,
    screen_height: int | None = None,
) -> TaskFunction:
    def run(progress: ProgressCallback) -> object:
        config = factory_container.configurations.generate_configuration(
            platform=platform, template=template
        )
        if screen_width is not None and screen_height is not None:
            config = factory_container.configurations.update_configuration(
                config.id,
                screen_width=screen_width,
                screen_height=screen_height,
            )
        return config

    return run


def generate_configuration_from_template(
    factory_container: "Container", template: str, *, name: str | None = None
) -> TaskFunction:
    def run(progress: ProgressCallback) -> object:
        return factory_container.configurations.generate_configuration(
            name=name, template=template
        )

    return run

# ---------------------------------------------------------------------- #
# Logs
# ---------------------------------------------------------------------- #


def list_logs(factory_container: "Container", after_id: int = 0) -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.logs.list_logs(after_id=after_id)

    return run


def export_logs(factory_container: "Container", path: Path) -> TaskFunction:
    def run(progress: ProgressCallback):
        factory_container.logs.export(path)
        return path

    return run


def clear_logs(factory_container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return factory_container.logs.clear()

    return run