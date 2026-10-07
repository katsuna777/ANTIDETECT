"""Country names (English / Russian) for the codes the app understands."""

from __future__ import annotations

from antidetect.i18n import is_ru

_NAMES: dict[str, tuple[str, str]] = {
    "US": ("United States", "США"), "GB": ("United Kingdom", "Великобритания"),
    "DE": ("Germany", "Германия"), "FR": ("France", "Франция"), "ES": ("Spain", "Испания"),
    "IT": ("Italy", "Италия"), "NL": ("Netherlands", "Нидерланды"), "PL": ("Poland", "Польша"),
    "BR": ("Brazil", "Бразилия"), "RU": ("Russia", "Россия"), "UA": ("Ukraine", "Украина"),
    "TR": ("Türkiye", "Турция"), "CZ": ("Czechia", "Чехия"), "SE": ("Sweden", "Швеция"),
    "FI": ("Finland", "Финляндия"), "DK": ("Denmark", "Дания"), "RO": ("Romania", "Румыния"),
    "HU": ("Hungary", "Венгрия"), "JP": ("Japan", "Япония"), "CN": ("China", "Китай"),
    "KR": ("South Korea", "Южная Корея"), "CA": ("Canada", "Канада"), "AU": ("Australia", "Австралия"),
    "CH": ("Switzerland", "Швейцария"), "AT": ("Austria", "Австрия"), "BE": ("Belgium", "Бельгия"),
    "IE": ("Ireland", "Ирландия"), "PT": ("Portugal", "Португалия"), "GR": ("Greece", "Греция"),
    "NO": ("Norway", "Норвегия"), "SK": ("Slovakia", "Словакия"), "BG": ("Bulgaria", "Болгария"),
    "KZ": ("Kazakhstan", "Казахстан"), "MX": ("Mexico", "Мексика"), "AR": ("Argentina", "Аргентина"),
    "IN": ("India", "Индия"), "SG": ("Singapore", "Сингапур"),
    "AE": ("United Arab Emirates", "ОАЭ"), "AM": ("Armenia", "Армения"), "AZ": ("Azerbaijan", "Азербайджан"),
    "BD": ("Bangladesh", "Бангладеш"), "BY": ("Belarus", "Беларусь"), "CL": ("Chile", "Чили"),
    "CO": ("Colombia", "Колумбия"), "CY": ("Cyprus", "Кипр"), "DZ": ("Algeria", "Алжир"),
    "EC": ("Ecuador", "Эквадор"), "EE": ("Estonia", "Эстония"), "EG": ("Egypt", "Египет"),
    "GE": ("Georgia", "Грузия"), "GH": ("Ghana", "Гана"), "HK": ("Hong Kong", "Гонконг"),
    "HR": ("Croatia", "Хорватия"), "ID": ("Indonesia", "Индонезия"), "IL": ("Israel", "Израиль"),
    "IR": ("Iran", "Иран"), "IS": ("Iceland", "Исландия"), "KE": ("Kenya", "Кения"),
    "LT": ("Lithuania", "Литва"), "LU": ("Luxembourg", "Люксембург"), "LV": ("Latvia", "Латвия"),
    "MA": ("Morocco", "Марокко"), "MD": ("Moldova", "Молдова"), "MT": ("Malta", "Мальта"),
    "MY": ("Malaysia", "Малайзия"), "NG": ("Nigeria", "Нигерия"), "NZ": ("New Zealand", "Новая Зеландия"),
    "PE": ("Peru", "Перу"), "PH": ("Philippines", "Филиппины"), "PK": ("Pakistan", "Пакистан"),
    "RS": ("Serbia", "Сербия"), "SA": ("Saudi Arabia", "Саудовская Аравия"), "SI": ("Slovenia", "Словения"),
    "TH": ("Thailand", "Таиланд"), "TN": ("Tunisia", "Тунис"), "TW": ("Taiwan", "Тайвань"),
    "VE": ("Venezuela", "Венесуэла"), "VN": ("Vietnam", "Вьетнам"), "ZA": ("South Africa", "ЮАР"),
}


def country_name(code: str | None, fallback: str | None = None) -> str:
    """Localized country name; unknown codes fall back to ``fallback`` or the code."""
    key = (code or "").strip().upper()
    names = _NAMES.get(key)
    if names is not None:
        return names[1] if is_ru() else names[0]
    return fallback or key or "—"


def known_codes() -> list[str]:
    return sorted(_NAMES, key=lambda c: country_name(c).casefold())
