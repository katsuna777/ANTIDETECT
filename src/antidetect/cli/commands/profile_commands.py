from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace

    from antidetect.application.profile_service import ProfileService


def _pretty(dt) -> str:
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _proxy_label(details) -> str:
    if details.proxy_check is None:
        return "-"
    proxy = details.proxy_check.proxy
    return f"{proxy.id}:{proxy.host}:{proxy.port}"


def _privacy_from(args: "Namespace") -> dict:
    """The protection switches the command line asked for (empty when it asked for none)."""
    chosen: dict = {}
    if getattr(args, "webrtc", None):
        chosen["webrtc"] = args.webrtc
    if getattr(args, "theme", None):
        chosen["theme"] = args.theme
    for noun in ("canvas", "audio"):
        off, on = getattr(args, f"no_{noun}_noise", False), getattr(args, f"{noun}_noise", False)
        if off and on:
            raise ValueError(f"--{noun}-noise and --no-{noun}-noise contradict each other")
        if off or on:
            chosen[f"noise_{noun}"] = on
    return chosen


def cmd_create(service: "ProfileService", args: "Namespace") -> None:
    from antidetect.application.fingerprint import privacy

    tags = [t.strip() for t in (getattr(args, "tags", None) or "").split(",") if t.strip()]
    profile = service.create_profile(
        args.name,
        configuration_id=args.configuration_id,
        proxy_id=args.proxy_id,
        auto_config=not args.no_auto_config,
        platform=getattr(args, "platform", None),
        notes=getattr(args, "notes", None) or "",
        tags=tags,
        geo_auto=not getattr(args, "no_geo_auto", False),
        start_url=getattr(args, "start_url", None),
        privacy_settings=privacy.minimal(_privacy_from(args)) or None,
    )
    print(f"Created profile id={profile.id} name={profile.name!r} path={profile.profile_path}")
    _print_auto_config(service, profile.id)


def cmd_show(service: "ProfileService", args: "Namespace") -> None:
    details = service.get_profile_details(args.id)
    profile = details.profile
    print("PROFILE")
    print(f"  ID:            {profile.id}")
    print(f"  NAME:          {profile.name}")
    print(f"  STATUS:        {profile.status.value}")
    print(f"  PROFILE_PATH:  {profile.profile_path}")
    print(f"  CREATED:       {_pretty(profile.created_at)}")
    print(f"  UPDATED:       {_pretty(profile.updated_at)}")
    print(f"  LAST_STARTED:  {_pretty(profile.last_started_at)}")
    print(f"  LAST_STOPPED:  {_pretty(profile.last_stopped_at)}")
    print(f"  PID:           {profile.pid or '-'}")
    print("PROXY")
    proxy_check = details.proxy_check
    if proxy_check is None:
        print("  None (unproxied browsing)")
    else:
        proxy = proxy_check.proxy
        print(f"  ID:        {proxy.id}")
        print(f"  ENDPOINT:  {proxy.protocol.value}://{proxy.host}:{proxy.port}")
        print(f"  STATUS:    {proxy.status.value}")
        print(f"  IP:        {proxy_check.external_ip or '-'}")
        print(f"  COUNTRY:   {proxy_check.country_code or proxy_check.country or '-'}")
        print(
            f"  PING:      {f'{proxy_check.latency_ms}ms' if proxy_check.latency_ms is not None else '-'}"
        )
        print(
            f"  ANONYMITY: {proxy_check.anonymity.value if proxy_check.anonymity else '-'}"
        )
    print("CONFIGURATION")
    configuration = details.configuration
    if configuration is None:
        print("  None (start requires a configuration)")
    else:
        print(f"  ID:          {configuration.id}")
        print(f"  NAME:        {configuration.name}")
        print(f"  USER_AGENT:  {configuration.user_agent or '-'}")
        print(f"  PLATFORM:    {configuration.platform or '-'}")
        print(f"  LANG:        {configuration.language_tag or '-'}")
        print(f"  LOCALE:      {configuration.locale or '-'}")
        print(f"  TIMEZONE:    {configuration.timezone or '-'}")
        print(
            f"  SCREEN:      "
            f"{configuration.screen_width or '-'}x{configuration.screen_height or '-'} "
            f"DPR={configuration.device_pixel_ratio or '-'} "
            f"DEPTH={configuration.color_depth or '-'}"
        )
        from antidetect.application.fingerprint import privacy

        shown = privacy.resolve(configuration.privacy_settings)
        print(
            f"  PROTECTION:  webrtc={shown['webrtc']} theme={shown['theme']} "
            f"canvas-noise={'on' if shown['noise_canvas'] else 'off'} "
            f"audio-noise={'on' if shown['noise_audio'] else 'off'}"
        )
        hints = configuration.client_hints or {}
        print(
            f"  HINTS:       "
            f"{hints.get('platform', '-') if hints else '-'}/"
            f"{hints.get('fullVersion', '-') if hints else '-'}"
        )


