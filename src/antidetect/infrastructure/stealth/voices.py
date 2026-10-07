"""The speech-synthesis voices a real Chrome lists on each OS for a given UI language.

``speechSynthesis.getVoices()`` answers from the *host*: a Windows profile on a Mac would
list Zarvox and Trinoids (a hard OS tell), and its default voice speaks the host's language
while ``Intl`` says German (CreepJS flags exactly that mismatch and paints the Timezone and
Intl hashes red). The in-page payload therefore replaces the list with the one built here.

Shapes verified against Chrome 154 on macOS 15 (names, languages, ``voiceURI == name``,
local voices first, then the remote "Google …" voices); Windows names follow the voices
Windows 10/11 ships per display language.
"""

from __future__ import annotations

# (name, lang) — Chrome's remote voices, identical on every desktop OS (note the real no-break spaces).
GOOGLE_VOICES: tuple[tuple[str, str], ...] = (
    ("Google Deutsch", "de-DE"),
    ("Google US English", "en-US"),
    ("Google UK English Female", "en-GB"),
    ("Google UK English Male", "en-GB"),
    ("Google español", "es-ES"),
    ("Google español de Estados Unidos", "es-US"),
    ("Google français", "fr-FR"),
    ("Google हिन्दी", "hi-IN"),
    ("Google Bahasa Indonesia", "id-ID"),
    ("Google italiano", "it-IT"),
    ("Google 日本語", "ja-JP"),
    ("Google 한국의", "ko-KR"),
    ("Google Nederlands", "nl-NL"),
    ("Google polski", "pl-PL"),
    ("Google português do Brasil", "pt-BR"),
    ("Google русский", "ru-RU"),
    ("Google 普通话（中国大陆）", "zh-CN"),
    ("Google 粤語（香港）", "zh-HK"),
    ("Google 國語（臺灣）", "zh-TW"),
)

# ----------------------------------------------------------------------------- macOS 15

_MAC_PLAIN: dict[str, tuple[str, ...]] = {
    "ar-001": ("Maged",), "bg-BG": ("Daria",), "ca-ES": ("Montse",), "cs-CZ": ("Zuzana",),
    "da-DK": ("Sara",), "de-DE": ("Anna", "Helena", "Martin"), "el-GR": ("Melina",),
    "en-AU": ("Catherine", "Gordon", "Karen"), "en-GB": ("Arthur", "Martha"), "en-IE": ("Moira",),
    "en-IN": ("Rishi",),
    "en-US": ("Aaron", "Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Fred",
              "Good News", "Jester", "Junior", "Kathy", "Nicky", "Organ", "Ralph", "Samantha",
              "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox"),
    "en-ZA": ("Tessa",), "es-ES": ("Mónica",), "es-MX": ("Paulina",), "fi-FI": ("Satu",),
    "fr-CA": ("Amélie",), "fr-FR": ("Jacques", "Marie", "Thomas"), "he-IL": ("Carmit",),
    "hi-IN": ("Lekha",), "hr-HR": ("Lana",), "hu-HU": ("Tünde",), "id-ID": ("Damayanti",),
    "it-IT": ("Alice",), "ja-JP": ("Hattori", "Kyoko", "O-Ren"), "ko-KR": ("Yuna",),
    "ms-MY": ("Amira",), "nb-NO": ("Nora",), "nl-BE": ("Ellen",), "nl-NL": ("Xander",),
    "pl-PL": ("Zosia",), "pt-BR": ("Luciana",), "pt-PT": ("Joana",), "ro-RO": ("Ioana",),
    "ru-RU": ("Milena",), "sk-SK": ("Laura",), "sl-SI": ("Tina",), "sv-SE": ("Alva",),
    "ta-IN": ("Vani",), "th-TH": ("Kanya",), "tr-TR": ("Yelda",), "uk-UA": ("Lesya",),
    "vi-VN": ("Linh",), "zh-CN": ("Li-Mu", "Ting-Ting", "Yu-shu"), "zh-HK": ("Sin-ji",),
    "zh-TW": ("Mei-Jia",),
}
_MAC_SUFFIX: dict[str, str] = {
    "de-DE": "German (Germany)", "en-GB": "English (UK)", "en-US": "English (US)",
    "es-ES": "Spanish (Spain)", "es-MX": "Spanish (Mexico)", "fi-FI": "Finnish (Finland)",
    "fr-CA": "French (Canada)", "fr-FR": "French (France)", "it-IT": "Italian (Italy)",
    "ja-JP": "Japanese (Japan)", "ko-KR": "Korean (South Korea)", "pt-BR": "Portuguese (Brazil)",
    "zh-CN": "Chinese (China mainland)", "zh-TW": "Chinese (Taiwan)",
}
_MAC_EXTRA_LANGS = ("en-GB", "es-ES", "es-MX", "fi-FI", "fr-CA", "fr-FR", "it-IT", "ja-JP", "ko-KR",
                    "pt-BR", "zh-CN", "zh-TW", "de-DE", "en-US")  # the 14 voices each "character" comes in
