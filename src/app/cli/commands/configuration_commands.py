"""Render config subcommands: list / create / generate / edit / show / duplicate / delete."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace

    from app.application.configuration_service import ConfigurationService
    from app.domain.models.browser_configuration import BrowserConfiguration


def _pretty(dt) -> str:
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def cmd_list(service: "ConfigurationService", args: "Namespace") -> None:
    rows = service.list_configurations()
    if not rows:
        print("No configurations yet. Create one with: app config create \"Name\"")
        return
    table: list[tuple[str, ...]] = [
        ("ID", "NAME", "PLATFORM", "UA", "LANG", "TIMEZONE", "UPDATED")
    ]
    for cfg in rows:
        table.append(
            (
                str(cfg.id),
                cfg.name,
                cfg.platform or "-",
                cfg.user_agent[:44] if cfg.user_agent else "-",
                cfg.language_tag or "-",
                cfg.timezone or "-",
                _pretty(cfg.updated_at),
            )
        )
    _print_table(table)


def cmd_show(service: "ConfigurationService", args: "Namespace") -> None:
    cfg = service.get_configuration(args.id)
    print(f"ID:                 {cfg.id}")
    print(f"NAME:               {cfg.name}")
    print(f"USER_AGENT:         {cfg.user_agent or '-'}")
    print(f"PLATFORM:           {cfg.platform or '-'}")
    print(f"LANG:               {cfg.language_tag or '-'}")
    print(f"LOCALE:             {cfg.locale or '-'}")
    print(f"TIMEZONE:           {cfg.timezone or '-'}")
    print(f"SCREEN:             {_screen(cfg)}")
    print(f"DPR:                {cfg.device_pixel_ratio or '-'}")
    print(f"COLOR_DEPTH:        {cfg.color_depth or '-'}")
    print(f"WEBGL:              {_webgl(cfg)}")
    print(f"HARDWARE:           {_hardware(cfg)}")
    print(f"CLIENT_HINTS:       {_hints(cfg)}")
    print(f"CREATED:            {_pretty(cfg.created_at)}")
    print(f"UPDATED:            {_pretty(cfg.updated_at)}")


def cmd_create(service: "ConfigurationService", args: "Namespace") -> None:
    cfg = service.create_configuration(
        name=args.name,
        user_agent=args.user_agent,
        language=args.language,
        timezone=args.timezone,
        platform=args.platform,
        locale=args.locale,
        screen_width=args.screen_width,
        screen_height=args.screen_height,
        device_pixel_ratio=args.dpr,
        color_depth=args.color_depth,
    )
    print(f"Created configuration id={cfg.id} name={cfg.name!r}")


def cmd_generate(service: "ConfigurationService", args: "Namespace") -> None:
    cfg = service.generate_configuration(
        name=args.name,
        template=args.from_template,
        platform=args.platform,
    )
    print(f"Generated configuration id={cfg.id} name={cfg.name!r}")
    print(f"  USER_AGENT: {cfg.user_agent}")
    print(f"  LANG/LOCALE: {cfg.language_tag} / {cfg.locale}  TIMEZONE: {cfg.timezone}")
    print(
        f"  SCREEN: {cfg.screen_width}x{cfg.screen_height} "
        f"DPR={cfg.device_pixel_ratio} DEPTH={cfg.color_depth}"
    )


def cmd_edit(service: "ConfigurationService", args: "Namespace") -> None:
    cfg = service.update_configuration(
        configuration_id=args.id,
        name=args.name,
        user_agent=args.user_agent,
        language=args.language,
        timezone=args.timezone,
        platform=args.platform,
        locale=args.locale,
        screen_width=args.screen_width,
        screen_height=args.screen_height,
        device_pixel_ratio=args.dpr,
        color_depth=args.color_depth,
    )
    print(f"Updated configuration id={cfg.id} name={cfg.name!r}")


def cmd_duplicate(service: "ConfigurationService", args: "Namespace") -> None:
    cfg = service.duplicate_configuration(args.id, name=args.name)
    print(f"Duplicated configuration {args.id} -> id={cfg.id} name={cfg.name!r}")


def cmd_delete(service: "ConfigurationService", args: "Namespace") -> None:
    service.delete_configuration(args.id)
    print(f"Deleted configuration id={args.id}")


def _screen(cfg: "BrowserConfiguration") -> str:
    if cfg.screen_width and cfg.screen_height:
        return f"{cfg.screen_width}x{cfg.screen_height}"
    return "-"


def _webgl(cfg: "BrowserConfiguration") -> str:
    if cfg.webgl_settings:
        renderer = cfg.webgl_settings.get("renderer")
        vendor = cfg.webgl_settings.get("vendor")
        if renderer:
            return renderer if not vendor else f"{vendor} / {renderer}"
    return "-"


def _hardware(cfg: "BrowserConfiguration") -> str:
    if cfg.hardware_settings:
        cores = cfg.hardware_settings.get("cores")
        memory = cfg.hardware_settings.get("device_memory_gb")
        ram = f"{memory}GB" if memory is not None else "-"
        return f"cores={cores} ram={ram}"
    return "-"


def _hints(cfg: "BrowserConfiguration") -> str:
    hints = cfg.client_hints
    if not hints:
        return "- (absent: regenerate configuration)"
    return (
        f"{hints.get('platform', '-')}/{(hints.get('fullVersion') or '-')}"
    )


def _print_table(table: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    for row in table:
        cells = [
            cell.ljust(widths[i]) if i < len(table) - 1 else cell
            for i, cell in enumerate(row)
        ]
        print("    ".join(cells))