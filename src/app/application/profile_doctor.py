"""Pre-launch consistency diagnostics (the "doctor" gate).

Google rejects a profile with "browser is not secure" when the fingerprint
parts contradict each other (UA Chrome/124 vs real binary 152, Windows UA vs
Apple WebGL, US timezone vs DE exit IP) or when the proxy leaks/bypasses.
This module is a pure function over already-gathered facts — no DB, no
network — so it is trivially testable and reusable by both the CLI
(``app profile doctor``) and the fail-closed gate inside
``ProfileService.start_profile``.

Severity contract (iron, fail-closed):

* ``block`` — launching anyway provably reproduces the Google error page.
  ``start_profile`` raises instead of launching.
* ``warn`` — elevated risk, launch proceeds and the warning is logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.application.configuration_generator import (
    LEGACY_CHROME_MAJORS,
    chrome_major,
    ua_chrome_major,
    validate_draft,
)
from app.domain.models.browser_configuration import BrowserConfiguration

# Timezone -> ISO country for every zone the generator can emit. Explicit on
# purpose: stdlib zoneinfo carries no country mapping and guessing from the
# region prefix alone (America/* -> US) mislabels e.g. America/Sao_Paulo.
TIMEZONE_COUNTRY: dict[str, str] = {
    "America/New_York": "US",
    "America/Chicago": "US",
    "America/Denver": "US",
    "America/Los_Angeles": "US",
    "America/Sao_Paulo": "BR",
    "Europe/London": "GB",
    "Europe/Berlin": "DE",
    "Europe/Paris": "FR",
    "Europe/Madrid": "ES",
    "Europe/Rome": "IT",
    "Europe/Amsterdam": "NL",
    "Europe/Warsaw": "PL",
    "Europe/Moscow": "RU",
    "Asia/Yekaterinburg": "RU",
    "Europe/Kyiv": "UA",
    "Europe/Istanbul": "TR",
    "Europe/Prague": "CZ",
    "Europe/Stockholm": "SE",
    "Europe/Helsinki": "FI",
    "Europe/Copenhagen": "DK",
    "Europe/Bucharest": "RO",
    "Europe/Budapest": "HU",
    "Asia/Tokyo": "JP",
    "Asia/Shanghai": "CN",
    "Asia/Seoul": "KR",
    "America/Toronto": "CA",
    "Australia/Sydney": "AU",
    "Europe/Zurich": "CH",
    "Europe/Vienna": "AT",
    "Europe/Brussels": "BE",
    "Europe/Dublin": "IE",
    "Europe/Lisbon": "PT",
    "Europe/Athens": "GR",
    "Europe/Oslo": "NO",
    "Europe/Bratislava": "SK",
    "Europe/Sofia": "BG",
    "Asia/Almaty": "KZ",
    "America/Mexico_City": "MX",
    "America/Argentina/Buenos_Aires": "AR",
    "Asia/Kolkata": "IN",
    "Asia/Singapore": "SG",
}


@dataclass(frozen=True)
class DoctorFinding:
    severity: str  # "block" | "warn"
    code: str
    message: str
    fix: str


@dataclass
class DoctorReport:
    ok: bool
    blocks: list[DoctorFinding] = field(default_factory=list)
    warns: list[DoctorFinding] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)


def locale_country(locale: str | None) -> str | None:
    """ISO country from a locale tag (``en-US`` -> ``US``)."""
    if not locale:
        return None
    tail = locale.replace("_", "-").rsplit("-", 1)
    if len(tail) != 2 or len(tail[1]) != 2 or not tail[1].isalpha():
        return None
    return tail[1].upper()


def diagnose(
    configuration: BrowserConfiguration | None,
    *,
    binary_major: int | None = None,
    proxy_country_code: str | None = None,
    anonymity: str | None = None,
    google_reachable: bool | None = None,
    has_proxy: bool = False,
) -> DoctorReport:
    """Check one launch configuration against live facts."""
    blocks: list[DoctorFinding] = []
    warns: list[DoctorFinding] = []
    facts: dict[str, Any] = {
        "binary_major": binary_major,
        "proxy_country": (proxy_country_code or "").upper() or None,
        "anonymity": anonymity,
        "google_reachable": google_reachable,
    }

    if configuration is None:
        blocks.append(
            DoctorFinding(
                "block", "no-configuration",
                "Profile has no browser configuration assigned.",
                "Assign one with: app profile update <id> --configuration-id <cfg>",
            )
        )
        return DoctorReport(ok=False, blocks=blocks, warns=warns, facts=facts)

    try:
        validate_draft(
            {
                "user_agent": configuration.user_agent,
                "platform": configuration.platform,
                "language": configuration.language,
                "locale": configuration.locale,
                "timezone": configuration.timezone,
                "screen_width": configuration.screen_width,
                "screen_height": configuration.screen_height,
                "device_pixel_ratio": configuration.device_pixel_ratio,
                "color_depth": configuration.color_depth,
                "webgl_settings": configuration.webgl_settings,
                "hardware_settings": configuration.hardware_settings,
                "client_hints": configuration.client_hints,
            }
        )
    except ValueError as exc:
        blocks.append(
            DoctorFinding(
                "block", "incoherent-configuration",
                f"Incoherent configuration: {exc}",
                "Regenerate it: app config generate --platform <platform>",
            )
        )

    ua_major = ua_chrome_major(configuration.user_agent or "")
    facts["ua_major"] = ua_major
    if ua_major is not None and ua_major in LEGACY_CHROME_MAJORS:
        blocks.append(
            DoctorFinding(
                "block", "legacy-user-agent",
                f"User-Agent Chrome/{ua_major} is legacy (real Chrome is "
                f"{binary_major or 'much newer'}); Google flags the version gap.",
                "Delete it and regenerate: app config generate --platform windows",
            )
        )

    hints = configuration.client_hints or {}
    hint_major = chrome_major(str(hints.get("fullVersion") or "")) if hints else None
    facts["hints_major"] = hint_major
    if ua_major is not None and hint_major is not None and ua_major != hint_major:
        blocks.append(
            DoctorFinding(
                "block", "ua-hints-mismatch",
                f"User-Agent Chrome/{ua_major} contradicts Client Hints {hints.get('fullVersion')}.",
                "Regenerate the configuration so UA and hints are atomic.",
            )
        )
    if hints and not configuration.user_agent:
        blocks.append(
            DoctorFinding(
                "block", "hints-without-ua",
                "Client Hints are stored without a User-Agent; stealth injection refuses partial spoofs.",
                "Regenerate the configuration coherently.",
            )
        )
    if configuration.user_agent and not hints:
        warns.append(
            DoctorFinding(
                "warn", "hints-missing",
                "No Client Hints stored: CDP falls back to UA-derived defaults.",
                "Regenerate the configuration to store full hints.",
            )
        )

    if ua_major is not None:
        if binary_major is None:
            warns.append(
                DoctorFinding(
                    "warn", "binary-version-unknown",
                    "Browser binary version could not be probed; UA/binary drift cannot be verified.",
                    "Check the binary manually: <binary> --version",
                )
            )
        elif abs(ua_major - binary_major) > 1:
            blocks.append(
                DoctorFinding(
                    "block", "ua-binary-drift",
                    f"User-Agent Chrome/{ua_major} vs installed Chrome/{binary_major}: "
                    "Sec-CH-UA will contradict the UA and Google will block login.",
                    f"Regenerate for Chrome/{binary_major} or update the browser.",
                )
            )

    if has_proxy:
        ip_country = (proxy_country_code or "").upper() or None
        tz_country = TIMEZONE_COUNTRY.get(configuration.timezone or "")
        loc_country = locale_country(configuration.locale)
        if ip_country and tz_country and ip_country != tz_country:
            blocks.append(
                DoctorFinding(
                    "block", "geo-timezone-mismatch",
                    f"Proxy exits in {ip_country} but timezone is {configuration.timezone} "
                    f"({tz_country}); Google treats this as location spoofing.",
                    "Use a proxy in the timezone country or regenerate the configuration for it.",
                )
            )
        if ip_country and loc_country and ip_country != loc_country:
            blocks.append(
                DoctorFinding(
                    "block", "geo-locale-mismatch",
                    f"Proxy exits in {ip_country} but locale is {configuration.locale}; "
                    "language/region contradicts the exit IP.",
                    "Align locale with the proxy country.",
                )
            )
        if not ip_country:
            warns.append(
                DoctorFinding(
                    "warn", "proxy-country-unknown",
                    "Proxy exit country is unknown (no successful check yet).",
                    "Run: app proxy check <id>",
                )
            )
        if anonymity == "TRANSPARENT":
            blocks.append(
                DoctorFinding(
                    "block", "proxy-transparent",
                    "Proxy is TRANSPARENT: it forwards your real IP (X-Forwarded-For).",
                    "Use an elite proxy for Google login.",
                )
            )
        elif anonymity in ("ANONYMOUS", "UNKNOWN", None):
            warns.append(
                DoctorFinding(
                    "warn", "proxy-not-elite",
                    f"Proxy anonymity is {anonymity or 'unchecked'} (not ELITE).",
                    "Prefer an elite proxy for Google login; run: app proxy check <id>",
                )
            )
        if google_reachable is False:
            blocks.append(
                DoctorFinding(
                    "block", "google-unreachable",
                    "Google (accounts.google.com) is unreachable through this proxy.",
                    "Use a proxy with Google reachability or browse it unproxied.",
                )
            )
        facts["timezone_country"] = tz_country
        facts["locale_country"] = loc_country

    return DoctorReport(ok=not blocks, blocks=blocks, warns=warns, facts=facts)