_MAC_CHARACTERS = ("Eddy", "Flo", "Grandma", "Grandpa", "Reed", "Rocko", "Sandy", "Shelley")
# The system voice macOS picks for a language when it is not simply "the first one".
_MAC_DEFAULT = {
    "en-US": "Samantha", "en-GB": "Daniel (English (UK))", "de-DE": "Anna", "fr-FR": "Thomas",
    "es-ES": "Mónica", "zh-CN": "Ting-Ting", "ja-JP": "Kyoko",
}


def _mac_local() -> list[tuple[str, str]]:
    voices = [(name, lang) for lang, names in _MAC_PLAIN.items() for name in names]
    for character in _MAC_CHARACTERS:
        for lang in _MAC_EXTRA_LANGS:
            if character == "Reed" and lang == "fr-FR":
                continue  # the one gap in the real list
            voices.append((f"{character} ({_MAC_SUFFIX[lang]})", lang))
    voices.append(("Daniel (English (UK))", "en-GB"))
    voices.append(("Daniel (French (France))", "fr-FR"))
    return sorted(voices, key=lambda v: v[0].casefold())


# ------------------------------------------------------------------------------- Windows

_EN_US = "English (United States)"
_WIN_US = tuple((f"Microsoft {n} - {_EN_US}", "en-US") for n in ("David", "Mark", "Zira"))
# locale -> (language label, first names); voices Windows 10/11 ships for that display language.
_WIN: dict[str, tuple[str, tuple[str, ...]]] = {
    "bg-BG": ("Bulgarian (Bulgaria)", ("Ivan",)),
    "cs-CZ": ("Czech (Czech Republic)", ("Jakub",)),
    "da-DK": ("Danish (Denmark)", ("Helle",)),
    "de-AT": ("German (Austria)", ("Michael",)),
    "de-CH": ("German (Switzerland)", ("Karsten",)),
    "de-DE": ("German (Germany)", ("Hedda", "Katja", "Stefan")),
    "el-GR": ("Greek (Greece)", ("Stefanos",)),
    "en-AU": ("English (Australia)", ("Catherine", "James")),
    "en-CA": ("English (Canada)", ("Linda", "Richard")),
    "en-GB": ("English (United Kingdom)", ("George", "Hazel", "Susan")),
    "en-IE": ("English (Ireland)", ("Sean",)),
    "en-IN": ("English (India)", ("Heera", "Ravi")),
    "es-ES": ("Spanish (Spain)", ("Helena", "Laura", "Pablo")),
    "es-MX": ("Spanish (Mexico)", ("Raul", "Sabina")),
    "fi-FI": ("Finnish (Finland)", ("Heidi",)),
    "fr-FR": ("French (France)", ("Hortense", "Julie", "Paul")),
    "hu-HU": ("Hungarian (Hungary)", ("Szabolcs",)),
    "it-IT": ("Italian (Italy)", ("Cosimo", "Elsa")),
    "ja-JP": ("Japanese (Japan)", ("Ayumi", "Haruka", "Ichiro")),
    "ko-KR": ("Korean (Korea)", ("Heami",)),
    "nb-NO": ("Norwegian (Bokmål, Norway)", ("Jon",)),
    "nl-BE": ("Dutch (Belgium)", ("Bart",)),
    "nl-NL": ("Dutch (Netherlands)", ("Frank",)),
    "pl-PL": ("Polish (Poland)", ("Paulina",)),
    "pt-BR": ("Portuguese (Brazil)", ("Daniel", "Maria")),
    "pt-PT": ("Portuguese (Portugal)", ("Helia",)),
    "ro-RO": ("Romanian (Romania)", ("Andrei",)),
    "ru-RU": ("Russian (Russia)", ("Irina", "Pavel")),
    "sk-SK": ("Slovak (Slovakia)", ("Filip",)),
    "sv-SE": ("Swedish (Sweden)", ("Bengt",)),
    "tr-TR": ("Turkish (Turkey)", ("Tolga",)),
    "uk-UA": ("Ukrainian (Ukraine)", ("Polina",)),
    "zh-CN": ("Chinese (Simplified, PRC)", ("Huihui", "Kangkang", "Yaoyao")),
}
_WIN["ru-KZ"] = _WIN["ru-RU"]  # Windows has no Kazakh-Russian pack: the Russian voices answer


