"""Task factories — thin, sync callables that map the GUI onto services.

Every function returns a ``(progress) -> result`` callable for
:meth:`antidetect.gui.workers.runner.TaskRunner.submit`. They are plain Python:
no Qt, no widgets. The UI thread stays idle while these run on pool threads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from antidetect.application.cookie_service import count_cookies
from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.errors import ProfileNotFoundError
from antidetect.gui.models import ProfileRow, ProxyRow
from antidetect.gui.models.rows import browser_label, short_gpu
from antidetect.gui.models.specs import ProfileSpec
from antidetect.gui.workers.runner import ProgressCallback, TaskFunction

if TYPE_CHECKING:
    from antidetect.container import Container


# ------------------------------------------------------------------ reads


def build_profile_rows(container: "Container", *, trashed: bool = False) -> list[ProfileRow]:
    """The rows of the profiles table (``trashed``: the rows of the trash instead)."""
    profiles = container.profiles.list_trashed_profiles() if trashed else container.profiles.list_profiles()
    configs = {c.id: c for c in container.configurations.list_configurations()}
    # Only the proxies profiles actually use: the pool can hold tens of thousands of free ones.
    used = sorted({p.proxy_id for p in profiles if p.proxy_id is not None})
    proxies = {row.proxy.id: row for row in container.proxies.list_proxies(ids=used)}
    rows: list[ProfileRow] = []
    for profile in profiles:
        config = configs.get(profile.configuration_id) if profile.configuration_id else None
        proxy_row = proxies.get(profile.proxy_id) if profile.proxy_id else None
        proxy = proxy_row.proxy if proxy_row is not None else None
        hardware = (config.hardware_settings or {}) if config is not None else {}
        screen = (
            f"{config.screen_width}×{config.screen_height}"
            if config is not None and config.screen_width and config.screen_height
            else None
        )
        rows.append(
            ProfileRow(
                id=profile.id,
                name=profile.name,
                running=profile.status.value == "RUNNING",
                pid=profile.pid,
                notes=profile.notes,
                tags=tuple(profile.tags),
                platform=config.platform if config is not None else None,
                browser=browser_label(config.user_agent if config is not None else None),
                user_agent=config.user_agent if config is not None else None,
                timezone=config.timezone if config is not None else None,
                locale=config.locale if config is not None else None,
                language=config.language if config is not None else None,
                screen=screen,
                gpu=short_gpu(((config.webgl_settings or {}).get("renderer")) if config is not None else None),
                cores=hardware.get("cores"),
                memory_gb=hardware.get("memory_gb"),
                proxy_id=profile.proxy_id,
                proxy_endpoint=proxy.host_port if proxy is not None else None,
                proxy_protocol=proxy.protocol.value if proxy is not None else None,
                proxy_country_code=(proxy_row.country_code or proxy.country_code) if proxy_row is not None else None,
                proxy_country=(proxy_row.country or proxy.country) if proxy_row is not None else None,
                proxy_latency=proxy_row.latency_ms if proxy_row is not None else None,
                last_started_at=profile.last_started_at,
                geo_auto=profile.geo_auto,
                start_url=profile.start_url,
                configuration_id=profile.configuration_id,
                profile_path=profile.profile_path,
                proxy_free=proxy is not None and (proxy.source or "") != "manual",
                created_at=profile.created_at,
                cookie_count=count_cookies(profile.profile_path),
                proxy_status=proxy.status.value if proxy is not None else None,
                proxy_username=proxy.username if proxy is not None else None,
                proxy_checked_at=(proxy_row.checked_at or proxy.last_checked_at) if proxy_row is not None else None,
                workspace_id=profile.workspace_id,
                updated_at=profile.updated_at,
                last_stopped_at=profile.last_stopped_at,
                deleted_at=profile.deleted_at,
            )
        )
    return rows


def list_profile_rows(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> list[ProfileRow]:
        return build_profile_rows(container)

    return run


@dataclass(frozen=True)
class ProxyListing:
    """What the proxies page shows plus the counts of the list."""

    rows: list[ProxyRow]
    total: int
    working: int


def list_proxies(container: "Container") -> ProxyListing:
    """Every stored proxy as a display row, with the profiles that use it."""
    users: dict[int, list[str]] = {}
    for profile in container.profiles.list_profiles():
        if profile.proxy_id is not None:
            users.setdefault(profile.proxy_id, []).append(profile.name)
    rows: list[ProxyRow] = []
    working = 0
    for row in container.proxies.list_proxies(sort="id"):
        proxy = row.proxy
        working += proxy.status.value == "WORKING"
        rows.append(
            ProxyRow(
                id=proxy.id,
                protocol=proxy.protocol.value,
                host=proxy.host,
                port=proxy.port,
                username=proxy.username,
                country_code=row.country_code or proxy.country_code,
                country=row.country or proxy.country,
                latency_ms=row.latency_ms,
                status=proxy.status.value,
                anonymity=row.anonymity.value if row.anonymity is not None else None,
                source=proxy.source,
                used_by=tuple(users.get(proxy.id, ())),
                checked_at=row.checked_at,
            )
        )
    return ProxyListing(rows=rows, total=len(rows), working=working)


def build_proxy_rows(container: "Container") -> list[ProxyRow]:
    return list_proxies(container).rows


def list_proxy_rows(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> ProxyListing:
        return list_proxies(container)

    return run


def running_ids(container: "Container") -> TaskFunction:
    """Ids of the profiles that are really running (also heals rows whose browser died)."""

    def run(progress: ProgressCallback) -> frozenset:
        return frozenset(p.id for p in container.profiles.list_profiles() if p.status.value == "RUNNING")

    return run


def browser_info(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.browser_info()

    return run


def browser_latest(container: "Container") -> TaskFunction:
    """Ask Google which Chrome is current (network)."""

    def run(progress: ProgressCallback):
        return container.browsers.latest()

    return run


def browser_download(container: "Container", release, cancel) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.browsers.download(release, progress, cancel)

    return run


def browser_install(container: "Container", release, archive) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.browsers.install(release, archive)

    return run


# ------------------------------------------------------------- profiles


def _protocol(name: str) -> ProxyProtocol | None:
    try:
        return ProxyProtocol[(name or "HTTP").upper()]
    except KeyError:
        return None


def _import_proxy(container: "Container", spec: ProfileSpec) -> int | None:
    """Add a pasted proxy to the list (database only, no network) and return its id."""
    text = (spec.proxy_text or "").strip()
    if not text:
        return spec.proxy_id
    summary = container.proxies.import_text(text, _protocol(spec.proxy_protocol))
    if not summary.ids:
        raise ValueError("Couldn't read this proxy.")
    return summary.ids[0]


def _measure_proxy(container: "Container", proxy_id: int) -> None:
    """Check a proxy so its country is known (best effort: the country decides time zone and language)."""
    try:
        container.proxies.check_proxy(proxy_id)
    except Exception:
        pass


def _resolve_proxy(container: "Container", spec: ProfileSpec) -> int | None:
    """Add + check a pasted proxy and return its id."""
    proxy_id = _import_proxy(container, spec)
    if proxy_id is not None and (spec.proxy_text or "").strip():
        _measure_proxy(container, proxy_id)
    return proxy_id


def create_profile(container: "Container", spec: ProfileSpec) -> TaskFunction:
    """Create the profile. Database work only, so it is done in a few milliseconds.

    Everything that needs the network (measuring a pasted proxy, finding the exit country,
    launching) is :func:`settle_profile`, which the page runs afterwards in the background —
    the new row is on screen right away instead of after the slowest lookup.
    """

    def run(progress: ProgressCallback):
        proxy_id = _import_proxy(container, spec)
        # A pasted proxy has no country yet; settle_profile aligns the geo once it is measured.
        pasted = bool((spec.proxy_text or "").strip())
        return container.profiles.create_profile(
            spec.name,
            proxy_id=proxy_id,
            auto_config=spec.geo_auto and not pasted,
            platform=spec.platform,
            notes=spec.notes,
            tags=spec.tags,
            geo_auto=spec.geo_auto,
            start_url=spec.start_url,
            workspace_id=spec.workspace_id,
            privacy_settings=spec.privacy or None,
        )

    return run


def needs_settling(spec: ProfileSpec, *, start: bool) -> bool:
    """Whether a just-created profile still has network work to do.

    A saved proxy was already measured, so a geo-matched fingerprint was built from the
    stored country by :func:`create_profile`; what is left is a pasted proxy, an own-IP
    country lookup (no proxy) or a launch.
    """
    return start or bool((spec.proxy_text or "").strip()) or (spec.geo_auto and spec.proxy_id is None)


def settle_profile(container: "Container", profile_id: int, *, start: bool = False) -> TaskFunction:
    """The slow half of creation: measure a not-yet-checked proxy, align geo, optionally launch."""

    def run(progress: ProgressCallback):
        service = container.profiles
        profile = service.get_profile(profile_id)
        if profile.proxy_id is not None:
            rows = container.proxies.list_proxies(ids=[profile.proxy_id])
            if rows and rows[0].checked_at is None:
                _measure_proxy(container, profile.proxy_id)
        # A launch aligns the geo itself, right before the browser starts.
        return service.start_profile(profile_id) if start else service.sync_geo(profile_id)

    return run


def update_profile(container: "Container", profile_id: int, spec: ProfileSpec, current: ProfileRow) -> TaskFunction:
    def run(progress: ProgressCallback):
        service = container.profiles
        service.update_profile(
            profile_id,
            name=spec.name if spec.name != current.name else None,
            notes=spec.notes,
            tags=spec.tags,
            geo_auto=spec.geo_auto,
            start_url=spec.start_url,
            auto_config=False,
        )
        if spec.workspace_id != current.workspace_id:
            container.workspaces.move_profiles([profile_id], spec.workspace_id)
        wanted_proxy = _resolve_proxy(container, spec)
        if wanted_proxy != current.proxy_id:
            service.assign_proxy(profile_id, wanted_proxy, auto_config=spec.geo_auto)
        if spec.regenerate or (spec.platform and spec.platform != current.platform):
            service.regenerate_configuration(profile_id, spec.platform)
        if spec.fingerprint:
            profile = service.get_profile(profile_id)
            if profile.configuration_id is not None:
                container.configurations.update_configuration(profile.configuration_id, **spec.fingerprint)
        if spec.privacy is not None:
            service.set_privacy(profile_id, spec.privacy, replace=True)       # {} puts the defaults back
        if spec.geo_auto:
            service.sync_geo(profile_id)
        return service.get_profile(profile_id)

    return run


def bulk_create(container: "Container", request) -> TaskFunction:
    """Create the profiles of a bulk request: database work only, the rows are on screen in moments."""

    def run(progress: ProgressCallback):
        return container.bulk.create(request, on_progress=progress)

    return run


def bulk_settle(container: "Container", profile_ids: list[int]) -> TaskFunction:
    """The slow half of a bulk creation: measure the new proxies together, then align every profile's geo."""

    def run(progress: ProgressCallback):
        return container.bulk.settle(profile_ids, on_progress=progress)

    return run


