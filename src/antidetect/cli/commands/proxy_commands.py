"""Render proxy subcommands: list / refresh / check / check-all / remove-dead."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace

    from antidetect.application.proxy_service import ProxyService
    from antidetect.domain.models.proxy import ProxyWithCheck


def cmd_add(service: "ProxyService", args: "Namespace") -> None:
    """Add your own proxies: ``proxy add host:port:user:pass`` or ``--file list.txt``."""
    from pathlib import Path

    from antidetect.domain.enums.proxy_status import ProxyProtocol

    lines = list(args.proxies or [])
    if args.file:
        lines.extend(Path(args.file).read_text(encoding="utf-8").splitlines())
    protocol = ProxyProtocol[args.type.upper()] if args.type else None
    summary = service.import_text("\n".join(lines), protocol)
    print(f"Added {summary.added} new, {summary.existing} already known, {len(summary.invalid)} unreadable")
    for bad in summary.invalid:
        print(f"  skipped: {bad}")
    if args.check:
        for proxy_id in summary.ids:
            try:
                _, check = service.check_proxy(proxy_id)
                status = check.status.value if check is not None else "?"
                country = (check.country_code or "-") if check is not None else "-"
                latency = f"{check.latency_ms}ms" if check is not None and check.latency_ms else "-"
                print(f"  #{proxy_id}: {status} {country} {latency}")
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"  #{proxy_id}: error {exc}")


def cmd_list(service: "ProxyService", args: "Namespace") -> None:
    rows = service.list_proxies(
        status=args.status,
        sort=args.sort,
        reverse=args.reverse,
        limit=args.limit,
    )
    if not rows:
        print(
            "No proxies yet. Populate the database with: app proxy refresh"
        )
        return
    headers = ("ID", "PROTOCOL", "IP", "PORT", "COUNTRY", "PING", "ANONYMITY", "STATUS")
    table: list[tuple[str, ...]] = [headers]
    for row in rows:
        table.append(_render_row(row))
    _print_table(table)


def _render_row(row: "ProxyWithCheck") -> tuple[str, ...]:
    proxy = row.proxy
    ping = f"{row.latency_ms}ms" if row.latency_ms is not None else "-"
    country = row.country_code or row.country or "-"
    anonymity = row.anonymity.value if row.anonymity else "-"
    return (
        str(proxy.id),
        proxy.protocol.value,
        proxy.host,
        str(proxy.port),
        country,
        ping,
        anonymity,
        proxy.status.value,
    )


def _print_table(table: list[tuple[str, ...]]) -> None:
    widths = [
        max(len(row[i]) for row in table)
        for i in range(len(table[0]))
    ]
    for row in table:
        cells = [
            cell.ljust(widths[i]) if i < len(table) - 1 else cell
            for i, cell in enumerate(row)
        ]
        print("    ".join(cells))


def cmd_check(service: "ProxyService", args: "Namespace") -> None:
    proxy, check = service.check_proxy(args.id)
    if check.status.value == "WORKING":
        ping = f"{check.latency_ms}ms" if check.latency_ms is not None else "-"
        anonymity = check.anonymity.value if check.anonymity else "unknown"
        print(
            f"Proxy id={proxy.id} {proxy.protocol.value}://{proxy.host_port} "
            f"status=WORKING ping={ping} external_ip={check.external_ip} "
            f"country={check.country_code or check.country or '-'} "
            f"anonymity={anonymity}"
        )
    else:
        print(
            f"Proxy id={proxy.id} {proxy.protocol.value}://{proxy.host_port} "
            f"status=ERROR" + (f" ({check.error})" if check.error else "")
        )


def cmd_check_all(service: "ProxyService", args: "Namespace") -> None:
    summary = service.check_all(
        workers=args.workers,
        timeout=args.timeout,
        force=args.stale_minutes is None,
        stale_minutes=args.stale_minutes or 60,
    )
    print(
        f"Checked {summary.checked} proxy(-ies): "
        f"{summary.working} working, {summary.failed} failed, "
        f"{summary.dead} dead in {summary.elapsed_seconds:.1f}s"
    )


def cmd_refresh(service: "ProxyService", args: "Namespace") -> None:
    summary = service.refresh(
        timeout=args.timeout,
        workers=args.workers,
        max_failures=args.max_failures,
        stale_minutes=args.stale_minutes,
        collect=not args.no_collect,
        force=args.force,
    )
    for error in summary.source_errors:
        print(f"source error: {error}", file=sys.stderr)
    print(
        f"Collected {summary.collected} new candidate(-ies), "
        f"{summary.created} inserted."
    )
    print(
        f"Checked {summary.checked} proxy(-ies): "
        f"{summary.working} working, {summary.failed} failed, "
        f"{summary.dead} dead. Removed {summary.removed} in "
        f"{summary.elapsed_seconds:.1f}s"
    )


def cmd_remove_dead(service: "ProxyService", args: "Namespace") -> None:
    removed = service.remove_dead()
    print(f"Removed {removed} dead proxy(-ies).")