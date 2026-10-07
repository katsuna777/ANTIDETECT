"""Several profiles at once, and profiles to and from a file. These need more than the profile
service (proxies, workspaces), so they are handed the whole container."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from antidetect.application.bulk_service import BulkRequest
from antidetect.application.fingerprint import privacy

if TYPE_CHECKING:
    from argparse import Namespace

    from antidetect.container import Container


def _lines_of(path: str) -> str:
    """The text of a proxy list file; ``-`` reads the standard input."""
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def cmd_bulk(container: "Container", args: "Namespace") -> None:
    from antidetect.cli.commands.profile_commands import _privacy_from

    workspace_id = None
    if args.workspace:
        workspace = container.workspaces.find(args.workspace) or container.workspaces.create_workspace(args.workspace)
        workspace_id = workspace.id
    request = BulkRequest(
        name=args.name,
        count=args.count,
        platform=args.platform,
        proxy_text=_lines_of(args.proxies_file) if args.proxies_file else "",
        proxy_protocol=(args.proxy_type or "http").upper(),
        workspace_id=workspace_id,
        tags=tuple(t.strip() for t in (args.tags or "").split(",") if t.strip()),
        geo_auto=not args.no_geo_auto,
        start_url=args.start_url,
        privacy_settings=privacy.minimal(_privacy_from(args)) or None,
    )
    result = container.bulk.create(request)
    for line in result.failed:
        print(f"Not created: {line}", file=sys.stderr)
    for line in result.invalid_proxies:
        print(f"Unreadable proxy line skipped: {line}", file=sys.stderr)
    print(f"Created {result.created} of {request.count} profiles "
          f"({result.with_proxy} with a proxy, {result.without_proxy} without)")
    if result.profile_ids and (request.geo_auto or request.proxy_text.strip()):
        print("Checking the proxies and matching language and time zone to them...")
        container.bulk.settle(result.profile_ids)
    for profile_id in result.profile_ids:
        print(f"  id={profile_id}  {container.profiles.get_profile(profile_id).name}")
    if result.failed:
        raise ValueError(f"{len(result.failed)} profile(s) could not be created")


def cmd_export(container: "Container", args: "Namespace") -> None:
    destination = Path(args.to).expanduser() if args.to else Path.cwd()
    out = container.transfer.export_profile(args.id, destination, include_proxy=args.with_proxy)
    print(f"Exported profile id={args.id} to {out}")
    if args.with_proxy:
        print("The proxy's login and password are in the file as plain text: share it only with people you trust.")
    print("Cookies and saved passwords are tied to this computer; elsewhere the profile opens logged out.")


def cmd_import(container: "Container", args: "Namespace") -> None:
    profile = container.transfer.import_profile(Path(args.file), name=args.name)
    print(f"Imported profile id={profile.id} name={profile.name!r} path={profile.profile_path}")