def export_profile(container: "Container", profile_id: int, destination: Path, include_proxy: bool) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.transfer.export_profile(profile_id, destination, include_proxy=include_proxy, on_progress=progress)

    return run


def import_profile(container: "Container", source: Path) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.transfer.import_profile(source, on_progress=progress)

    return run


def trash_profiles(container: "Container", ids: list[int]) -> TaskFunction:
    """Move profiles to the trash (a running one is stopped first); returns the ids that went."""

    def run(progress: ProgressCallback) -> list[int]:
        moved: list[int] = []
        for index, profile_id in enumerate(ids, start=1):
            try:
                container.profiles.trash_profile(profile_id)
                moved.append(profile_id)
            except ProfileNotFoundError:                 # a script already removed it: carry on with the rest
                pass
            progress(index, len(ids))
        return moved

    return run


def edit_profile_fields(container: "Container", profile_id: int, *, name: str | None = None,
                        notes: str | None = None, tags: list[str] | None = None,
                        start_url: str | None = None, workspace: tuple[int | None] | None = None) -> TaskFunction:
    """What the profile drawer edits in place: name, notes, tags, start page, workspace.

    ``workspace`` is ``(id,)`` or ``(None,)`` to take the profile out of its workspace; ``None`` leaves it.
    """

    def run(progress: ProgressCallback):
        profile = container.profiles.update_profile(
            profile_id, name=name, notes=notes, tags=tags, start_url=start_url, auto_config=False,
        )
        if workspace is not None:
            container.workspaces.move_profiles([profile_id], workspace[0])
        return profile

    return run


