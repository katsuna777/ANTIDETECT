from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from typing import Callable

from app.application.configuration_service import ConfigurationService
from app.application.cookie_service import CookieService
from app.application.profile_service import ProfileService
from app.application.proxy_service import ProxyService
from app.cli.commands import (
    configuration_commands,
    cookie_commands,
    profile_commands,
    proxy_commands,
)
from app.di import bootstrap
from app.domain.errors import AntiDetectError, ChromiumNotFoundError

ProfileHandler = Callable[[ProfileService, Namespace], None]
ProxyHandler = Callable[[ProxyService, Namespace], None]
ConfigurationHandler = Callable[[ConfigurationService, Namespace], None]
CookieHandler = Callable[[CookieService, Namespace], None]

_PROFILE_HANDLERS: dict[str, ProfileHandler] = {
    "create": profile_commands.cmd_create,
    "show": profile_commands.cmd_show,
    "list": profile_commands.cmd_list,
    "update": profile_commands.cmd_update,
    "edit": profile_commands.cmd_update,
    "doctor": profile_commands.cmd_doctor,
    "start": profile_commands.cmd_start,
    "stop": profile_commands.cmd_stop,
    "restart": profile_commands.cmd_restart,
    "duplicate": profile_commands.cmd_duplicate,
    "delete": profile_commands.cmd_delete,
    "proxy": profile_commands.cmd_proxy,
}

_PROXY_HANDLERS: dict[str, ProxyHandler] = {
    "list": proxy_commands.cmd_list,
    "refresh": proxy_commands.cmd_refresh,
    "check": proxy_commands.cmd_check,
    "check-all": proxy_commands.cmd_check_all,
    "remove-dead": proxy_commands.cmd_remove_dead,
}

_CONFIGURATION_HANDLERS: dict[str, ConfigurationHandler] = {
    "list": configuration_commands.cmd_list,
    "create": configuration_commands.cmd_create,
    "generate": configuration_commands.cmd_generate,
    "show": configuration_commands.cmd_show,
    "edit": configuration_commands.cmd_edit,
    "duplicate": configuration_commands.cmd_duplicate,
    "delete": configuration_commands.cmd_delete,
}

_COOKIE_HANDLERS: dict[str, CookieHandler] = {
    "export": cookie_commands.cmd_export,
    "import": cookie_commands.cmd_import,
}

