"""Exporting a profile to one archive and importing it back, here or on another computer.

The archive is a plain zip: ``manifest.json`` (the profile's settings, fingerprint, protection
switches, the seed that makes its canvas / audio noise its own, and - only on request - its proxy)
and ``data/`` (the browser's own folder: site data, bookmarks, extensions, history).

What does NOT travel: the browser's caches, and anything the operating system protects. Chrome
encrypts cookies and saved passwords with a key that belongs to the computer's user, so they open
on the computer they came from (a backup, a restore after a re-install) and not on another one,
where the profile arrives with the same fingerprint and settings but logged out.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from antidetect import __version__
from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.errors import ProfileNotFoundError, TransferError

if TYPE_CHECKING:
    from antidetect.application.configuration_service import ConfigurationService
    from antidetect.application.ports import ActivitySink
    from antidetect.application.profile_service import ProfileService
    from antidetect.application.proxy_service import ProxyService
    from antidetect.application.workspace_service import WorkspaceService
    from antidetect.domain.models.profile import Profile

FORMAT = "antidetect-profile"
VERSION = 1
MANIFEST = "manifest.json"
DATA = "data/"
SEED_FILE = ".antidetect-seed"
#: Refuse an archive that claims to unpack to more than this: a damaged or hostile file, not a profile.
MAX_UNPACKED_BYTES = 64 * 1024 ** 3

#: Folders the browser rebuilds by itself (caches) and files that only mean "this browser is running".
_SKIP_DIRS = frozenset({
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "GrShaderCache", "ShaderCache",
    "GraphiteDawnCache", "Crashpad", "component_crx_cache", "extensions_crx_cache", "CacheStorage", "ScriptCache",
    "optimization_guide_model_store", "BrowserMetrics", "Safe Browsing", "Crash Reports",
})
_SKIP_FILES = frozenset({
    "SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile", "DevToolsActivePort", "LOCK", "Cookies-journal",
    "BrowserMetrics-spare.pma",
})

_CONFIGURATION_FIELDS = (
    "user_agent", "platform", "language", "locale", "timezone", "screen_width", "screen_height",
    "device_pixel_ratio", "color_depth", "webgl_settings", "hardware_settings", "client_hints",
)


def _skipped(relative: Path) -> bool:
    return relative.name in _SKIP_FILES or any(part in _SKIP_DIRS for part in relative.parts)


def safe_file_name(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " ._-()" else "_" for c in name).strip(" .")
    return cleaned or "profile"


class TransferService:
    def __init__(
        self,
        profiles: "ProfileService",
        configurations: "ConfigurationService",
        proxies: "ProxyService",
        workspaces: "WorkspaceService",
        activity: "ActivitySink | None" = None,
    ) -> None:
        self._profiles = profiles
        self._configurations = configurations
        self._proxies = proxies
        self._workspaces = workspaces
        self._activity = activity

    # ---------------------------------------------------------------- export

    def default_file_name(self, profile_id: int) -> str:
        return f"{safe_file_name(self._profiles.get_profile(profile_id).name)}.zip"

    def export_profile(
        self,
        profile_id: int,
        destination: Path,
        *,
        include_proxy: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Write the profile to ``destination`` (a file, or a folder: the name is then made up).

        The profile must be stopped: a running browser is writing its databases, and a copy taken
        in the middle of that is not one you can rely on. The proxy's login and password are in
        the file in plain text, which is why they go in only when asked for.
        """
        profile = self._profiles.get_profile(profile_id)
        if profile.status.value == "RUNNING":
            raise TransferError(f"Stop “{profile.name}” first: a running browser can't be copied reliably.")
        source = Path(profile.profile_path)               # a profile never started has no folder: settings only

        destination = Path(destination).expanduser()
        if destination.is_dir():
            destination = destination / f"{safe_file_name(profile.name)}.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)

        files = self._files(source)
        manifest = self._manifest(profile, source, include_proxy)
        scratch = destination.with_name(destination.name + ".part")
        try:
            with zipfile.ZipFile(scratch, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
                for index, (path, relative) in enumerate(files, start=1):
                    try:
                        archive.write(path, DATA + relative.as_posix())
                    except OSError:
                        pass                      # a file that vanished or is locked is not worth losing the rest
                    if on_progress is not None:
                        on_progress(index, len(files))
            os.replace(scratch, destination)
        except BaseException:
            scratch.unlink(missing_ok=True)
            raise
        if self._activity is not None:
            self._activity.record("act.profile.exported", profile.name, profile_id=profile.id)
        return destination

    @staticmethod
    def _files(source: Path) -> list[tuple[Path, Path]]:
        found: list[tuple[Path, Path]] = []
        if not source.is_dir():
            return found
        for folder, dirs, names in os.walk(source, followlinks=False):
            relative_folder = Path(folder).relative_to(source)
            dirs[:] = [d for d in dirs if not _skipped(relative_folder / d) and not Path(folder, d).is_symlink()]
            for name in names:
                path = Path(folder, name)
                relative = relative_folder / name
                if _skipped(relative) or path.is_symlink() or not path.is_file():
                    continue
                found.append((path, relative))
        return found

    def _manifest(self, profile: "Profile", source: Path, include_proxy: bool) -> dict[str, Any]:
        configuration = (
            self._configurations.get_configuration(profile.configuration_id)
            if profile.configuration_id is not None else None
        )
        workspace = next(
            (info.workspace.name for info in self._workspaces.list_workspaces()
             if info.workspace.id == profile.workspace_id), None,
        ) if profile.workspace_id is not None else None
        manifest: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "app_version": __version__,
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "profile": {
                "name": profile.name,
                "notes": profile.notes,
                "tags": list(profile.tags),
                "start_url": profile.start_url,
                "geo_auto": profile.geo_auto,
                "workspace": workspace,
            },
            "configuration": (
                {field: getattr(configuration, field) for field in _CONFIGURATION_FIELDS}
                | {"privacy_settings": configuration.privacy_settings}
                if configuration is not None else None
            ),
            "seed": self._read_seed(source),
            "proxy": None,
        }
        if include_proxy and profile.proxy_id is not None:
            proxy = self._proxies.get_proxy(profile.proxy_id)
            manifest["proxy"] = {
                "protocol": proxy.protocol.value, "host": proxy.host, "port": proxy.port,
                "username": proxy.username, "password": proxy.password,
            }
        return manifest

    @staticmethod
    def _read_seed(source: Path) -> int | None:
        try:
            value = int((source / SEED_FILE).read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return value if value > 0 else None

    # ---------------------------------------------------------------- import

    def read_manifest(self, source: Path) -> dict[str, Any]:
        """The archive's manifest, checked: what an import dialog shows before it does anything."""
        source = Path(source).expanduser()
        if not source.is_file():
            raise TransferError(f"File not found: {source}")
        try:
            with zipfile.ZipFile(source) as archive:
                try:
                    raw = archive.read(MANIFEST)
                except KeyError:
                    raise TransferError("This is not a profile archive made by this app (no manifest).") from None
        except zipfile.BadZipFile:
            raise TransferError("This file is not a valid archive.") from None
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise TransferError("The archive's manifest is damaged.") from None
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise TransferError("This is not a profile archive made by this app.")
        version = manifest.get("version")
        if not isinstance(version, int) or version < 1:
            raise TransferError("The archive's manifest is damaged.")
        if version > VERSION:
            raise TransferError("This archive was made by a newer version of the app. Update the app to open it.")
        if not isinstance(manifest.get("profile"), dict) or not str(manifest["profile"].get("name") or "").strip():
            raise TransferError("The archive's manifest is damaged (no profile name).")
        return manifest

    def import_profile(
        self,
        source: Path,
        *,
        name: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> "Profile":
        """Create a new profile from an archive. Nothing existing is touched or replaced.

        The name is the archive's unless given; when it is taken, “(imported)” and a number are added.
        A profile that fails halfway is removed again, so a bad file leaves nothing behind.
        """
        source = Path(source).expanduser()
        manifest = self.read_manifest(source)
        meta = manifest["profile"]
        wanted = self._free_name(name if name is not None else str(meta["name"]))

        workspace_id = None
        if meta.get("workspace"):
            found = self._workspaces.find(meta["workspace"]) or self._workspaces.create_workspace(meta["workspace"])
            workspace_id = found.id
        configuration = manifest.get("configuration") or {}
        platform = configuration.get("platform")
        profile = self._profiles.create_profile(
            wanted,
            platform=platform if platform in ("windows", "macos", "linux") else None,
            auto_config=False,
            notes=str(meta.get("notes") or ""),
            tags=[str(t) for t in (meta.get("tags") or [])],
            geo_auto=bool(meta.get("geo_auto", True)),
            start_url=meta.get("start_url") or None,
            workspace_id=workspace_id,
        )
        try:
            self._apply_configuration(profile, configuration)
            self._apply_proxy(profile, manifest.get("proxy"))
            self._unpack(source, Path(profile.profile_path), on_progress)
            seed = manifest.get("seed")
            if isinstance(seed, int) and seed > 0:
                (Path(profile.profile_path) / SEED_FILE).write_text(str(seed), encoding="utf-8")
        except BaseException:
            try:
                self._profiles.delete_profile(profile.id)
            except Exception:
                pass
            raise
        if self._activity is not None:
            self._activity.record("act.profile.imported", profile.name, profile_id=profile.id)
        return self._profiles.get_profile(profile.id)

    def _free_name(self, wanted: str) -> str:
        taken = {p.name.casefold() for p in self._profiles.list_profiles()}
        base = " ".join(wanted.split()) or "Profile"
        if base.casefold() not in taken:
            return base
        candidate, number = f"{base} (imported)", 1
        while candidate.casefold() in taken:
            number += 1
            candidate = f"{base} (imported {number})"
        return candidate

    def _apply_configuration(self, profile: "Profile", configuration: dict[str, Any]) -> None:
        if profile.configuration_id is None:
            return
        values = {k: v for k, v in configuration.items() if k in (*_CONFIGURATION_FIELDS, "privacy_settings") and v is not None}
        if values:
            try:
                self._configurations.update_configuration(profile.configuration_id, **values)
            except ValueError as exc:
                raise TransferError(f"The archive holds an invalid fingerprint: {exc}") from exc

    def _apply_proxy(self, profile: "Profile", proxy: dict[str, Any] | None) -> None:
        if not proxy:
            return
        try:
            protocol = ProxyProtocol.from_string(str(proxy.get("protocol") or "HTTP"))
            auth = ""
            if proxy.get("username"):
                auth = f"{quote(str(proxy['username']), safe='')}:{quote(str(proxy.get('password') or ''), safe='')}@"
            line = f"{protocol.value.lower()}://{auth}{proxy['host']}:{int(proxy['port'])}"
        except (KeyError, ValueError, TypeError):
            raise TransferError("The archive holds a proxy that can't be read.") from None
        summary = self._proxies.import_text(line, protocol)
        if summary.ids:
            self._profiles.assign_proxy(profile.id, summary.ids[0], auto_config=False)

    @staticmethod
    def _unpack(source: Path, target: Path, on_progress: Callable[[int, int], None] | None) -> None:
        with zipfile.ZipFile(source) as archive:
            members = [m for m in archive.infolist() if m.filename.startswith(DATA) and not m.is_dir()]
            if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
                raise TransferError("The archive claims to be unreasonably large; it is probably damaged.")
            root = target.resolve()
            target.mkdir(parents=True, exist_ok=True)
            for index, member in enumerate(members, start=1):
                relative = PurePosixPath(member.filename[len(DATA):])
                # Zip-slip: a name like "../../x" or "/etc/x" must never leave the profile's folder.
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise TransferError(f"The archive holds an unsafe path: {member.filename!r}")
                path = (root / Path(*relative.parts)).resolve()
                if root != path and root not in path.parents:
                    raise TransferError(f"The archive holds an unsafe path: {member.filename!r}")
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as read, open(path, "wb") as write:
                    shutil.copyfileobj(read, write, 1024 * 1024)
                if on_progress is not None:
                    on_progress(index, len(members))