# ----------------------------------------------------------------------- trash


def list_trash_rows(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> list[ProfileRow]:
        return build_profile_rows(container, trashed=True)

    return run


def restore_profiles(container: "Container", ids: list[int]) -> TaskFunction:
    def run(progress: ProgressCallback) -> list[str]:
        names: list[str] = []
        for index, profile_id in enumerate(ids, start=1):
            try:
                names.append(container.profiles.restore_profile(profile_id).name)
            except ProfileNotFoundError:
                pass
            progress(index, len(ids))
        return names

    return run


def purge_profiles(container: "Container", ids: list[int]) -> TaskFunction:
    """Delete profiles for good (folders included)."""

    def run(progress: ProgressCallback) -> int:
        removed = 0
        for index, profile_id in enumerate(ids, start=1):
            try:
                container.profiles.delete_profile(profile_id)
                removed += 1
            except ProfileNotFoundError:
                pass
            progress(index, len(ids))
        return removed

    return run


def empty_trash(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> int:
        return container.profiles.empty_trash()

    return run


def purge_expired_trash(container: "Container") -> TaskFunction:
    """Start-up housekeeping: profiles that stayed in the trash longer than the retention period go for good."""

    def run(progress: ProgressCallback) -> int:
        return container.profiles.purge_expired()

    return run


def trash_retention(container: "Container", days: int | None = None) -> TaskFunction:
    """Read (``days=None``) or set how many days a profile stays in the trash (0 = forever)."""

    def run(progress: ProgressCallback) -> int:
        if days is not None:
            container.profiles.set_trash_retention_days(days)
        return container.profiles.trash_retention_days()

    return run


# --------------------------------------------------------- tags and workspaces


@dataclass(frozen=True)
class CatalogSnapshot:
    """Everything the sidebar and the pickers need about tags, workspaces, the trash and the feed."""

    tags: tuple[tuple[int, str, int, int], ...]            # (id, name, colour slot, profiles)
    workspaces: tuple[tuple[int, str, int, int], ...]
    unassigned: int                                         # profiles in no workspace
    trash: int
    unseen: int                                             # activity entries nobody looked at yet
    unseen_errors: int = 0                                  # ...of which failures


def load_catalog(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> CatalogSnapshot:
        return CatalogSnapshot(
            tags=tuple((i.tag.id, i.tag.name, i.tag.color, i.count) for i in container.tags.list_tags()),
            workspaces=tuple((i.workspace.id, i.workspace.name, i.workspace.color, i.count)
                             for i in container.workspaces.list_workspaces()),
            unassigned=container.workspaces.unassigned_count(),
            trash=container.profiles.count_trashed(),
            unseen=container.activity.unseen(),
            unseen_errors=container.activity.unseen_errors(),
        )

    return run


def create_tag(container: "Container", name: str, color: int | None = None) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.tags.create_tag(name, color)

    return run


def rename_tag(container: "Container", tag_id: int, name: str) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.tags.rename_tag(tag_id, name)

    return run


def recolor_tag(container: "Container", tag_id: int, color: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.tags.set_color(tag_id, color)

    return run


def delete_tag(container: "Container", tag_id: int) -> TaskFunction:
    def run(progress: ProgressCallback) -> int:
        return container.tags.delete_tag(tag_id)

    return run


def assign_tags(container: "Container", ids: list[int], add: list[str], remove: list[str]) -> TaskFunction:
    def run(progress: ProgressCallback) -> int:
        return container.tags.assign(ids, add=add, remove=remove)

    return run


def create_workspace(container: "Container", name: str, color: int | None = None) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.workspaces.create_workspace(name, color)

    return run


def rename_workspace(container: "Container", workspace_id: int, name: str) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.workspaces.rename_workspace(workspace_id, name)

    return run


def recolor_workspace(container: "Container", workspace_id: int, color: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.workspaces.set_color(workspace_id, color)

    return run


def delete_workspace(container: "Container", workspace_id: int) -> TaskFunction:
    def run(progress: ProgressCallback) -> int:
        return container.workspaces.delete_workspace(workspace_id)

    return run


def move_profiles(container: "Container", ids: list[int], workspace_id: int | None) -> TaskFunction:
    def run(progress: ProgressCallback) -> int:
        return container.workspaces.move_profiles(ids, workspace_id)

    return run


# -------------------------------------------------------------------- activity


def list_activity(container: "Container", *, before_id: int | None = None, after_id: int | None = None,
                  group: str | None = None, errors_only: bool = False, limit: int = 200) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.activity.list(before_id=before_id, after_id=after_id, limit=limit, group=group,
                                       errors_only=errors_only)

    return run


def mark_activity_seen(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> None:
        container.activity.mark_seen()

    return run


def clear_activity(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback) -> int:
        return container.activity.clear()

    return run


def start_profile(container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.profiles.start_profile(profile_id)

    return run


def stop_profile(container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.profiles.stop_profile(profile_id)

    return run


def restart_profile(container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.profiles.restart_profile(profile_id)

    return run


def duplicate_profile(container: "Container", profile_id: int) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.profiles.duplicate_profile(profile_id)

    return run


def open_url(container: "Container", profile_id: int, url: str, *, start_if_stopped: bool = True) -> TaskFunction:
    """Open a page in a profile; start it with that page when it is not running."""

    def run(progress: ProgressCallback):
        profile = container.profiles.get_profile(profile_id)
        if profile.status.value == "RUNNING":
            container.profiles.open_url(profile_id, url)
            return profile
        if not start_if_stopped:
            return profile
        container.profiles.update_profile(profile_id, start_url=url, auto_config=False)
        try:
            return container.profiles.start_profile(profile_id)
        finally:  # a check page is a one-off, not the profile's permanent start page
            container.profiles.update_profile(profile_id, start_url=profile.start_url or "", auto_config=False)

    return run


def export_cookies(container: "Container", profile_id: int, output: Path | None = None) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.cookies.export(profile_id, output)

    return run


def import_cookies(container: "Container", profile_id: int, source: Path) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.cookies.import_(profile_id, source)

    return run


# --------------------------------------------------------------- proxies


def check_new_proxy(container: "Container", text: str, protocol: str) -> TaskFunction:
    """The dialog's "Check": add the pasted proxy, test it, report what was found."""

    def run(progress: ProgressCallback) -> dict:
        summary = container.proxies.import_text(text, _protocol(protocol))
        if not summary.ids:
            return {"id": None, "ok": False, "unreadable": True}
        proxy_id = summary.ids[0]
        try:
            proxy, check = container.proxies.check_proxy(proxy_id)
        except Exception as exc:
            return {"id": proxy_id, "ok": False, "error": str(exc)}
        ok = check is not None and check.status.value == "WORKING"
        return {
            "id": proxy_id,
            "ok": ok,
            "country": (check.country if check else None),
            "country_code": (check.country_code if check else None),
            "latency": (check.latency_ms if check else None),
            "error": (check.error if check else None),
        }

    return run


def import_proxies(container: "Container", text: str, protocol: str, check: bool) -> TaskFunction:
    def run(progress: ProgressCallback):
        summary = container.proxies.import_text(text, _protocol(protocol))
        if check and summary.ids:
            container.proxies.check_all(ids=summary.ids, on_progress=progress)
        return summary

    return run


def check_proxies(container: "Container", ids: list[int] | None = None, *, stop_event=None) -> TaskFunction:
    """Check the given proxies, or the whole list when ``ids`` is None (many at a time)."""

    def run(progress: ProgressCallback):
        return container.proxies.check_all(
            force=True, on_progress=progress, purge_failed=False, ids=ids, stop_event=stop_event
        )

    return run


def refresh_free_proxies(container: "Container", *, stop_event=None) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.proxies.refresh(
            collect=True, reset=False, force=True, on_progress=progress,
            stop_event=stop_event, purge_failed=True,
        )

    return run


def delete_proxies(container: "Container", ids: list[int]) -> TaskFunction:
    def run(progress: ProgressCallback) -> int:
        return container.proxies.delete_proxies(list(ids))

    return run


# ------------------------------------------------------------------ logs


def list_logs(container: "Container", after_id: int = 0) -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.logs.list_logs(after_id=after_id)

    return run


def export_logs(container: "Container", path: Path) -> TaskFunction:
    def run(progress: ProgressCallback):
        container.logs.export(path)
        return path

    return run


def clear_logs(container: "Container") -> TaskFunction:
    def run(progress: ProgressCallback):
        return container.logs.clear()

    return run


# ------------------------------------------------------------ dialog data


def load_dialog_data(container: "Container", profile_id: int | None = None) -> TaskFunction:
    """Everything the profile dialog needs, read off the UI thread."""

    def run(progress: ProgressCallback) -> dict:
        configuration = None
        if profile_id is not None:
            profile = container.profiles.get_profile(profile_id)
            if profile.configuration_id is not None:
                configuration = container.configurations.get_configuration(profile.configuration_id)
        return {
            "proxies": list_proxies(container).rows,
            "configuration": configuration,
            "names": {p.name for p in container.profiles.list_profiles()},
        }

    return run
