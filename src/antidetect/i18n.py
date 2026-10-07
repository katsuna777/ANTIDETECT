"""Interface language: English / Russian.

Two languages, one flat table. The choice is stored in the settings table
(``gui.language``) and applied live; every key has both translations (checked by
the test-suite). Usage::

    from antidetect.i18n import tr
    label = tr("nav.profiles")                  # "Profiles" / "Профили"
    text = tr("toast.started", name="Shop")     # formatted
"""

from __future__ import annotations

LANG_EN = "en"
LANG_RU = "ru"
DEFAULT = LANG_EN

_current: str = DEFAULT


def normalize(code: str | None) -> str:
    raw = (code or "").strip().lower()
    if raw in ("ru", "rus", "russian", "рус", "русский"):
        return LANG_RU
    if raw in ("en", "eng", "english", "анг", "английский"):
        return LANG_EN
    return DEFAULT


def set_language(code: str | None) -> str:
    """Set the global UI language; returns the normalized code."""
    global _current
    _current = normalize(code)
    return _current


def get_language() -> str:
    return _current


def is_ru() -> bool:
    return _current == LANG_RU


def tr(key: str, _lang: str | None = None, **kwargs) -> str:
    """Translate ``key``; unknown keys fall back to English, then the key."""
    lang = normalize(_lang) if _lang is not None else _current
    table = _STRINGS.get(key)
    if not table:
        return key
    text = table.get(lang) or table.get(LANG_EN) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def _t(en: str, ru: str) -> dict[str, str]:
    return {"en": en, "ru": ru}


_STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ shell
    "app.title": _t("Antidetect", "Antidetect"),
    "nav.profiles": _t("Profiles", "Профили"),
    "nav.proxies": _t("Proxies", "Прокси"),
    "nav.check": _t("Check", "Проверка"),
    "nav.api": _t("API", "API"),
    "nav.logs": _t("Logs", "Журнал"),
    "nav.settings": _t("Settings", "Настройки"),
    "sidebar.browser": _t("Chrome {version}", "Chrome {version}"),
    "sidebar.browser.missing": _t("Chrome not found", "Chrome не найден"),
    "sidebar.theme.dark": _t("Switch to dark theme", "Включить тёмную тему"),
    "sidebar.theme.light": _t("Switch to light theme", "Включить светлую тему"),
    "common.cancel": _t("Cancel", "Отмена"),
    "common.close": _t("Close", "Закрыть"),
    "common.delete": _t("Delete", "Удалить"),
    "common.open": _t("Open", "Открыть"),
    "common.choose": _t("Choose…", "Выбрать…"),
    "common.details": _t("Details", "Подробности"),
    "common.copy": _t("Copy", "Копировать"),
    "common.never": _t("Never", "Никогда"),
    # ---------------------------------------------------------------- profiles
    "profiles.title": _t("Profiles", "Профили"),
    "profiles.new": _t("New profile", "Новый профиль"),
    "profiles.search": _t("Search profiles…", "Поиск профилей…"),
    "profiles.count": _t("{total} profiles · {running} running", "Профилей: {total} · запущено: {running}"),
    "profiles.filter.all": _t("All", "Все"),
    "profiles.filter.alltags": _t("All tags", "Все теги"),
    "profiles.filter.running": _t("Running", "Запущенные"),
    "profiles.filter.stopped": _t("Stopped", "Остановленные"),
    "profiles.filter.tag": _t("Tag: {tag}", "Тег: {tag}"),
    "filter.button": _t("Filter", "Фильтр"),
    "filter.status": _t("Status", "Статус"),
    "filter.system": _t("System", "Система"),
    "filter.proxy": _t("Proxy", "Прокси"),
    "filter.tags": _t("Tags", "Теги"),
    "filter.reset": _t("Reset filters", "Сбросить фильтры"),
    "filter.proxy.any": _t("Any", "Любой"),
    "filter.proxy.with": _t("With proxy", "С прокси"),
    "filter.proxy.without": _t("No proxy", "Без прокси"),
    "sort.button": _t("Sort", "Сортировка"),
    "sort.name": _t("Name", "Имя"),
    "sort.last": _t("Last run", "Последний запуск"),
    "sort.created": _t("Created", "Дата создания"),
    "sort.status": _t("Status", "Статус"),
    "sort.asc": _t("Ascending", "По возрастанию"),
    "sort.desc": _t("Descending", "По убыванию"),
    "bulk.clear": _t("Clear selection", "Снять выделение"),
    "proxy.info.unknown": _t("Unknown location", "Страна не определена"),
    "proxy.info.host": _t("Host", "Хост"),
    "proxy.info.auth": _t("Login", "Логин"),
    "proxy.info.noauth": _t("none", "нет"),
    "proxy.info.timezone": _t("Timezone", "Часовой пояс"),
    "proxy.info.status": _t("Status", "Состояние"),
    "proxy.info.checked": _t("Checked", "Проверен"),
    "proxy.info.check": _t("Check now", "Проверить"),
    "col.name": _t("Profile", "Профиль"),
    "col.status": _t("Status", "Статус"),
    "col.system": _t("System", "Система"),
    "col.proxy": _t("Proxy", "Прокси"),
    "col.lastrun": _t("Last run", "Запуск"),
    "col.created": _t("Created", "Создан"),
    "col.cookies": _t("Cookies", "Cookies"),
    "cookies.tip": _t("Cookies this profile has saved", "Cookies, сохранённые этим профилем"),
    "proxy.free.tag": _t("free", "бесплатный"),
    "col.address": _t("Address", "Адрес"),
    "col.country": _t("Country", "Страна"),
    "col.ping": _t("Ping", "Пинг"),
    "col.anonymity": _t("Anonymity", "Анонимность"),
    "col.source": _t("Source", "Источник"),
    "col.usedby": _t("Used by", "Используется"),
    "status.running": _t("Running", "Запущен"),
    "status.stopped": _t("Stopped", "Остановлен"),
    "status.starting": _t("Starting…", "Запуск…"),
    "status.stopping": _t("Stopping…", "Остановка…"),
    "status.preparing": _t("Setting up…", "Настройка…"),
    "action.start": _t("Start", "Запустить"),
    "action.stop": _t("Stop", "Остановить"),
    "proxy.none": _t("No proxy", "Без прокси"),
    "proxy.none.tip": _t("This profile uses your own connection.", "Профиль использует ваше обычное подключение."),
    "time.now": _t("Just now", "Только что"),
    "time.minutes": _t("{n} min ago", "{n} мин назад"),
    "time.hours": _t("{n} h ago", "{n} ч назад"),
    "time.days": _t("{n} d ago", "{n} дн назад"),
    "menu.start": _t("Start", "Запустить"),
    "menu.stop": _t("Stop", "Остановить"),
    "menu.restart": _t("Restart", "Перезапустить"),
    "menu.edit": _t("Edit…", "Изменить…"),
    "menu.duplicate": _t("Duplicate", "Дублировать"),
    "menu.check": _t("Check fingerprint", "Проверить отпечаток"),
    "menu.cookies": _t("Cookies", "Cookies"),
    "menu.cookies.export": _t("Export…", "Экспортировать…"),
    "menu.cookies.import": _t("Import…", "Импортировать…"),
    "menu.folder": _t("Open profile folder", "Открыть папку профиля"),
    "menu.delete": _t("Delete…", "Удалить…"),
    "menu.selected": _t("{n} selected", "Выбрано: {n}"),
    "bulk.start": _t("Start", "Запустить"),
    "bulk.stop": _t("Stop", "Остановить"),
    "bulk.delete": _t("Delete", "Удалить"),
    "bulk.selected": _t("{n} selected", "Выбрано: {n}"),
    "empty.title": _t("Create your first profile", "Создайте первый профиль"),
    "empty.text": _t(
        "A profile is a separate browser with its own cookies, fingerprint and proxy — "
        "accounts never mix.",
        "Профиль — это отдельный браузер со своими cookies, отпечатком и прокси. "
        "Аккаунты никогда не пересекаются.",
    ),
    "empty.step1": _t("1   Pick the system and, if you have one, a proxy", "1   Выберите систему и, если есть, прокси"),
    "empty.step2": _t("2   Press Start — the browser opens ready to use", "2   Нажмите «Запустить» — браузер откроется готовым к работе"),
    "empty.step3": _t("3   See how it looks to websites in the Check section", "3   Посмотрите, как он выглядит для сайтов, во вкладке «Проверка»"),
    "empty.filtered": _t("No profiles match your search", "Ничего не найдено"),
    "banner.nobrowser": _t(
        "Google Chrome was not found on this computer. Download it (about 150 MB) or choose where it is in Settings.",
        "Google Chrome не найден на этом компьютере. Скачайте его (около 150 МБ) или укажите расположение в настройках.",
    ),
    "banner.download": _t("Download Chrome", "Скачать Chrome"),
    "toast.started": _t("“{name}” started", "«{name}» запущен"),
    "toast.stopped": _t("“{name}” stopped", "«{name}» остановлен"),
    "toast.created": _t("Profile “{name}” created", "Профиль «{name}» создан"),
    "toast.updated": _t("Saved", "Сохранено"),
    "toast.deleted": _t("Deleted: {name}", "Удалено: {name}"),
    "toast.duplicated": _t("Created “{name}”", "Создан «{name}»"),
    "toast.cookies.exported": _t("Cookies saved to {path}", "Cookies сохранены: {path}"),
    "toast.cookies.imported": _t("Cookies restored", "Cookies восстановлены"),
    "toast.proxies.added": _t("Added {added} new, {existing} already in the list", "Добавлено новых: {added}, уже были: {existing}"),
    "toast.copied": _t("Copied", "Скопировано"),
    "confirm.delete.title": _t("Delete profile?", "Удалить профиль?"),
    "confirm.delete.text": _t(
        "“{name}” and everything stored in it — cookies, history, saved logins — will be "
        "removed. This cannot be undone.",
        "«{name}» и всё, что в нём хранится — cookies, история, сохранённые входы — будет "
        "удалено. Это нельзя отменить.",
    ),
    "confirm.delete.many.title": _t("Delete {n} profiles?", "Удалить профилей: {n}?"),
    "confirm.delete.many.text": _t(
        "All data of the selected profiles will be removed. This cannot be undone.",
        "Все данные выбранных профилей будут удалены. Это нельзя отменить.",
    ),
    "quit.title": _t("Profiles are still running", "Профили ещё запущены"),
    "quit.text": _t(
        "Running profiles are protected only while Antidetect is open, so they will be "
        "stopped first.",
        "Запущенные профили защищены, только пока открыт Antidetect, поэтому они будут "
        "сначала остановлены.",
    ),
    "quit.confirm": _t("Stop profiles and quit", "Остановить профили и выйти"),
    # ----------------------------------------------------------- profile dialog
    "dlg.new.title": _t("New profile", "Новый профиль"),
    "profile.default": _t("Profile {n}", "Профиль {n}"),
    "dlg.edit.title": _t("Edit profile", "Изменить профиль"),
    "dlg.new.subtitle": _t("The fingerprint is built for the system you choose.",
                           "Отпечаток подберём под выбранную систему."),
    "tab.general": _t("General", "Основное"),
    "tab.proxy": _t("Proxy", "Прокси"),
    "tab.fingerprint": _t("Fingerprint", "Отпечаток"),
    "tab.notes": _t("Notes and tags", "Заметки и теги"),
    "field.name": _t("Name", "Название"),
    "field.os": _t("Operating system", "Операционная система"),
    "os.windows": _t("Windows", "Windows"),
    "os.macos": _t("macOS", "macOS"),
    "os.linux": _t("Linux", "Linux"),
    "os.hint.native": _t(
        "This is your computer's system — the most natural choice.",
        "Это система вашего компьютера — самый естественный выбор.",
    ),
    "os.hint.other": _t(
        "Different from your computer. Works on most sites, but strict checkers (Pixelscan, for "
        "example) report “masking”: fonts and rendering belong to the real system and cannot be "
        "faked. The same system as yours looks most natural.",
        "Отличается от системы вашего компьютера. Работает на большинстве сайтов, но строгие "
        "проверки (например, Pixelscan) покажут «masking»: шрифты и отрисовка — свойства "
        "настоящей системы, их нельзя подменить. Та же система, что у вас, выглядит естественнее всего.",
    ),
    "field.proxy": _t("Proxy", "Прокси"),
    "proxy.mode.none": _t("No proxy — use my connection", "Без прокси — моё подключение"),
    "proxy.mode.new": _t("Add a new proxy…", "Добавить новый прокси…"),
    "proxy.paste.placeholder": _t("host:port:login:password", "host:port:логин:пароль"),
    "proxy.paste.hint": _t(
        "Paste it the way your provider gave it: host:port, host:port:login:password, "
        "login:password@host:port or socks5://…",
        "Вставьте так, как выдал провайдер: host:port, host:port:логин:пароль, "
        "логин:пароль@host:port или socks5://…",
    ),
    "proxy.type": _t("Type", "Тип"),
    "proxy.check": _t("Check", "Проверить"),
    "proxy.checking": _t("Checking…", "Проверяем…"),
    "proxy.ok": _t("Works · {country} · {ms} ms", "Работает · {country} · {ms} мс"),
    "proxy.fail": _t("Not responding: {detail}", "Не отвечает: {detail}"),
    "proxy.unreadable": _t(
        "Couldn't read this proxy. Use host:port or host:port:login:password.",
        "Не удалось прочитать прокси. Используйте host:port или host:port:логин:пароль.",
    ),
    "proxy.saved.label": _t("{address}  ·  {country}", "{address}  ·  {country}"),
    "proxy.saved.free": _t("{address}  ·  {country}  ·  free", "{address}  ·  {country}  ·  бесплатный"),
    "field.geo": _t(
        "Match language and time zone to the IP address",
        "Подбирать язык и часовой пояс по IP-адресу",
    ),
    "geo.hint": _t(
        "Recommended. Keeps the profile's location consistent with where it connects from.",
        "Рекомендуется. Местоположение профиля совпадёт с тем, откуда он выходит в сеть.",
    ),
    "field.webrtc": _t("WebRTC", "WebRTC"),
    "webrtc.auto": _t("Automatic", "Автоматически"),
    "webrtc.block": _t("Always hidden", "Всегда скрыт"),
    "webrtc.allow": _t("Not hidden", "Не скрывать"),
    "webrtc.hint.auto": _t(
        "Hidden while the profile uses a proxy, so the real address can't show next to the proxy's.",
        "Скрыт, пока профиль работает через прокси: реальный адрес не покажется рядом с адресом прокси.",
    ),
    "webrtc.hint.block": _t(
        "Hidden always. Video calls in the browser may not work.",
        "Скрыт всегда. Видеозвонки в браузере могут не работать.",
    ),
    "webrtc.hint.allow": _t(
        "Left alone. Calls work, but sites can see the real address.",
        "Не трогается. Звонки работают, но сайты могут увидеть реальный адрес.",
    ),
    "fp.protection": _t("Protection", "Защита"),
    "fp.theme": _t("Colour scheme of sites", "Цветовая схема сайтов"),
    "fp.theme.hint": _t(
        "What sites are told the profile prefers. By default it does not follow the computer, so profiles "
        "don't share its dark or light mode.",
        "Что сайты узнают о предпочтениях профиля. По умолчанию не зависит от компьютера, поэтому у профилей "
        "нет общего признака тёмной или светлой темы системы.",
    ),
    "theme.light": _t("Light", "Светлая"),
    "theme.dark": _t("Dark", "Тёмная"),
    "theme.auto": _t("Like the system", "Как в системе"),
    "fp.noise.canvas": _t("Canvas noise", "Шум canvas"),
    "fp.noise.canvas.hint": _t(
        "Makes the picture fingerprint unique to this profile.",
        "Делает отпечаток картинки уникальным у этого профиля.",
    ),
    "fp.noise.audio": _t("Audio noise", "Шум audio"),
    "fp.noise.audio.hint": _t(
        "Does the same for the sound fingerprint. Turn off only if a site breaks.",
        "То же для отпечатка звука. Выключайте, только если сайт перестал работать.",
    ),
    "bulk.title": _t("Create several profiles", "Создать несколько профилей"),
    "bulk.subtitle": _t(
        "The same settings for all; each profile gets a fingerprint of its own.",
        "Одни настройки на всех, у каждого профиля — свой отпечаток.",
    ),
    "bulk.name.default": _t("Profile", "Профиль"),
    "bulk.count": _t("How many", "Сколько"),
    "bulk.proxies": _t("Proxies, one per line", "Прокси, по одному в строке"),
    "bulk.proxies.placeholder": _t(
        "203.0.113.5:8080:login:password\nsocks5://login:password@203.0.113.6:1080",
        "203.0.113.5:8080:логин:пароль\nsocks5://логин:пароль@203.0.113.6:1080",
    ),
    "bulk.proxies.none": _t(
        "No proxies: the profiles will connect the way you do.",
        "Без прокси: профили будут выходить в сеть так же, как вы.",
    ),
    "bulk.proxies.enough": _t(
        "Every profile gets a proxy of its own.",
        "Каждый профиль получит свой прокси.",
    ),
    "bulk.proxies.extra": _t(
        "Every profile gets a proxy of its own; {extra} spare stay in your list.",
        "Каждый профиль получит свой прокси; лишние ({extra}) останутся в списке.",
    ),
    "bulk.proxies.short": _t(
        "Proxies are enough for {have} of {n} profiles; the other {missing} will have none (a proxy is never shared).",
        "Прокси хватит на {have} из {n} профилей; у остальных ({missing}) прокси не будет (один прокси на два профиля не выдаётся).",
    ),
    "bulk.proxies.invalid": _t("Can't read {k} line(s).", "Не удалось прочитать строк: {k}."),
    "bulk.create": _t("Create ({n})", "Создать ({n})"),
    "bulk.create.none": _t("Create", "Создать"),
    "err.bulk.count": _t("From 1 to {max} profiles", "От 1 до {max} профилей"),
    "toast.bulk.created": _t("Created {n} profiles", "Создано профилей: {n}"),
    "toast.bulk.partial": _t(
        "Created {n} of {total}. Not created: {failed}",
        "Создано {n} из {total}. Не создано: {failed}",
    ),
    "toast.bulk.ready": _t("The profiles are ready", "Профили готовы"),
    "menu.more": _t("More", "Ещё"),
    "menu.more.bulk": _t("Create several…", "Создать несколько…"),
    "menu.more.import": _t("Import a profile…", "Импортировать профиль…"),
    "menu.export": _t("Export…", "Экспортировать…"),
    "export.title": _t("Export a profile", "Экспорт профиля"),
    "export.what": _t("What goes into the file", "Что попадёт в файл"),
    "export.cookies": _t(
        "Settings, fingerprint and the browser's data. Cookies and saved passwords are tied to this "
        "computer: on another one the profile opens with the same fingerprint, but logged out.",
        "Настройки, отпечаток и данные браузера. Cookies и сохранённые пароли привязаны к этому компьютеру: "
        "на другом профиль откроется с тем же отпечатком, но без входа в аккаунты.",
    ),
    "export.proxy": _t("Include the proxy", "Добавить прокси"),
    "export.proxy.hint": _t(
        "Its login and password are saved in the file as plain text. Share the file only with people you trust.",
        "Логин и пароль прокси сохранятся в файле открытым текстом. Передавайте файл только тем, кому доверяете.",
    ),
    "export.choose": _t("Choose where to save…", "Выбрать, куда сохранить…"),
    "toast.exported": _t("Exported: {path}", "Экспортировано: {path}"),
    "import.dialog": _t("Import a profile", "Импорт профиля"),
    "import.filter": _t("Profile archives (*.zip)", "Архивы профилей (*.zip)"),
    "toast.imported": _t("Imported “{name}”", "Импортирован «{name}»"),
    "act.browser.installed": _t("Chrome {name} downloaded", "Скачан Chrome {name}"),
    "act.profile.imported": _t("“{name}” imported from a file", "«{name}» импортирован из файла"),
    "act.profile.exported": _t("“{name}” exported to a file", "«{name}» экспортирован в файл"),
    "field.starturl": _t("Start page", "Стартовая страница"),
    "field.notes": _t("Notes", "Заметки"),
    "field.tags": _t("Tags", "Теги"),
    "field.tags.hint": _t("Separate with commas", "Через запятую"),
    "fp.summary.os": _t("System", "Система"),
    "fp.summary.browser": _t("Browser", "Браузер"),
    "fp.summary.screen": _t("Screen", "Экран"),
    "fp.summary.gpu": _t("Video card", "Видеокарта"),
    "fp.regenerate": _t("Generate a new fingerprint", "Сгенерировать новый отпечаток"),
    "fp.regenerated": _t(
        "A new fingerprint will be generated when you save.",
        "Новый отпечаток будет создан при сохранении.",
    ),
    "fp.advanced": _t("Fine-tune", "Тонкая настройка"),
    "fp.language": _t("Language", "Язык"),
    "fp.timezone": _t("Time zone", "Часовой пояс"),
    "fp.screen": _t("Screen", "Экран"),
    "fp.gpu": _t("Video card", "Видеокарта"),
    "fp.cores": _t("CPU cores", "Ядер процессора"),
    "fp.memory": _t("Memory, GB", "Память, ГБ"),
    "fp.auto.note": _t(
        "Language and time zone follow the IP address while that option is on.",
        "Язык и часовой пояс следуют за IP-адресом, пока эта опция включена.",
    ),
    "btn.create": _t("Create", "Создать"),
    "btn.create_start": _t("Create and start", "Создать и запустить"),
    "btn.save": _t("Save", "Сохранить"),
    "err.name.empty": _t("Enter a name", "Введите название"),
    "err.name.exists": _t("A profile with this name already exists", "Профиль с таким названием уже есть"),
    # ------------------------------------------------------------------- check
    "check.title": _t("Fingerprint check", "Проверка отпечатка"),
    "check.subtitle": _t(
        "Open a profile on independent services and see what websites see.",
        "Откройте профиль на независимых сервисах и посмотрите, что видят сайты.",
    ),
    "check.profile": _t("Profile", "Профиль"),
    "check.open": _t("Open", "Открыть"),
    "check.hint": _t(
        "Profiles with the same system as your computer pass the strictest checks most "
        "naturally. The page opens inside the chosen profile and starts it if needed.",
        "Профили с той же системой, что у вашего компьютера, естественнее всего проходят "
        "строгие проверки. Страница откроется в выбранном профиле — при необходимости он "
        "будет запущен.",
    ),
    "check.none.title": _t("Create a profile first", "Сначала создайте профиль"),
    "check.none.text": _t(
        "Checks run inside a profile, so there is nothing to test yet.",
        "Проверки выполняются внутри профиля, пока тестировать нечего.",
    ),
    "check.site.creepjs": _t("CreepJS", "CreepJS"),
    "check.site.pixelscan": _t("Pixelscan", "Pixelscan"),
    "check.site.iphey": _t("IPHey", "IPHey"),
    "check.site.browserleaks": _t("BrowserLeaks", "BrowserLeaks"),
    "check.site.sannysoft": _t("Sannysoft", "Sannysoft"),
    "check.desc.creepjs": _t("Inconsistencies and “lies” in the fingerprint", "Несоответствия и «ложь» в отпечатке"),
    "check.desc.pixelscan": _t("Overall consistency of the browser", "Общая согласованность браузера"),
    "check.desc.iphey": _t("Trust score of the browser and the IP", "Уровень доверия к браузеру и IP"),
    "check.desc.browserleaks": _t("WebRTC and IP leaks", "Утечки WebRTC и IP-адреса"),
    "check.desc.sannysoft": _t("Automation and headless signals", "Признаки автоматизации"),
    # ----------------------------------------------------------------- proxies
    "proxies.title": _t("Proxies", "Прокси"),
    "proxies.add": _t("Add proxies", "Добавить прокси"),
    "proxies.check": _t("Check all", "Проверить все"),
    "proxies.free": _t("Free proxies", "Бесплатные прокси"),
    "proxies.free.tip": _t(
        "Download public lists of free proxies and keep only the ones that pass a check. "
        "They are slow and short-lived — use your own for real work.",
        "Скачать публичные списки бесплатных прокси и оставить только те, что прошли проверку. "
        "Они медленные и быстро умирают — для работы берите свои.",
    ),
    "proxies.search": _t("Search proxies…", "Поиск прокси…"),
    "proxies.count": _t("{total} proxies · {working} working", "Прокси: {total} · рабочих: {working}"),
    "proxies.working": _t("{n} working", "рабочих: {n}"),
    "sidebar.tags": _t("Tags", "Теги"),
    "sidebar.tags.more": _t("{n} more", "Ещё {n}"),
    "sidebar.tags.less": _t("Show less", "Свернуть"),
    "search.tip": _t("Quick search", "Быстрый поиск"),
    "palette.placeholder": _t("Search profiles, pages and actions…", "Профили, страницы, действия…"),
    "palette.empty": _t("Nothing found", "Ничего не найдено"),
    "palette.start": _t("Start ↵", "Запустить ↵"),
    "palette.stop": _t("Stop ↵", "Остановить ↵"),
    "palette.tag": _t("Tag · {n} profiles", "Тег · профилей: {n}"),
    "menu.file": _t("File", "Файл"),
    "menu.file.new": _t("New profile", "Новый профиль"),
    "menu.file.proxies": _t("Add proxies…", "Добавить прокси…"),
    "menu.file.settings": _t("Settings…", "Настройки…"),
    "menu.file.about": _t("About Antidetect", "О программе Antidetect"),
    "menu.file.quit": _t("Quit Antidetect", "Выйти из Antidetect"),
    "menu.view": _t("View", "Вид"),
    "menu.view.search": _t("Quick search", "Быстрый поиск"),
    "menu.view.theme": _t("Switch light / dark theme", "Переключить тему"),
    "menu.window": _t("Window", "Окно"),
    "menu.window.minimize": _t("Minimize", "Свернуть"),
    "menu.window.zoom": _t("Zoom", "Развернуть"),
    "proxies.empty.title": _t("No proxies yet", "Прокси пока нет"),
    "proxies.empty.text": _t(
        "Add the proxies you bought. Paste them in any common format — one per line.",
        "Добавьте купленные прокси. Вставьте их в любом привычном формате — по одному в строке.",
    ),
    "proxies.checking": _t("Checking {done} of {total}…", "Проверка {done} из {total}…"),
    "proxies.collecting": _t("Collecting free proxies…", "Собираем бесплатные прокси…"),
    "proxies.stopping": _t("Stopping…", "Останавливаем…"),
    "proxies.done": _t("Done: {working} working of {checked} checked", "Готово: рабочих {working} из {checked}"),
    "proxy.status.working": _t("Working", "Работает"),
    "proxy.status.dead": _t("Dead", "Не работает"),
    "proxy.status.unknown": _t("Not checked", "Не проверен"),
    "proxy.status.error": _t("Error", "Ошибка"),
    "proxy.anon.elite": _t("Elite", "Элитный"),
    "proxy.anon.anonymous": _t("Anonymous", "Анонимный"),
    "proxy.anon.transparent": _t("Transparent", "Прозрачный"),
    "proxy.anon.unknown": _t("—", "—"),
    "proxy.source.manual": _t("Yours", "Ваш"),
    "proxy.source.pool": _t("Free list", "Бесплатный список"),
    "proxy.free.warn.title": _t("Free proxies are for testing only", "Бесплатные прокси — только для тестов"),
    "proxy.free.warn.text": _t(
        "Their IPs are already flagged: fingerprint checks (Pixelscan, IPHey…) usually fail, "
        "Google shows captchas and accounts get banned easily. That is not a fault of the "
        "antidetect — use your own private proxies for real work.",
        "Их IP давно засвечены: проверки (Pixelscan, IPHey и др.) обычно не проходятся, "
        "Google показывает капчу, а аккаунты легко получают бан. Это не сбой антидетекта — "
        "для реальной работы используйте свои приватные прокси.",
    ),
    "proxy.menu.check": _t("Check", "Проверить"),
    "proxy.menu.copy": _t("Copy address", "Копировать адрес"),
    "proxy.menu.delete": _t("Delete", "Удалить"),
    "imp.title": _t("Add proxies", "Добавить прокси"),
    "imp.hint": _t(
        "One proxy per line. Any of these formats works:",
        "Один прокси в строке. Подойдёт любой из форматов:",
    ),
    "imp.formats": _t(
        "host:port\nhost:port:login:password\nlogin:password@host:port\nsocks5://login:password@host:port",
        "host:port\nhost:port:логин:пароль\nлогин:пароль@host:port\nsocks5://логин:пароль@host:port",
    ),
    "imp.placeholder": _t("Paste proxies here…", "Вставьте прокси сюда…"),
    "imp.type": _t("Type when not specified", "Тип, если не указан"),
    "imp.preview": _t("{ok} ready · {bad} can't be read", "Готово: {ok} · не удалось прочитать: {bad}"),
    "imp.check": _t("Check them after adding", "Проверить после добавления"),
    "imp.add": _t("Add", "Добавить"),
    # -------------------------------------------------------------------- logs
    "logs.title": _t("Logs", "Журнал"),
    "logs.subtitle": _t("{n} entries this session", "Записей за сессию: {n}"),
    "logs.filter.all": _t("All", "Все"),
    "logs.filter.info": _t("Info", "Инфо"),
    "logs.filter.warn": _t("Warnings", "Предупреждения"),
    "logs.filter.error": _t("Errors", "Ошибки"),
    "logs.search": _t("Filter…", "Фильтр…"),
    "logs.clear": _t("Clear", "Очистить"),
    "logs.export": _t("Export…", "Экспорт…"),
    "logs.follow": _t("Follow", "Следить"),
    "logs.exported": _t("Log saved to {path}", "Журнал сохранён: {path}"),
    "logs.empty": _t("Nothing logged yet", "Записей пока нет"),
    # ---------------------------------------------------------------- settings
    "settings.title": _t("Settings", "Настройки"),
    "settings.appearance": _t("Appearance", "Оформление"),
    "settings.theme": _t("Theme", "Тема"),
    "settings.theme.desc": _t("Light, dark or follow the system.", "Светлая, тёмная или как в системе."),
    "theme.system": _t("System", "Система"),
    "theme.light": _t("Light", "Светлая"),
    "theme.dark": _t("Dark", "Тёмная"),
    "settings.language": _t("Language", "Язык"),
    "settings.language.desc": _t("The language of the interface.", "Язык интерфейса."),
    "settings.browser": _t("Browser", "Браузер"),
    "settings.browser.name": _t("Google Chrome", "Google Chrome"),
    "settings.browser.auto": _t("Detect automatically", "Определить автоматически"),
    "settings.browser.found": _t("{path}", "{path}"),
    "settings.browser.version": _t("Version {version}", "Версия {version}"),
    "settings.browser.missing": _t("Not found", "Не найден"),
    "settings.browser.note": _t(
        "Profiles run on the browser shown here, always as its real version, so the fingerprint "
        "matches the engine. A Chrome downloaded by the app stays as it is until you update it.",
        "Профили запускаются на показанном здесь браузере, всегда как на его реальной версии, поэтому "
        "отпечаток совпадает с движком. Скачанный приложением Chrome не меняется, пока вы сами не обновите его.",
    ),
    "settings.browser.download": _t("Download Chrome", "Скачать Chrome"),
    "settings.browser.update": _t("Update Chrome", "Обновить Chrome"),
    "settings.browser.source.managed": _t("Downloaded by the app", "Скачан приложением"),
    "settings.browser.source.configured": _t("Chosen by you", "Выбран вами"),
    "settings.browser.source.auto": _t("Installed on this computer", "Установлен на компьютере"),
    "browser.dl.title": _t("Download Chrome", "Скачивание Chrome"),
    "browser.dl.checking": _t("Asking Google which version is current…", "Узнаём у Google, какая версия актуальна…"),
    "browser.dl.sub": _t("Chrome {version} · the official build from Google", "Chrome {version} · официальная сборка Google"),
    "browser.dl.progress": _t("{done} of {total} MB", "{done} из {total} МБ"),
    "browser.dl.installing": _t("Unpacking and checking…", "Распаковка и проверка…"),
    "browser.dl.note": _t(
        "Profiles will run on this version, so the fingerprint always matches the real engine. It stays as it is until you update it.",
        "Профили будут работать на этой версии, поэтому отпечаток всегда совпадает с реальным движком. Она не меняется, пока вы сами не обновите её.",
    ),
    "browser.dl.retry": _t("Try again", "Повторить"),
    "toast.browser.installed": _t(
        "Chrome {version} downloaded; profiles now run on it",
        "Chrome {version} скачан, профили теперь запускаются на нём",
    ),
    "toast.browser.latest": _t(
        "You already have the latest Chrome ({version})",
        "У вас уже последняя версия Chrome ({version})",
    ),
    "menu.browser.download": _t("Download Chrome…", "Скачать Chrome…"),
    "settings.behavior": _t("Behavior", "Поведение"),
    "settings.confirm": _t("Ask before deleting for good", "Спрашивать перед удалением навсегда"),
    "settings.confirm.desc": _t(
        "Profiles go to the trash first; deleting them from there removes their cookies and history for good.",
        "Профили сначала попадают в корзину; удаление оттуда стирает их cookies и историю навсегда.",
    ),
    "settings.data": _t("Data", "Данные"),
    "settings.data.folder": _t("Data folder", "Папка с данными"),
    "settings.about": _t("About", "О программе"),
    "settings.about.text": _t("Isolated browser profiles with a consistent fingerprint.", "Изолированные профили браузера с согласованным отпечатком."),
    "settings.version": _t("Version {version}", "Версия {version}"),
    "dlg.choose.browser": _t("Choose the Chrome executable", "Выберите исполняемый файл Chrome"),
    # --------------------------------------------------------------------- api
    "api.title": _t("API", "API"),
    "api.state.on": _t("Running", "Работает"),
    "api.state.off": _t("Off", "Выключено"),
    "api.instruction": _t("Instruction", "Инструкция"),
    "api.keys.new": _t("New key", "Новый ключ"),
    "api.enable.tip": _t(
        "Local API for scripts: create, start and stop profiles and connect Playwright, Puppeteer or Selenium. "
        "Available on this computer only.",
        "Локальное API для скриптов: создание, запуск и остановка профилей, подключение Playwright, Puppeteer или "
        "Selenium. Доступно только на этом компьютере.",
    ),
    "api.port.tip": _t("Port", "Порт"),
    "api.address.copy": _t("Copy address", "Копировать адрес"),
    "api.address.copied": _t("Address copied", "Адрес скопирован"),
    "api.error.busy": _t("Port {port} is busy", "Порт {port} занят"),
    "api.error.other": _t("Could not start: {error}", "Не удалось запустить: {error}"),
    "api.port.invalid": _t("Port: 1024–65535", "Порт: 1024–65535"),
    "api.toast.failed": _t("The API could not start: {error}", "API не удалось запустить: {error}"),
    "api.keys": _t("Keys", "Ключи"),
    "api.key.unused": _t("Not used yet", "Не использовался"),
    "api.key.tip": _t(
        "Created {date}\nRequests since start: {n}",
        "Создан {date}\nЗапросов с запуска: {n}",
    ),
    "api.key.show": _t("Show key", "Показать ключ"),
    "api.key.hide": _t("Hide key", "Скрыть ключ"),
    "api.key.copy": _t("Copy key", "Копировать ключ"),
    "api.key.copied": _t("Key copied", "Ключ скопирован"),
    "api.key.more": _t("More", "Ещё"),
    "api.key.rename": _t("Rename…", "Переименовать…"),
    "api.key.regenerate": _t("Make a new secret…", "Перевыпустить…"),
    "api.key.delete": _t("Delete…", "Удалить…"),
    "api.key.dlg.new": _t("New key", "Новый ключ"),
    "api.key.dlg.rename": _t("Rename key", "Переименовать ключ"),
    "api.key.dlg.hint": _t(
        "Name it after what will use it, e.g. “parser”.",
        "Назовите по тому, что будет его использовать, например «парсер».",
    ),
    "api.key.dlg.placeholder": _t("Key name", "Название ключа"),
    "api.key.dlg.create": _t("Create", "Создать"),
    "api.key.dlg.save": _t("Save", "Сохранить"),
    "api.key.err.empty": _t("Enter a name.", "Введите название."),
    "api.key.err.long": _t("The name is too long.", "Название слишком длинное."),
    "api.key.err.duplicate": _t("A key with this name already exists.", "Ключ с таким названием уже есть."),
    "api.key.regen.title": _t("Make a new secret for “{name}”?", "Перевыпустить ключ «{name}»?"),
    "api.key.regen.text": _t(
        "The old key stops working at once. Scripts that use it will get an error until you give them the new one.",
        "Старый ключ сразу перестанет работать. Скрипты, которые его используют, получат ошибку, пока вы не "
        "вставите новый.",
    ),
    "api.key.regen.button": _t("Make new", "Перевыпустить"),
    "api.key.del.title": _t("Delete “{name}”?", "Удалить «{name}»?"),
    "api.key.del.text": _t("Scripts that use this key will stop working at once.", "Скрипты, использующие этот ключ, сразу перестанут работать."),
    "api.key.toast.created": _t("Key “{name}” created", "Ключ «{name}» создан"),
    "api.docs.methods.hint": _t("Click a method to see its fields and an example.", "Нажмите на метод, чтобы увидеть поля и пример."),
    "api.docs.install": _t("Install:", "Установка:"),
    "api.docs.save": _t("Save as file…", "Сохранить файлом…"),
    "api.docs.saved": _t("Saved to {path}", "Сохранено: {path}"),
    "api.docs.copied": _t("Script copied", "Скрипт скопирован"),
    "api.docs.off": _t(
        "The API is switched off now: turn it on above before running these scripts.",
        "Сейчас API выключено: включите его выше, прежде чем запускать эти скрипты.",
    ),
    # ------------------------------------------------------------------ errors
    "error.unexpected": _t(
        "Something went wrong. You can copy the details below if you need help.",
        "Что-то пошло не так. Подробности можно скопировать, если нужна помощь.",
    ),
    "error.details": _t("Details", "Подробности"),
    "err.profile.notfound": _t("Profile with id={id} does not exist.", "Профиль с id={id} не существует."),
    "err.profile.exists": _t("A profile named {name!r} already exists.", "Профиль с именем {name!r} уже существует."),
    "err.profile.running": _t("This profile is already running.", "Этот профиль уже запущен."),
    "err.profile.notrunning": _t("This profile is not running.", "Этот профиль не запущен."),
    "err.profile.noconfig": _t("The profile has no fingerprint yet.", "У профиля ещё нет отпечатка."),
    "err.config.notfound": _t("Fingerprint with id={id} does not exist.", "Отпечаток с id={id} не существует."),
    "err.config.invalid": _t("Invalid fingerprint: {msg}", "Некорректный отпечаток: {msg}"),
    "err.chromium.notfound": _t(
        "Google Chrome was not found. Install it or choose its location in Settings.",
        "Google Chrome не найден. Установите его или укажите расположение в настройках.",
    ),
    "err.proxy.notfound": _t("Proxy with id={id} does not exist.", "Прокси с id={id} не существует."),
    "err.proxy.unusable": _t("The proxy can't be used: {detail}", "Этот прокси нельзя использовать: {detail}"),
    "err.proxy.source": _t("Proxy source {source!r} failed: {detail}", "Источник прокси {source!r} дал сбой: {detail}"),
    "err.cookie.nocookies": _t("This profile has no cookies yet: {detail}", "У этого профиля ещё нет cookies: {detail}"),
    # ------------------------------------------------- activity feed (kind == key)
    "act.profile.created": _t("Profile “{name}” created", "Создан профиль «{name}»"),
    "act.profile.updated": _t("Profile “{name}” changed", "Профиль «{name}» изменён"),
    "act.profile.renamed": _t("Profile “{old}” renamed to “{name}”", "Профиль «{old}» переименован в «{name}»"),
    "act.profile.started": _t("Profile “{name}” started", "Профиль «{name}» запущен"),
    "act.profile.stopped": _t("Profile “{name}” stopped", "Профиль «{name}» остановлен"),
    "act.profile.closed": _t("Browser of “{name}” was closed", "Браузер профиля «{name}» закрыт"),
    "act.profile.start_failed": _t("“{name}” could not start", "«{name}» не удалось запустить"),
    "act.profile.trashed": _t("“{name}” moved to the trash", "«{name}» перемещён в корзину"),
    "act.profile.restored": _t("“{name}” restored from the trash", "«{name}» восстановлен из корзины"),
    "act.profile.purged": _t("“{name}” deleted for good", "«{name}» удалён навсегда"),
    "act.profile.duplicated": _t("“{name}” created as a copy of “{source}”", "«{name}» создан как копия «{source}»"),
    "act.profile.tagged": _t("Tags changed on {count} profiles", "Теги изменены у профилей: {count}"),
    "act.profile.moved": _t("{count} profiles moved to “{name}”", "Профилей перенесено в «{name}»: {count}"),
    "act.profile.unmoved": _t("{count} profiles taken out of their workspace", "Профилей вынуто из рабочих пространств: {count}"),
    "act.tag.created": _t("Tag “{name}” created", "Создан тег «{name}»"),
    "act.tag.renamed": _t("Tag “{old}” renamed to “{name}”", "Тег «{old}» переименован в «{name}»"),
    "act.tag.deleted": _t("Tag “{name}” deleted", "Тег «{name}» удалён"),
    "act.workspace.created": _t("Workspace “{name}” created", "Создано рабочее пространство «{name}»"),
    "act.workspace.renamed": _t("Workspace “{old}” renamed to “{name}”", "Рабочее пространство «{old}» переименовано в «{name}»"),
    "act.workspace.deleted": _t("Workspace “{name}” deleted", "Рабочее пространство «{name}» удалено"),
    "act.proxy.imported": _t("Proxies added: {added} new, {existing} already in the list",
                             "Прокси добавлены: новых {added}, уже были {existing}"),
    "act.proxy.checked": _t("Checked {checked} proxies: {working} working", "Проверено прокси: {checked}, рабочих: {working}"),
    "act.proxy.refreshed": _t("Free proxies updated: {added} added, {working} working",
                              "Бесплатные прокси обновлены: добавлено {added}, рабочих {working}"),
    "act.proxy.deleted": _t("Proxies deleted: {count}", "Удалено прокси: {count}"),
    "act.trash.emptied": _t("Trash emptied: {count} profiles deleted", "Корзина очищена: удалено профилей {count}"),
    "act.trash.expired": _t("{count} profiles deleted after {days} days in the trash",
                            "Удалено профилей, пролежавших в корзине {days} дн.: {count}"),
    "act.detail.profiles": _t("{n} profiles", "Профилей: {n}"),
    "act.detail.unreadable": _t("{n} unreadable lines", "Нечитаемых строк: {n}"),
    "act.today": _t("Today", "Сегодня"),
    "act.yesterday": _t("Yesterday", "Вчера"),
    "act.field.name": _t("name", "название"),
    "act.field.notes": _t("notes", "заметки"),
    "act.field.tags": _t("tags", "теги"),
    "act.field.proxy": _t("proxy", "прокси"),
    "act.filter.all": _t("All", "Все"),
    "act.filter.profiles": _t("Profiles", "Профили"),
    "act.filter.proxies": _t("Proxies", "Прокси"),
    "act.filter.organize": _t("Tags and workspaces", "Теги и пространства"),
    "act.filter.errors": _t("Errors", "Ошибки"),
    # ------------------------------------------------------------ navigation
    "nav.activity": _t("Activity", "Активность"),
    "nav.trash": _t("Trash", "Корзина"),
    "settings.tab.general": _t("General", "Основные"),
    "settings.tab.check": _t("Fingerprint check", "Проверка отпечатка"),
    "settings.tab.logs": _t("Log", "Журнал"),
    "common.save": _t("Save", "Сохранить"),
    # -------------------------------------------------------------- sidebar
    "sidebar.workspaces": _t("Workspaces", "Пространства"),
    "sidebar.workspaces.create": _t("Create a workspace", "Создать пространство"),
    "sidebar.workspaces.none": _t("No workspace", "Без пространства"),
    "sidebar.tags.create": _t("Create a tag", "Создать тег"),
    "sidebar.tags.manage": _t("Manage tags", "Управление тегами"),
    "palette.workspace": _t("Workspace · {n} profiles", "Рабочее пространство · профилей: {n}"),
    # ----------------------------------------------------------- workspaces
    "workspace.none": _t("No workspace", "Без пространства"),
    "workspace.new.title": _t("New workspace", "Новое рабочее пространство"),
    "workspace.name.hint": _t("Client, project or team", "Клиент, проект или команда"),
    "workspace.edit": _t("Edit…", "Изменить…"),
    "workspace.edit.title": _t("Edit workspace", "Изменить рабочее пространство"),
    "workspace.delete": _t("Delete workspace", "Удалить пространство"),
    "workspace.delete.title": _t("Delete workspace “{name}”?", "Удалить пространство «{name}»?"),
    "workspace.delete.text": _t(
        "Its {n} profiles are not deleted: they just stay without a workspace.",
        "Профили ({n}) не удаляются: они просто останутся без рабочего пространства.",
    ),
    "toast.workspace.created": _t("Workspace “{name}” created", "Рабочее пространство «{name}» создано"),
    "toast.workspace.deleted": _t("Workspace “{name}” deleted", "Рабочее пространство «{name}» удалено"),
    "toast.moved": _t("{n} moved to “{name}”", "Перенесено в «{name}»: {n}"),
    "toast.unmoved": _t("{n} taken out of their workspace", "Убрано из пространства: {n}"),
    "field.color": _t("Colour", "Цвет"),
    # ------------------------------------------------------------------ tags
    "tags.add": _t("Tag", "Тег"),
    "tags.remove.tip": _t("Remove from this profile", "Убрать у этого профиля"),
    "tags.search": _t("Find a tag…", "Найти тег…"),
    "tags.none": _t("No tags yet. Create the first one below.", "Тегов пока нет. Создайте первый ниже."),
    "tags.none.match": _t("No such tag", "Такого тега нет"),
    "tags.new": _t("New tag", "Новый тег"),
    "tags.new.named": _t("Create “{name}”", "Создать «{name}»"),
    "tags.name": _t("Tag name", "Название тега"),
    "tags.create": _t("Create", "Создать"),
    "tags.new.title": _t("New tag", "Новый тег"),
    "tags.edit": _t("Rename or recolour…", "Переименовать или перекрасить…"),
    "tags.edit.title": _t("Edit tag", "Изменить тег"),
    "tags.delete": _t("Delete tag", "Удалить тег"),
    "tags.delete.tip": _t("Delete tag", "Удалить тег"),
    "tags.delete.title": _t("Delete tag “{name}”?", "Удалить тег «{name}»?"),
    "tags.delete.text": _t("It will be taken off {n} profiles.", "Он будет снят у профилей: {n}."),
    "tags.color.tip": _t("Change colour", "Сменить цвет"),
    "tags.count": _t("{n} profiles", "Профилей: {n}"),
    "tags.manage.title": _t("Tags", "Теги"),
    "tags.manage.subtitle": _t(
        "Create a tag once, then hand it out to profiles from the list.",
        "Создайте тег один раз и назначайте его профилям из списка.",
    ),
    "bulk.tags": _t("Tags", "Теги"),
    "bulk.workspace": _t("Workspace", "Пространство"),
    # ----------------------------------------------------------------- menus
    "menu.tags": _t("Tags…", "Теги…"),
    "menu.workspace": _t("Move to workspace", "В рабочее пространство"),
    "menu.trash": _t("Move to trash", "В корзину"),
    "toast.trashed": _t("Moved to trash: {name}", "В корзине: {name}"),
    "toast.trashed.many": _t("Moved to trash: {n} profiles", "В корзине профилей: {n}"),
    "toast.undo": _t("Undo", "Отменить"),
    "toast.restored": _t("Restored: {name}", "Восстановлено: {name}"),
    # ------------------------------------------------------------ filters
    "filter.cookies": _t("Cookies", "Cookies"),
    "filter.cookies.with": _t("Has cookies", "Есть"),
    "filter.cookies.without": _t("Empty", "Нет"),
    "filter.created": _t("Created", "Создан"),
    "filter.created.today": _t("Today", "Сегодня"),
    "filter.created.week": _t("7 days", "7 дней"),
    "filter.created.month": _t("30 days", "30 дней"),
    # ------------------------------------------------------------ the drawer
    "drawer.basic": _t("Basics", "Основное"),
    "drawer.info": _t("Information", "Информация"),
    "drawer.workspace": _t("Workspace", "Рабочее пространство"),
    "drawer.notes.hint": _t("A note only you see", "Заметка, которую видите только вы"),
    "drawer.screen": _t("Screen", "Экран"),
    "drawer.gpu": _t("Graphics", "Видеокарта"),
    "drawer.hardware": _t("Hardware", "Железо"),
    "drawer.cores": _t("{n} cores", "ядер: {n}"),
    "drawer.memory": _t("{n} GB RAM", "{n} ГБ ОЗУ"),
    "drawer.timezone": _t("Time zone", "Часовой пояс"),
    "drawer.created": _t("Created", "Создан"),
    "drawer.started": _t("Last start", "Последний запуск"),
    "drawer.cookies": _t("Cookies", "Cookies"),
    "drawer.settings": _t("All settings…", "Все настройки…"),
    "drawer.revert": _t("Revert", "Сбросить"),
    "drawer.unsaved": _t("Unsaved changes", "Есть несохранённые изменения"),
    # ------------------------------------------------------------------ trash
    "trash.title": _t("Trash", "Корзина"),
    "trash.restore": _t("Restore", "Восстановить"),
    "trash.purge": _t("Delete for good", "Удалить навсегда"),
    "trash.empty": _t("Empty trash", "Очистить корзину"),
    "trash.empty.title": _t("The trash is empty", "Корзина пуста"),
    "trash.empty.text": _t(
        "Deleted profiles wait here for {n} days: you can bring them back with all their cookies.",
        "Удалённые профили хранятся здесь {n} дн.: их можно вернуть вместе со всеми cookies.",
    ),
    "trash.empty.text.forever": _t(
        "Deleted profiles wait here until you delete them for good.",
        "Удалённые профили лежат здесь, пока вы не удалите их навсегда.",
    ),
    "trash.keep": _t("Kept", "Хранится"),
    "trash.left": _t("{n} d", "{n} дн."),
    "trash.keep.caption": _t("Keep for", "Хранить"),
    "trash.keep.days": _t("{n} days", "{n} дней"),
    "trash.keep.never": _t("Until I delete", "Пока не удалю"),
    "col.deleted": _t("Deleted", "Удалён"),
    "col.left": _t("Left", "Осталось"),
    "confirm.purge.title": _t("Delete “{name}” for good?", "Удалить «{name}» навсегда?"),
    "confirm.purge.many.title": _t("Delete {n} profiles for good?", "Удалить навсегда профили: {n}?"),
    "confirm.purge.text": _t(
        "Their cookies, history and saved logins are removed from this computer and cannot be brought back.",
        "Их cookies, история и сохранённые входы будут удалены с этого компьютера без возможности восстановления.",
    ),
    "confirm.empty.title": _t("Empty the trash?", "Очистить корзину?"),
    "confirm.empty.text": _t(
        "{n} profiles will be deleted for good, with their cookies and history.",
        "Профили ({n}) будут удалены навсегда вместе с cookies и историей.",
    ),
    "toast.purged": _t("Deleted for good: {n}", "Удалено навсегда: {n}"),
    # --------------------------------------------------------------- activity
    "activity.title": _t("Activity", "Активность"),
    "activity.search": _t("Search…", "Поиск…"),
    "activity.clear": _t("Clear history", "Очистить историю"),
    "activity.clear.title": _t("Clear the activity history?", "Очистить историю активности?"),
    "activity.clear.text": _t(
        "Only this list is cleared: profiles, proxies and tags stay as they are.",
        "Очищается только этот список: профили, прокси и теги останутся как есть.",
    ),
    "activity.empty.title": _t("Nothing has happened yet", "Пока ничего не происходило"),
    "activity.empty.text": _t(
        "Starts, stops, new profiles, proxies and everything else you do will be listed here.",
        "Здесь будут запуски, остановки, новые профили, прокси и всё остальное, что вы делаете.",
    ),
    # ---------------------------------------------------- tag / workspace errors
    "err.tag.notfound": _t("Tag with id={id} does not exist.", "Тег с id={id} не существует."),
    "err.tag.exists": _t("A tag named “{name}” already exists.", "Тег «{name}» уже есть."),
    "err.workspace.notfound": _t("Workspace with id={id} does not exist.", "Рабочее пространство с id={id} не существует."),
    "err.workspace.exists": _t("A workspace named “{name}” already exists.", "Рабочее пространство «{name}» уже есть."),
    # --------------------------------------------------------------------- log
    "log.app.started": _t("Application started", "Приложение запущено"),
    "log.app.exiting": _t("Application exiting", "Приложение завершается"),
    "log.session.started": _t("Log session started", "Сессия журнала начата"),
}
