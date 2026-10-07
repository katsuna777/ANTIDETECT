from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from typing import Callable

from antidetect.application.configuration_service import ConfigurationService
from antidetect.application.cookie_service import CookieService
from antidetect.application.profile_service import ProfileService
from antidetect.application.proxy_service import ProxyService
from antidetect.cli.commands import (
    api_commands,
    browser_commands,
    configuration_commands,
    cookie_commands,
    profile_commands,
    proxy_commands,
    transfer_commands,
)
from antidetect.api.examples import KEYS
from antidetect.container import bootstrap
from antidetect.domain.errors import AntiDetectError, ChromiumNotFoundError

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
    "restore": profile_commands.cmd_restore,
    "trash": profile_commands.cmd_trash,
    "proxy": profile_commands.cmd_proxy,
    # these three are handed the whole container (see _CONTAINER_COMMANDS)
    "bulk": transfer_commands.cmd_bulk,
    "export": transfer_commands.cmd_export,
    "import": transfer_commands.cmd_import,
}

#: Commands that need more than their group's service.
_CONTAINER_COMMANDS = {("profile", "bulk"), ("profile", "export"), ("profile", "import")}

_PROXY_HANDLERS: dict[str, ProxyHandler] = {
    "add": proxy_commands.cmd_add,
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

_BROWSER_HANDLERS: dict[str, Callable] = {
    "status": browser_commands.cmd_status,
    "download": browser_commands.cmd_download,
    "check-update": browser_commands.cmd_check_update,
    "path": browser_commands.cmd_path,
}

_API_HANDLERS: dict[str, Callable] = {
    "serve": api_commands.cmd_serve,
    "token": api_commands.cmd_token,
    "examples": api_commands.cmd_examples,
    "docs": api_commands.cmd_docs,
    "keys": api_commands.cmd_keys,
}

# Back-compat alias: legacy tests inject raisers through ``_HANDLERS``.
_HANDLERS = _PROFILE_HANDLERS


def _add_privacy_options(parser, *, creating: bool) -> None:
    """The protection switches, in the same words for ``create`` and ``update``."""
    parser.add_argument(
        "--webrtc", choices=("auto", "block", "allow"), default=None,
        help="WebRTC: auto = hidden behind a proxy (default), block = always hidden, allow = left alone",
    )
    parser.add_argument(
        "--theme", choices=("light", "dark", "auto"), default=None,
        help="Colour scheme sites are told the profile prefers: light (default for new profiles), dark, "
             "or auto = follow this computer",
    )
    for noun in ("canvas", "audio"):
        parser.add_argument(
            f"--no-{noun}-noise", action="store_true", dest=f"no_{noun}_noise",
            help=f"Turn the {noun} fingerprint noise off",
        )
        if not creating:
            parser.add_argument(
                f"--{noun}-noise", action="store_true", dest=f"{noun}_noise",
                help=f"Turn the {noun} fingerprint noise back on",
            )



def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="antidetect", description="Antidetect — isolated browser profiles (command line)")
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
    create.add_argument(
        "--platform", choices=("windows", "macos", "linux"), default=None,
        help="Operating system to present (default: this computer's, the most natural)",
    )
    create.add_argument("--tags", default=None, help="Comma-separated tags")
    create.add_argument("--notes", default=None, help="Free-form notes")
    create.add_argument("--start-url", default=None, dest="start_url", help="Page to open at start")
    create.add_argument(
        "--no-geo-auto", action="store_true", dest="no_geo_auto",
        help="Keep language/time zone as generated instead of following the IP address",
    )
    _add_privacy_options(create, creating=True)

    bulk = profile_sub.add_parser(
        "bulk", help="Create several profiles at once (numbered names, a proxy each from a file)",
    )
    bulk.add_argument("name", help='Base name: "Shop" gives "Shop 1", "Shop 2"...; "Acc #{n}" puts the number where you say')
    bulk.add_argument("--count", type=int, required=True, help="How many profiles (1-200)")
    bulk.add_argument("--platform", choices=("windows", "macos", "linux"), default=None,
                      help="Operating system for all of them (default: this computer's)")
    bulk.add_argument("--proxies-file", default=None, dest="proxies_file",
                      help="Text file with one proxy per line, '-' for standard input; each profile gets the next one, "
                           "none is shared, profiles beyond the list get none")
    bulk.add_argument("--proxy-type", choices=("http", "https", "socks5"), default=None, dest="proxy_type",
                      help="Type for lines that do not say")
    bulk.add_argument("--workspace", default=None, help="Workspace for all of them (created when missing)")
    bulk.add_argument("--tags", default=None, help="Comma-separated tags")
    bulk.add_argument("--start-url", default=None, dest="start_url", help="Page to open at start")
    bulk.add_argument("--no-geo-auto", action="store_true", dest="no_geo_auto",
                      help="Keep language/time zone as generated instead of following the IP address")
    _add_privacy_options(bulk, creating=True)

    pexport = profile_sub.add_parser("export", help="Save a stopped profile (settings, fingerprint, browser data) to a .zip")
    pexport.add_argument("id", type=int)
    pexport.add_argument("--to", default=None, help="File or folder to write to (default: the current folder)")
    pexport.add_argument("--with-proxy", action="store_true", dest="with_proxy",
                         help="Include the proxy; its login and password go into the file as plain text")

    pimport = profile_sub.add_parser("import", help="Create a new profile from a .zip made by 'profile export'")
    pimport.add_argument("file", help="The archive")
    pimport.add_argument("--name", default=None, help="Name for the new profile (default: the archive's)")

    show = profile_sub.add_parser("show", help="Show profile details")
    show.add_argument("id", type=int)

    profile_sub.add_parser("list", help="List all profiles as a table")

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
        _add_privacy_options(update, creating=False)

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
        ("start", "Start the profile browser (stays open to keep it protected)"),
        ("stop", "Stop the profile browser"),
        ("restart", "Restart the profile browser"),
    ):
        sub = profile_sub.add_parser(name, help=help_text)
        sub.add_argument("id", type=int)
        if name == "start":
            sub.add_argument(
                "--detach", action="store_true",
                help="Return immediately (tabs opened later are NOT protected)",
            )

    duplicate = profile_sub.add_parser("duplicate", help="Duplicate a profile (copies browser state)")
    duplicate.add_argument("id", type=int)
    duplicate.add_argument("--name", default=None, help="Name for the copy")

    delete = profile_sub.add_parser("delete", help="Move a profile to the trash (--permanent: delete it and its data for good)")
    delete.add_argument("id", type=int)
    delete.add_argument("--permanent", action="store_true", help="Delete for good: the data directory goes too")
    delete.add_argument("--yes", action="store_true", help="Skip the confirmation of a permanent delete")

    restore = profile_sub.add_parser("restore", help="Bring a profile back from the trash")
    restore.add_argument("id", type=int)

    profile_sub.add_parser("trash", help="List the profiles in the trash")

    # --------------------------------------------------------------- configs
    config = subparsers.add_parser("config", help="Manage browser configurations")
    config_sub = config.add_subparsers(dest="command", required=True)

    config_sub.add_parser("list", help="List stored configurations as a table")
    ccreate = config_sub.add_parser("create", help="Create a configuration by hand")
    ccreate.add_argument("name", help="Configuration name")
    _add_config_fields(ccreate)

    generate = config_sub.add_parser(
        "generate", help="Generate a coherent fingerprint configuration"
    )
    generate.add_argument("--name", default=None, help="Name for the generated configuration")
    generate.add_argument("--from-template", default=None, dest="from_template",
                          help="Template key (windows-chrome, windows-laptop, macos-chrome, linux-chrome)")
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

    padd = proxy_sub.add_parser("add", help="Add your own proxies (host:port:user:pass, user:pass@host:port, ...)")
    padd.add_argument("proxies", nargs="*", help="One or more proxy strings")
    padd.add_argument("--file", default=None, help="Read proxies from a text file, one per line")
    padd.add_argument("--type", default=None, choices=("http", "https", "socks5"), help="Type when the string has none")
    padd.add_argument("--check", action="store_true", help="Check each proxy right after adding it")

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

    # -------------------------------------------------------------------- api
    browser = subparsers.add_parser("browser", help="Which Chrome runs the profiles; download Google's Chrome for the app")
    browser_sub = browser.add_subparsers(dest="command", required=True)
    browser_sub.add_parser("status", help="Show the browser that runs the profiles and the downloaded versions")
    browser_sub.add_parser("path", help="Print the path of the browser that runs the profiles (for scripts)")
    bdownload = browser_sub.add_parser("download", help="Download the newest Chrome (Google's Chrome for Testing) for the app to use")
    bcheck = browser_sub.add_parser("check-update", help="Say whether Google has a newer Chrome than the downloaded one")
    for sub in (bdownload, bcheck):
        sub.add_argument("--channel", choices=("Stable", "Beta", "Dev", "Canary"), default="Stable")

    api = subparsers.add_parser("api", help="Local HTTP API for automation (Playwright, Puppeteer, Selenium)")
    api_sub = api.add_subparsers(dest="command", required=True)

    aserve = api_sub.add_parser("serve", help="Run the API without the window (stays open; Ctrl+C stops it)")
    aserve.add_argument("--port", type=int, default=None, help="Port to listen on (saved; default 47831)")

    atoken = api_sub.add_parser("token", help="Print the API token")
    atoken.add_argument("--rotate", action="store_true", help="Make a new token; the old one stops working")

    aexamples = api_sub.add_parser("examples", help="Print ready-to-run example scripts with your address and token")
    aexamples.add_argument("kind", nargs="?", choices=KEYS, default=None, help="Only this one (default: all)")
    aexamples.add_argument("--lang", choices=("en", "ru"), default=None, help="Language of the comments (default: the app's)")

    adocs = api_sub.add_parser("docs", help="Print the API reference (methods, types, errors) as Markdown")
    adocs.add_argument("--lang", choices=("en", "ru"), default=None, help="Language (default: the app's)")

    akeys = api_sub.add_parser("keys", help="List and manage access keys")
    akeys.add_argument("--show", action="store_true", help="Print whole keys in the list instead of a shortened form")
    keys_sub = akeys.add_subparsers(dest="keys_action")
    kadd = keys_sub.add_parser("add", help="Make a new key")
    kadd.add_argument("name", help="What it is for, e.g. the script's name")
    krename = keys_sub.add_parser("rename", help="Rename a key")
    krename.add_argument("key", help="Key id or name")
    krename.add_argument("name", help="New name")
    kregen = keys_sub.add_parser("regenerate", help="New secret for a key; the old one stops working")
    kregen.add_argument("key", help="Key id or name")
    kremove = keys_sub.add_parser("remove", help="Delete a key")
    kremove.add_argument("key", help="Key id or name")

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
    from antidetect.runtime import ensure_ssl_certs

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

    if group == "profile" and args.command == "delete" and args.permanent and not args.yes:
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

    service = container if group in ("api", "browser") or (group, args.command) in _CONTAINER_COMMANDS else getattr(container, _SERVICE_ATTR[group])
    try:
        handler(service, args)
    except AntiDetectError as exc:
        container.logs.error("cli", f"Command failed: {exc}")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        container.logs.error("cli", f"Command failed: {exc}")
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
    "api": _API_HANDLERS,
    "browser": _BROWSER_HANDLERS,
}

_SERVICE_ATTR = {
    "profile": "profiles",
    "proxy": "proxies",
    "config": "configurations",
    "cookies": "cookies",
}


if __name__ == "__main__":
    raise SystemExit(main())