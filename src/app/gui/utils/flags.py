"""Country flag emojis derived from ISO 3166-1 alpha-2 codes.

Geo providers already return a two-letter country code; a regional-indicator
pair turns that code into a flag emoji (e.g. ``DE`` -> ``🇩🇪``) with zero icon
assets. Unknown or malformed codes fall back to the plain text labels.
"""

from __future__ import annotations

_REGIONAL_INDICATOR_A = 0x1F1E6  # 🇦
_LETTER_A = ord("A")

# Some providers and sources report "UK"; the flag that renders is GB's.
_SYNONYMS = {"UK": "GB"}


def country_flag(country_code: str | None) -> str:
    """Return the flag emoji for a two-letter country code, or ``""``."""
    code = (country_code or "").strip().upper()
    code = _SYNONYMS.get(code, code)
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(
        chr(_REGIONAL_INDICATOR_A + ord(ch) - _LETTER_A) for ch in code
    )


def country_label(
    country_code: str | None,
    country: str | None = None,
    *,
    placeholder: str = "—",
) -> str:
    """Render the country as a flag + code (``🇩🇪 DE``) when available,
    otherwise the fallback name or placeholder, uppercased to keep the
    existing display convention."""
    flag = country_flag(country_code)
    text = (country_code or country or placeholder).upper()
    return f"{flag} {text}" if flag else text