def cmd_list(service: "ProfileService", args: "Namespace") -> None:
    details_list = service.list_profiles_details()
    if not details_list:
        print("No profiles yet. Create one with: app profile create \"Name\"")
        return
    rows: list[tuple[str, ...]] = [("ID", "NAME", "PROXY", "IP", "COUNTRY", "PING", "STATUS")]
    for details in details_list:
        profile = details.profile
        proxy_check = details.proxy_check
        if proxy_check is None:
            proxy, ip, country, ping = "-", "-", "-", "-"
        else:
            proxy = _proxy_label(details)
            ip = proxy_check.external_ip or "-"
            country = proxy_check.country_code or proxy_check.country or "-"
            ping = f"{proxy_check.latency_ms}ms" if proxy_check.latency_ms is not None else "-"
        rows.append(
            (str(profile.id), profile.name, proxy, ip, country, ping, profile.status.value)
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for row in rows:
        line = "    ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        print(line)


def cmd_update(service: "ProfileService", args: "Namespace") -> None:
    proxy_id = args.proxy_id
    if args.remove_proxy:
        proxy_id = None
    profile = service.update_profile(
        args.id,
        name=args.name,
        configuration_id=args.configuration_id,
        proxy_id=proxy_id,
        auto_config=not args.no_auto_config,
    )
    switches = _privacy_from(args)
    if switches:
        service.set_privacy(profile.id, switches)
    print(f"Updated profile id={profile.id} name={profile.name!r} proxy_id={profile.proxy_id}")
    _print_auto_config(service, profile.id)


def cmd_proxy(service: "ProfileService", args: "Namespace") -> None:
    if args.remove:
        profile = service.remove_proxy(args.id)
        print(f"Removed proxy from profile id={profile.id}")
        return
    if args.set is None:
        raise ValueError("specify --set <proxy-id> or --remove")
    profile = service.assign_proxy(args.id, args.set, auto_config=not args.no_auto_config)
    print(f"Profile id={profile.id} now uses proxy id={profile.proxy_id}")
    _print_auto_config(service, profile.id)


def _print_auto_config(service: "ProfileService", profile_id: int) -> None:
    """Show the fingerprint currently matched to the profile's proxy."""
    try:
        details = service.get_profile_details(profile_id)
    except Exception:
        return
    configuration = details.configuration
    proxy_check = details.proxy_check
    if configuration is None or proxy_check is None:
        return
    country = proxy_check.country_code or proxy_check.country or "-"
    print(
        f"  Fingerprint: {configuration.name!r} "
        f"({configuration.locale or '-'}/{configuration.timezone or '-'}) "
        f"matched to proxy country {country}"
    )


def cmd_doctor(service: "ProfileService", args: "Namespace") -> None:
    from antidetect.domain.errors import ChromiumError

    report = service.diagnose_profile(args.id, probe_google=not args.no_probe)
    print(f"DOCTOR profile id={args.id}: {'OK' if report.ok else 'BLOCKED'}")
    for name, findings in (("BLOCK", report.blocks), ("WARN", report.warns)):
        for finding in findings:
            print(f"  [{name}] {finding.code}: {finding.message}")
            print(f"         Fix: {finding.fix}")
    if not report.blocks and not report.warns:
        print("  No issues found.")
    facts = ", ".join(f"{key}={value}" for key, value in report.facts.items())
    print(f"  FACTS: {facts}")
    if not report.ok:
        raise ChromiumError(
            f"Profile id={args.id} has {len(report.blocks)} blocking issue(s); "
            "resolve them before starting."
        )


def cmd_start(service: "ProfileService", args: "Namespace") -> None:
    import time

    profile = service.start_profile(args.id)
    print(f"Started profile id={profile.id} pid={profile.pid}")
    if getattr(args, "detach", False) or not service.is_protected(profile.id):
        return
    # The fingerprint layer runs inside this process; if it exits, tabs opened
    # later would no longer be patched. Stay here until the browser closes.
    print("Fingerprint protection is active while this window stays open. Ctrl+C stops the browser.")
    try:
        while service.get_profile(profile.id).status.value == "RUNNING":
            time.sleep(1.0)
    except KeyboardInterrupt:
        service.stop_profile(profile.id)
        print(f"Stopped profile id={profile.id}")


def cmd_stop(service: "ProfileService", args: "Namespace") -> None:
    profile = service.stop_profile(args.id)
    print(f"Stopped profile id={profile.id}")


def cmd_restart(service: "ProfileService", args: "Namespace") -> None:
    profile = service.restart_profile(args.id)
    print(f"Restarted profile id={profile.id} pid={profile.pid}")


def cmd_duplicate(service: "ProfileService", args: "Namespace") -> None:
    profile = service.duplicate_profile(args.id, name=args.name)
    print(f"Duplicated profile {args.id} -> id={profile.id} name={profile.name!r}")


def cmd_delete(service: "ProfileService", args: "Namespace") -> None:
    if getattr(args, "permanent", False):
        service.delete_profile(args.id)
        print(f"Deleted profile id={args.id} for good")
        return
    service.trash_profile(args.id)
    print(f"Moved profile id={args.id} to the trash (restore it with: profile restore {args.id})")


def cmd_restore(service: "ProfileService", args: "Namespace") -> None:
    profile = service.restore_profile(args.id)
    print(f"Restored profile id={profile.id} name={profile.name!r}")


def cmd_trash(service: "ProfileService", args: "Namespace") -> None:
    trashed = service.list_trashed_profiles()
    if not trashed:
        print("The trash is empty.")
        return
    rows = [("ID", "NAME", "DELETED")] + [(str(p.id), p.name, _pretty(p.deleted_at)) for p in trashed]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for row in rows:
        print("    ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))