# Back-compat alias: legacy tests inject raisers through ``_HANDLERS``.
_HANDLERS = _PROFILE_HANDLERS


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="app", description="Antidetect browser (foundation: CLI only)")
    subparsers = parser.add_subparsers(dest="group", required=True)

    # ------------------------------------------------------------- profiles
    profile = subparsers.add_parser("profile", help="Manage browser profiles")
    profile_sub = profile.add_subparsers(dest="command", required=True)

    create = profile_sub.add_parser("create", help="Create a new profile")
    create.add_argument("name", help="Profile name")
    create.add_argument("--configuration-id", type=int, default=None, dest="configuration_id")
    create.add_argument("--proxy-id", type=int, default=None, dest="proxy_id")
    create.add_argument(
        "--no-auto-config", action="store_true", dest="no_auto_config",
        help="Do not auto-match the fingerprint to the proxy country",
    )

    show = profile_sub.add_parser("show", help="Show profile details")
    show.add_argument("id", type=int)

    list_ = profile_sub.add_parser("list", help="List all profiles as a table")

    for name in ("update", "edit"):
        update = profile_sub.add_parser(name, help="Update a profile" + (" (alias)" if name == "edit" else ""))
        update.add_argument("id", type=int)
        update.add_argument("name", nargs="?", default=None, help="New profile name")
        update.add_argument("--configuration-id", type=int, default=None, dest="configuration_id")
        update.add_argument("--proxy-id", type=int, default=None, dest="proxy_id")
        update.add_argument("--remove-proxy", action="store_true", dest="remove_proxy")
        update.add_argument(
            "--no-auto-config", action="store_true", dest="no_auto_config",
            help="Do not auto-match the fingerprint to the proxy country",
        )

    proxy = profile_sub.add_parser(
        "proxy", help="Assign, change or remove the profile's proxy"
    )
    proxy.add_argument("id", type=int)
    proxy.add_argument("--set", type=int, default=None, dest="set", help="Proxy id to assign")
    proxy.add_argument("--remove", action="store_true", help="Detach the proxy")
    proxy.add_argument(
        "--no-auto-config", action="store_true", dest="no_auto_config",
        help="Do not auto-match the fingerprint to the proxy country",
    )

    doctor = profile_sub.add_parser(
        "doctor", help="Check a profile for fingerprint/proxy issues blocking Google login"
    )
    doctor.add_argument("id", type=int)
    doctor.add_argument(
        "--no-probe",
        action="store_true",
        help="Skip the live Google reachability probe (offline mode)",
    )

    for name, help_text in (
        ("start", "Start the profile browser"),
        ("stop", "Stop the profile browser"),
        ("restart", "Restart the profile browser"),
    ):
        sub = profile_sub.add_parser(name, help=help_text)
        sub.add_argument("id", type=int)

    duplicate = profile_sub.add_parser("duplicate", help="Duplicate a profile (copies browser state)")
    duplicate.add_argument("id", type=int)
    duplicate.add_argument("--name", default=None, help="Name for the copy")

    delete = profile_sub.add_parser("delete", help="Delete a profile and its data directory")
    delete.add_argument("id", type=int)
    delete.add_argument("--yes", action="store_true", help="Skip confirmation")

    # --------------------------------------------------------------- configs
    config = subparsers.add_parser("config", help="Manage browser configurations")
    config_sub = config.add_subparsers(dest="command", required=True)

    clist = config_sub.add_parser("list", help="List stored configurations as a table")
    ccreate = config_sub.add_parser("create", help="Create a configuration by hand")
    ccreate.add_argument("name", help="Configuration name")
    _add_config_fields(ccreate)

    generate = config_sub.add_parser(
        "generate", help="Generate a coherent fingerprint configuration"
    )
    generate.add_argument("--name", default=None, help="Name for the generated configuration")
    generate.add_argument("--from-template", default=None, dest="from_template",
                          help="Template key (windows-chrome, windows-edge, macos-chrome, macos-edge, linux-chrome)")
    generate.add_argument("--platform", default=None, choices=("windows", "macos", "linux"),
                          help="Use a random template for this platform")

    cshow = config_sub.add_parser("show", help="Show configuration details")
    cshow.add_argument("id", type=int)

    cedit = config_sub.add_parser("edit", help="Edit a configuration")
    cedit.add_argument("id", type=int)
    cedit.add_argument("name", nargs="?", default=None, help="New configuration name")
    _add_config_fields(cedit)

    cdup = config_sub.add_parser("duplicate", help="Duplicate a configuration")
    cdup.add_argument("id", type=int)
    cdup.add_argument("--name", default=None, help="Name for the copy")

    cdel = config_sub.add_parser("delete", help="Delete a configuration")
    cdel.add_argument("id", type=int)

    # --------------------------------------------------------------- cookies
    cookies = subparsers.add_parser("cookies", help="Backup/restore profile cookies")
    cookies_sub = cookies.add_subparsers(dest="command", required=True)

    cexp = cookies_sub.add_parser("export", help="Export a profile's cookie database")
    cexp.add_argument("id", type=int)
    cexp.add_argument("--to", default=None, help="Output file path (default: data dir)")

    cimp = cookies_sub.add_parser("import", help="Import cookies into a stopped profile")
    cimp.add_argument("id", type=int)
    cimp.add_argument("--from", dest="source", required=True, help="Path to the cookie database file")

    # ---------------------------------------------------------------- proxies
    proxy = subparsers.add_parser("proxy", help="Manage proxies")
    proxy_sub = proxy.add_subparsers(dest="command", required=True)

    plist = proxy_sub.add_parser("list", help="List stored proxies as a table (working first, best ping on top)")
    plist.add_argument("--status", default=None, help="Filter by status (UNKNOWN/CHECKING/WORKING/DEAD/ERROR)")
    plist.add_argument(
        "--sort", default="latency", choices=("latency", "id", "status", "country"),
        help="Sort order (default: working-first, ping ascending)",
    )
    plist.add_argument("--limit", type=int, default=None, help="Only show N rows")
    plist.add_argument("--reverse", action="store_true", help="Reverse the sort order")

    prep = proxy_sub.add_parser(
        "refresh",
        help="Collect, parse, deduplicate, check and update the proxy pool",
    )
    prep.add_argument("--workers", type=int, default=None, help="Concurrent checker workers")
    prep.add_argument("--timeout", type=float, default=None, help="Per-proxy check timeout (seconds)")
    prep.add_argument("--max-failures", type=int, default=None, help="Consecutive failures before a proxy is DEAD")
    prep.add_argument("--stale-minutes", type=int, default=None, help="Re-check only proxies older than N minutes")
    prep.add_argument("--force", action="store_true", help="Re-check every stored proxy regardless of staleness")
    prep.add_argument("--no-collect", action="store_true", help="Skip downloading sources; only re-check the database")

    pcheck = proxy_sub.add_parser("check", help="Check a single proxy by id")
    pcheck.add_argument("id", type=int)

    pcheckall = proxy_sub.add_parser("check-all", help="Re-check every stored proxy")
    pcheckall.add_argument("--workers", type=int, default=None, help="Concurrent checker workers")
    pcheckall.add_argument("--timeout", type=float, default=None, help="Per-proxy check timeout (seconds)")
    pcheckall.add_argument("--stale-minutes", type=int, default=None, help="When set, only re-check proxies older than N minutes")

    premove = proxy_sub.add_parser("remove-dead", help="Delete confirmed DEAD proxies")
    premove.add_argument("--yes", action="store_true", help="Skip confirmation (only when the dead policy is 'disable')")

    return parser


