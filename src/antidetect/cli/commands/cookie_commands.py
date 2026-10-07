"""Render cookies subcommands: export / import.

Purposefully never prints, echoes or logs cookie payloads; only filesystem
paths are displayed. See ``CookieService`` for the backup-level guarantees.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace

    from antidetect.application.cookie_service import CookieService


def cmd_export(service: "CookieService", args: "Namespace") -> None:
    output = service.export(args.id, output=Path(args.to) if args.to else None)
    print(f"Exported cookies of profile {args.id} to {output}")


def cmd_import(service: "CookieService", args: "Namespace") -> None:
    target = service.import_(args.id, Path(args.source))
    print(f"Imported cookies into profile {args.id} from {args.source}")
    print(f"  replaced {target}")