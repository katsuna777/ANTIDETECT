"""Pre-launch diagnostics (the "doctor").

Most inconsistencies a profile can have are repaired automatically right before
launch (:meth:`ProfileService.start_profile`): the User-Agent / Client Hints
follow the installed browser, language / time zone / locale follow the exit IP,
a missing fingerprint is generated. What is left for the doctor is to *explain*:

* ``block`` — launching is impossible until the user acts (no fingerprint at all
  after auto-repair failed).
* ``warn`` — something looks risky but launching works: a proxy that leaks
  headers, an exit country that disagrees with the fingerprint's geo while
  auto-geo is off, a proxy that cannot reach Google.

The module is a pure function over already-gathered facts — no DB, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from antidetect.application.fingerprint.generator import (
    chrome_major,
    ua_chrome_major,
    validate_draft,
)
from antidetect.domain.models.browser_configuration import BrowserConfiguration

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


#: Every timezone the app understands, for dropdowns and validation. The
#: doctor maps each of these to an exit country; anything else is rejected
#: at configuration creation time with a message pointing here.
SUPPORTED_TIMEZONES: tuple[str, ...] = tuple(sorted(TIMEZONE_COUNTRY))


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
                "Profile has no browser fingerprint assigned.",
                "Start the profile again (a fingerprint is generated automatically) "
                "or assign one in the profile settings.",
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
        warns.append(
            DoctorFinding(
                "warn", "incoherent-configuration",
                f"The fingerprint is not self-consistent: {exc}",
                "Regenerate the fingerprint for this profile.",
            )
        )

    facts["ua_major"] = ua_chrome_major(configuration.user_agent or "")
    hints = configuration.client_hints or {}
    facts["hints_major"] = chrome_major(str(hints.get("fullVersion") or "")) if hints else None

    if has_proxy:
        ip_country = (proxy_country_code or "").upper() or None
        tz_country = TIMEZONE_COUNTRY.get(configuration.timezone or "")
        loc_country = locale_country(configuration.locale)
        if ip_country and tz_country and ip_country != tz_country:
            warns.append(
                DoctorFinding(
                    "warn", "geo-timezone-mismatch",
                    f"Proxy exits in {ip_country} but the time zone is {configuration.timezone} "
                    f"({tz_country}); sites read this as location spoofing.",
                    "Turn on automatic language/time zone for this profile.",
                )
            )
        if ip_country and loc_country and ip_country != loc_country:
            warns.append(
                DoctorFinding(
                    "warn", "geo-locale-mismatch",
                    f"Proxy exits in {ip_country} but the locale is {configuration.locale}.",
                    "Turn on automatic language/time zone for this profile.",
                )
            )
        if not ip_country:
            warns.append(
                DoctorFinding(
                    "warn", "proxy-country-unknown",
                    "The proxy's country is unknown (it has not been checked yet).",
                    "Check the proxy once so the profile can match its location.",
                )
            )
        if anonymity == "TRANSPARENT":
            warns.append(
                DoctorFinding(
                    "warn", "proxy-transparent",
                    "This proxy forwards your real IP (X-Forwarded-For).",
                    "Use an elite (anonymous) proxy.",
                )
            )
        elif anonymity in ("ANONYMOUS", "UNKNOWN", None):
            warns.append(
                DoctorFinding(
                    "warn", "proxy-not-elite",
                    f"Proxy anonymity is {anonymity or 'unchecked'} (not ELITE).",
                    "Check the proxy to learn how anonymous it is.",
                )
            )
        if google_reachable is False:
            warns.append(
                DoctorFinding(
                    "warn", "google-unreachable",
                    "Google is not reachable through this proxy.",
                    "Pick another proxy if you need Google sign-in.",
                )
            )
        facts["timezone_country"] = tz_country
        facts["locale_country"] = loc_country

    return DoctorReport(ok=not blocks, blocks=blocks, warns=warns, facts=facts)