def _primary(locale: str) -> str:
    return (locale or "").replace("_", "-").split("-")[0].lower()


def _closest(locale: str, table: dict) -> str | None:
    """The table key that serves ``locale``: exact match, else the same language."""
    if locale in table:
        return locale
    wanted = _primary(locale)
    return next((key for key in table if _primary(key) == wanted), None)


def _windows(locale: str) -> list[tuple[str, str, bool, bool]]:
    local = list(_WIN_US)
    default_name: str | None = None
    if locale in _WIN:
        key = locale
    elif _primary(locale) == "en":
        key = None  # any other English region speaks with the US voices every Windows ships
        default_name = _WIN_US[0][0]  # David
    else:
        key = _closest(locale, _WIN)
    if key is not None:
        label, names = _WIN[key]
        lang = "ru-RU" if key == "ru-KZ" else key
        local += [(f"Microsoft {n} - {label}", lang) for n in names]
        default_name = f"Microsoft {names[0]} - {label}"
    elif locale == "en-US":
        default_name = _WIN_US[0][0]
    local.sort(key=lambda v: v[0].casefold())
    return [(n, l, True, n == default_name) for n, l in local]


def _mac(locale: str) -> list[tuple[str, str, bool, bool]]:
    local = _mac_local()
    if locale in _MAC_PLAIN:
        key = locale
    elif _primary(locale) == "en":
        key = "en-US"  # other English regions: macOS speaks with the US voice
    else:
        key = next((k for k in sorted(_MAC_PLAIN) if _primary(k) == _primary(locale)), None)
    default_name = (_MAC_DEFAULT.get(key) or _MAC_PLAIN[key][0]) if key is not None else None
    return [(n, l, True, n == default_name) for n, l in local]


def voices_for(platform_key: str | None, locale: str | None) -> list[tuple[str, str, bool, bool]]:
    """``(name, lang, localService, default)`` in the order Chrome lists them (local, then remote).

    At most one voice is the default and only when the OS ships a voice for the profile's
    language — otherwise there is none, which is what a detector cannot flag.
    """
    locale = (locale or "").replace("_", "-")
    if platform_key == "windows":
        local = _windows(locale)
    elif platform_key == "macos":
        local = _mac(locale)
    else:  # Linux has no system voices unless speech-dispatcher is installed: only the remote ones
        local = []
    return local + [(name, lang, False, False) for name, lang in GOOGLE_VOICES]


def js_voices(platform_key: str | None, locale: str | None) -> list[dict]:
    """The compact form handed to the payload."""
    return [{"n": n, "l": l, "s": s, "d": d} for n, l, s, d in voices_for(platform_key, locale)]
