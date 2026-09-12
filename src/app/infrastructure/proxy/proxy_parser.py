"""Parsing and normalization of raw proxy list lines.

Supported input formats (one endpoint per line):

* ``IP:PORT``
* ``protocol://IP:PORT``
* ``username:password@IP:PORT``
* ``protocol://username:password@IP:PORT``

``protocol`` may be ``http``, ``https`` or ``socks5``. Unknown schemes and
unsupported protocols (e.g. ``socks4``) are rejected by ``parse_entry``; the
collector simply skips them instead of crashing the whole batch.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Iterable, Optional
from urllib.parse import unquote

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.models.proxy_entry import ProxyEntry

_SCHEME_ALIASES = {
    "http": ProxyProtocol.HTTP,
    "https": ProxyProtocol.HTTPS,
    "socks5": ProxyProtocol.SOCKS5,
    "socks5h": ProxyProtocol.SOCKS5,
}

_DEFAULT_PORT = {
    ProxyProtocol.HTTP: 80,
    ProxyProtocol.HTTPS: 443,
    ProxyProtocol.SOCKS5: 1080,
}

# Host may be an IPv4, a bracketed IPv6 or a DNS hostname. Username/password
# never contain '@', ':' or '/', which mirrors what public lists actually ship.
_LINE_RE = re.compile(
    r"^\s*"
    r"(?:(?P<scheme>[a-z][a-z0-9+.-]*)://)?"
    r"(?:(?P<user>[^:@/\s]+):(?P<password>[^@/\s]*)@)?"
    r"(?P<host>\[[^\]]+\]|[^:@/\s]+)"
    r"(?::(?P<port>[0-9]{1,5}))"
    r"\s*$"
)

_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_MAX_PORT = 65535


def parse_line(
    line: str,
    default_protocol: ProxyProtocol | None = None,
) -> Optional[ProxyEntry]:
    """Parse a raw line into a normalized entry, or return ``None``.

    ``source`` is left ``None`` here on purpose; the collector stamps it per
    source line via :func:`stamp_source`. When the line omits the scheme,
    ``default_protocol`` (e.g. the protocol declared by the source list) is
    used; otherwise the entry defaults to HTTP.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = _LINE_RE.match(stripped)
    if match is None:
        return None

    scheme_raw = match.group("scheme")
    scheme = _SCHEME_ALIASES.get(scheme_raw.lower()) if scheme_raw else None
    if scheme_raw is not None and scheme is None:
        return None  # known-but-unsupported or unknown scheme

    host = _normalize_host(match.group("host"))
    if host is None:
        return None

    port_raw = match.group("port")
    if port_raw is None:
        if scheme is None:
            return None
        port = _DEFAULT_PORT[scheme]
    else:
        port = int(port_raw)
        if not (1 <= port <= _MAX_PORT):
            return None

    username = _maybe_unquote(match.group("user"))
    password = _maybe_unquote(match.group("password"))
    if scheme is None:
        scheme = default_protocol or ProxyProtocol.HTTP
    return ProxyEntry(
        protocol=scheme,
        host=host,
        port=port,
        username=username,
        password=password,
    )


def _normalize_host(raw: str) -> Optional[str]:
    host = raw.strip().strip("[]").lower()
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        return None  # looks like an IPv4 but is not a valid one
    if _HOSTNAME_RE.match(host):
        return host
    return None


def _maybe_unquote(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return unquote(value)


def stamp_source(entry: ProxyEntry, source: str | None) -> ProxyEntry:
    """Stamp the originating source; the already-stamped source wins."""
    if source is None or entry.source is not None:
        return entry
    return ProxyEntry(
        protocol=entry.protocol,
        host=entry.host,
        port=entry.port,
        username=entry.username,
        password=entry.password,
        source=source,
    )


def dedupe(entries: Iterable[ProxyEntry]) -> list[ProxyEntry]:
    """Drop duplicates, keeping the first occurrence of each endpoint."""
    seen: set[tuple[str, str, int]] = set()
    result: list[ProxyEntry] = []
    for entry in entries:
        key = entry.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result