def _add_config_fields(parser) -> None:
    parser.add_argument("--user-agent", default=None, dest="user_agent")
    parser.add_argument("--language", default=None, dest="language")
    parser.add_argument("--timezone", default=None, dest="timezone")
    parser.add_argument("--platform", default=None, choices=("windows", "macos", "linux"))
    parser.add_argument("--locale", default=None, dest="locale")
    parser.add_argument("--screen-width", type=int, default=None, dest="screen_width")
    parser.add_argument("--screen-height", type=int, default=None, dest="screen_height")
    parser.add_argument("--dpr", type=float, default=None, dest="dpr")
    parser.add_argument("--color-depth", type=int, default=None, dest="color_depth")


def main(argv: list[str] | None = None) -> int:
    from app._frozen import ensure_ssl_certs

    ensure_ssl_certs()
    parser = build_parser()
    args = parser.parse_args(argv)

    group = args.group
    command_handlers = _COMMAND_HANDLERS.get(group)
    if command_handlers is None:
        parser.error(f"Unknown command group: {group}")
        return 2
    handler = command_handlers.get(args.command)
    if handler is None:
        parser.error(f"Unknown {group} command: {args.command}")
        return 2

    if group == "profile" and args.command == "delete" and not args.yes:
        answer = input(f"Delete profile id={args.id} and its data directory? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 0

    try:
        container = bootstrap()
    except ChromiumNotFoundError:
        print(
            "Chromium executable not found. Set ANTIDETECT_CHROMIUM_PATH to the browser binary.",
            file=sys.stderr,
        )
        return 2

    service = getattr(container, _SERVICE_ATTR[group])
    try:
        handler(service, args)
    except AntiDetectError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        container.close()
    return 0


_COMMAND_HANDLERS = {
    "profile": _PROFILE_HANDLERS,
    "proxy": _PROXY_HANDLERS,
    "config": _CONFIGURATION_HANDLERS,
    "cookies": _COOKIE_HANDLERS,
}

_SERVICE_ATTR = {
    "profile": "profiles",
    "proxy": "proxies",
    "config": "configurations",
    "cookies": "cookies",
}


if __name__ == "__main__":
    raise SystemExit(main())