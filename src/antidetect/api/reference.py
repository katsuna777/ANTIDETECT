"""The API reference: every method, every type, every error, in English and Russian.

One source for three readers: the "Instruction" view in the app, ``antidetect api docs`` and the
file ``docs/API.md``. A test checks it against the server's routes, so a method that is added
without being described fails the build.
"""

from __future__ import annotations

from dataclasses import dataclass

from antidetect.api.examples import examples

#: (English, Russian)
T = tuple[str, str]


def pick(text: T, lang: str) -> str:
    return text[1] if lang == "ru" else text[0]


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    desc: T
    required: bool = False


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    summary: T
    desc: T = ("", "")
    query: tuple[Field, ...] = ()
    body: tuple[Field, ...] = ()
    returns: str = ""
    request: str = ""
    response: str = ""


@dataclass(frozen=True)
class Group:
    key: str
    title: T
    endpoints: tuple[Endpoint, ...]


@dataclass(frozen=True)
class Model:
    name: str
    intro: T
    fields: tuple[Field, ...]


@dataclass(frozen=True)
class Tip:
    title: T
    text: T


# ------------------------------------------------------------------------------------- overview

TITLE: T = ("API instruction", "Инструкция по API")

INTRO: T = (
    "Run profiles from your scripts: start one, connect Playwright, Puppeteer or Selenium to the address you "
    "get back, and drive a browser that has its own fingerprint. JSON over HTTP on 127.0.0.1, this computer only.",
    "Управляйте профилями из скриптов: запустите профиль, подключите Playwright, Puppeteer или Selenium к "
    "полученному адресу и работайте в браузере со своим отпечатком. JSON поверх HTTP на 127.0.0.1, только на этом компьютере.",
)

#: The five steps as tiles: (title, the one line that matters)
FLOW: tuple[tuple[T, str], ...] = (
    (("Key", "Ключ"), "Authorization: Bearer …"),
    (("Profile", "Профиль"), "POST /v1/profiles"),
    (("Start", "Запуск"), "POST /v1/profiles/{id}/start"),
    (("Connect", "Подключение"), "connection.ws"),
    (("Stop", "Остановка"), "POST /v1/profiles/{id}/stop"),
)

QUICKSTART: tuple[T, ...] = (
    ("Turn the API on (the switch on the API page) and copy a key.",
     "Включите API (переключатель на странице API) и скопируйте ключ."),
    ("Create a profile: POST /v1/profiles with a name (and a proxy if you have one).",
     "Создайте профиль: POST /v1/profiles с именем (и прокси, если он есть)."),
    ("Start it: POST /v1/profiles/{id}/start. The answer holds connection.ws, the address of the running browser.",
     "Запустите его: POST /v1/profiles/{id}/start. В ответе будет connection.ws — адрес запущенного браузера."),
    ("Connect Playwright, Puppeteer or Selenium to that address (see “Connecting tools” below) and work as usual.",
     "Подключите Playwright, Puppeteer или Selenium к этому адресу (см. «Подключение инструментов» ниже) и работайте как обычно."),
    ("Stop the profile when you are done: POST /v1/profiles/{id}/stop. Cookies and logins stay in it.",
     "Когда закончите, остановите профиль: POST /v1/profiles/{id}/stop. Cookies и входы в нём сохранятся."),
)

AUTH: tuple[T, ...] = (
    ("Every request except GET /v1/health must carry an access key:",
     "Каждый запрос, кроме GET /v1/health, должен содержать ключ доступа:"),
    ("Authorization: Bearer <key>", "Authorization: Bearer <ключ>"),
    ("The header X-API-Key: <key> works too. You can make as many keys as you like (one per script, machine or "
     "teammate), rename them, regenerate or delete them on the API page; a deleted key stops working at once.",
     "Подойдёт и заголовок X-API-Key: <ключ>. Ключей можно сделать сколько угодно (по одному на скрипт, компьютер "
     "или коллегу), переименовывать, перевыпускать и удалять на странице API; удалённый ключ перестаёт работать сразу."),
    ("Requests from web pages are refused (no CORS, a request with an Origin header gets 403), and the server "
     "listens on 127.0.0.1 only. Never put a key into a public repository.",
     "Запросы из веб-страниц отклоняются (CORS нет, запрос с заголовком Origin получает 403), а сервер слушает "
     "только 127.0.0.1. Не кладите ключ в публичный репозиторий."),
)

CONVENTIONS: tuple[T, ...] = (
    ("The base address is http://127.0.0.1:<port>/v1. Bodies are JSON (UTF-8); send Content-Length.",
     "Базовый адрес — http://127.0.0.1:<порт>/v1. Тела запросов — JSON (UTF-8), указывайте Content-Length."),
    ("Success is 200 (201 when something was created). A failure is 4xx/5xx with "
     "{\"error\": {\"code\": \"...\", \"message\": \"...\"}}: branch on code, show message to people.",
     "Успех — 200 (201, если что-то создано). Ошибка — 4xx/5xx с телом "
     "{\"error\": {\"code\": \"...\", \"message\": \"...\"}}: ветвитесь по code, а message показывайте людям."),
    ("Times are ISO 8601 in UTC (2026-10-05T14:28:39Z). Lists answer {\"total\": n, \"items\": [...]}.",
     "Время — ISO 8601 в UTC (2026-10-05T14:28:39Z). Списки отвечают {\"total\": n, \"items\": [...]}."),
    ("Types: string, integer, number, boolean, object, X[] (a list of X), X | null (may be absent or null).",
     "Типы: string (строка), integer (целое), number (число), boolean (да/нет), object, X[] (список X), "
     "X | null (может быть пустым)."),
)

CONNECT_INTRO: T = (
    "Each script below makes a profile (or reuses “shop-1”), starts it, connects to the address from the answer, opens "
    "a page and stops the profile. Replace the address and the key with yours (the app fills them in for you).",
    "Каждый скрипт ниже создаёт профиль (или берёт существующий «shop-1»), запускает его, подключается по адресу из "
    "ответа, открывает страницу и останавливает профиль. Подставьте свой адрес и ключ (приложение подставляет их за вас).",
)

# -------------------------------------------------------------------------------------- models

_PROFILE_JSON = """{
  "id": 3,
  "name": "shop-1",
  "status": "stopped",
  "tags": ["eu", "shop"],
  "workspace": "Clients",
  "notes": "",
  "start_url": null,
  "geo_auto": true,
  "webrtc": "auto",
  "noise_canvas": true,
  "noise_audio": true,
  "theme": "light",
  "platform": "windows",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
  "language": "de",
  "locale": "de-DE",
  "timezone": "Europe/Berlin",
  "screen": "1920x1080",
  "cores": 8,
  "memory_gb": 8,
  "proxy": null,
  "connection": null,
  "created_at": "2026-10-05T14:28:39Z",
  "last_started_at": null,
  "last_stopped_at": null
}"""

_RUNNING_JSON = """{
  "id": 3,
  "name": "shop-1",
  "status": "running",
  "already_running": false,
  "connection": {
    "ws": "ws://127.0.0.1:60746/devtools/browser/6d07c7e6-ec83-43de-b818-7592b0cd0c1c",
    "http": "http://127.0.0.1:60746",
    "port": 60746,
    "debugger_address": "127.0.0.1:60746",
    "pid": 15562
  },
  "...": "…"
}"""

_PROXY_JSON = """{
  "id": 5,
  "type": "socks5",
  "host": "203.0.113.10",
  "port": 1080,
  "username": "user",
  "has_password": true,
  "country": "Germany",
  "country_code": "DE",
  "status": "working",
  "latency_ms": 312,
  "ip": "203.0.113.10",
  "source": "manual",
  "checked_at": "2026-10-05T14:30:02Z"
}"""

MODELS: tuple[Model, ...] = (
    Model("Profile", ("A browser profile: its own fingerprint, cookies and (optionally) proxy.",
                      "Профиль браузера: свой отпечаток, свои cookies и (по желанию) прокси."), (
        Field("id", "integer", ("Profile number.", "Номер профиля.")),
        Field("name", "string", ("Unique name.", "Уникальное имя.")),
        Field("status", "string", ("\"running\" or \"stopped\".", "\"running\" (запущен) или \"stopped\" (остановлен).")),
        Field("tags", "string[]", ("Labels you put on the profile.", "Метки профиля.")),
        Field("workspace", "string | null", ("The workspace the profile is in (a group of profiles you made in the app).", "Рабочее пространство профиля (группа профилей, созданная в приложении).")),
        Field("notes", "string", ("Free-form notes.", "Заметки.")),
        Field("start_url", "string | null", ("Page opened at start (instead of a new tab).", "Страница, открываемая при запуске (вместо новой вкладки).")),
        Field("geo_auto", "boolean", ("Time zone and language follow the exit IP address.", "Часовой пояс и язык подстраиваются под IP-адрес выхода.")),
        Field("webrtc", "string", ("What WebRTC may do: \"auto\" (hidden while a proxy is set), \"block\" (always hidden) or \"allow\" (left alone).", "Что может WebRTC: \"auto\" (скрыт, пока задан прокси), \"block\" (скрыт всегда) или \"allow\" (не трогается).")),
        Field("noise_canvas", "boolean", ("The profile's picture (canvas) fingerprint is made unique.", "Отпечаток картинки (canvas) делается уникальным у профиля.")),
        Field("noise_audio", "boolean", ("The same for the sound fingerprint.", "То же для отпечатка звука.")),
        Field("theme", "string", ("The colour scheme sites are told the profile prefers: \"light\" (default for new profiles), \"dark\" or \"auto\" (follow the computer, as profiles made earlier do).", "Цветовая схема, которую профиль сообщает сайтам: \"light\" (по умолчанию у новых профилей), \"dark\" или \"auto\" (как в системе, так работают профили, созданные раньше).")),
        Field("platform", "string | null", ("Operating system shown to sites: \"windows\", \"macos\" or \"linux\".", "ОС, которую видят сайты: \"windows\", \"macos\" или \"linux\".")),
        Field("user_agent", "string | null", ("The User-Agent the browser sends.", "User-Agent, который отправляет браузер.")),
        Field("language", "string | null", ("Main language, e.g. \"de\".", "Основной язык, например \"de\".")),
        Field("locale", "string | null", ("Locale, e.g. \"de-DE\".", "Региональные настройки, например \"de-DE\".")),
        Field("timezone", "string | null", ("IANA time zone, e.g. \"Europe/Berlin\".", "Часовой пояс IANA, например \"Europe/Berlin\".")),
        Field("screen", "string | null", ("Screen size \"WIDTHxHEIGHT\", e.g. \"1920x1080\".", "Размер экрана «ШИРИНАxВЫСОТА», например \"1920x1080\".")),
        Field("cores", "integer | null", ("Processor cores shown to sites.", "Число ядер процессора, которое видят сайты.")),
        Field("memory_gb", "number | null", ("Memory (GB) shown to sites.", "Память (ГБ), которую видят сайты.")),
        Field("proxy", "Proxy | null", ("The assigned proxy, or null for a direct connection.", "Назначенный прокси или null — прямое соединение.")),
        Field("connection", "Connection | null", ("Where to connect to the running browser; null while it is stopped.", "Куда подключаться к запущенному браузеру; null, пока он остановлен.")),
        Field("created_at", "string", ("When it was created.", "Когда создан.")),
        Field("last_started_at", "string | null", ("When it was started last.", "Когда запускался в последний раз.")),
        Field("last_stopped_at", "string | null", ("When it was stopped last.", "Когда останавливался в последний раз.")),
        Field("already_running", "boolean", ("Only in the answer to start: true if the profile was running already.", "Только в ответе на start: true, если профиль уже был запущен.")),
    )),
    Model("Connection", ("How to attach an automation tool to a running profile.",
                         "Как подключить инструмент автоматизации к запущенному профилю."), (
        Field("ws", "string", ("The address for Playwright (connect_over_cdp) and Puppeteer (browserWSEndpoint).", "Адрес для Playwright (connect_over_cdp) и Puppeteer (browserWSEndpoint).")),
        Field("debugger_address", "string", ("host:port for Selenium (debugger_address).", "host:port для Selenium (debugger_address).")),
        Field("http", "string", ("The same browser over HTTP (for tools that want a URL).", "Тот же браузер по HTTP (для инструментов, которым нужен URL).")),
        Field("port", "integer", ("The debugging port.", "Порт отладки.")),
        Field("pid", "integer | null", ("The browser process id.", "Номер процесса браузера.")),
    )),
    Model("Proxy", ("A proxy from your list. The password is never returned.",
                    "Прокси из вашего списка. Пароль никогда не возвращается."), (
        Field("id", "integer", ("Proxy number.", "Номер прокси.")),
        Field("type", "string", ("\"http\", \"https\" or \"socks5\".", "\"http\", \"https\" или \"socks5\".")),
        Field("host", "string", ("Address.", "Адрес.")),
        Field("port", "integer", ("Port.", "Порт.")),
        Field("username", "string | null", ("Login, if it has one.", "Логин, если есть.")),
        Field("has_password", "boolean", ("Whether a password is stored.", "Сохранён ли пароль.")),
        Field("country", "string | null", ("Exit country name (known after a check).", "Страна выхода (известна после проверки).")),
        Field("country_code", "string | null", ("Two-letter country code, e.g. \"DE\".", "Двухбуквенный код страны, например \"DE\".")),
        Field("status", "string", ("\"unknown\" (not checked), \"working\", \"dead\" or \"error\".", "\"unknown\" (не проверен), \"working\" (работает), \"dead\" (не работает) или \"error\" (ошибка).")),
        Field("latency_ms", "integer | null", ("Response time of the last check.", "Время ответа при последней проверке.")),
        Field("ip", "string | null", ("The IP address sites see through it.", "IP-адрес, который видят сайты через него.")),
        Field("source", "string | null", ("\"manual\" for proxies you added.", "\"manual\" для прокси, которые добавили вы.")),
        Field("checked_at", "string | null", ("When it was checked last.", "Когда проверялся в последний раз.")),
    )),
    Model("Cookie", ("A cookie in the format of Chrome DevTools. Exports of the common cookie-editor extensions are accepted too.",
                     "Cookie в формате Chrome DevTools. Экспорт популярных расширений-редакторов cookie тоже принимается."), (
        Field("name", "string", ("Name.", "Имя."), True),
        Field("value", "string", ("Value.", "Значение."), True),
        Field("domain", "string", ("Domain, e.g. \".example.com\". Needed unless url is given.", "Домен, например \".example.com\". Нужен, если не указан url."), True),
        Field("url", "string", ("Instead of domain: the address the cookie belongs to.", "Вместо domain: адрес, к которому относится cookie.")),
        Field("path", "string", ("Path, default \"/\".", "Путь, по умолчанию \"/\".")),
        Field("expires", "number", ("Expiry in Unix seconds; leave out (or -1) for a session cookie. expirationDate is accepted as well.", "Срок действия в секундах Unix; не указывайте (или -1) для сессионной cookie. Подходит и expirationDate.")),
        Field("httpOnly", "boolean", ("Hidden from page scripts.", "Скрыта от скриптов страницы.")),
        Field("secure", "boolean", ("Sent over HTTPS only.", "Отправляется только по HTTPS.")),
        Field("sameSite", "string", ("\"Strict\", \"Lax\" or \"None\".", "\"Strict\", \"Lax\" или \"None\".")),
    )),
    Model("Error", ("What every failed request answers.", "Ответ на любой неудачный запрос."), (
        Field("error.code", "string", ("A stable name of the problem (see the table of errors).", "Постоянное имя проблемы (см. таблицу ошибок).")),
        Field("error.message", "string", ("A sentence for people.", "Фраза для людей.")),
    )),
)

# ------------------------------------------------------------------------------------ endpoints

_ID = ("{id}", "{id}")

GROUPS: tuple[Group, ...] = (
    Group("service", ("Service", "Служебные"), (
        Endpoint("GET", "/v1/health", ("Is the API up?", "API работает?"),
                 ("The only method that needs no key. Handy for waiting until the app is ready.",
                  "Единственный метод без ключа. Удобен, чтобы дождаться готовности приложения."),
                 returns="{ok, app}", response='{"ok": true, "app": "antidetect"}'),
        Endpoint("GET", "/v1/status", ("App status", "Состояние приложения"),
                 ("Version, how many profiles exist and run, and which browser is used.",
                  "Версия, сколько профилей существует и запущено, какой браузер используется."),
                 returns="{ok, version, profiles, running, browser}",
                 response='{\n  "ok": true,\n  "version": "0.2.0",\n  "profiles": 12,\n  "running": 2,\n'
                          '  "browser": {"path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "version": "154.0.8037.93"}\n}'),
    )),
    Group("profiles", ("Profiles", "Профили"), (
        Endpoint("GET", "/v1/profiles", ("List profiles", "Список профилей"),
                 ("In the order the profiles were created. Filters combine.", "В порядке создания профилей. Фильтры сочетаются."),
                 query=(
                     Field("tag", "string", ("Only profiles with this tag.", "Только профили с этим тегом.")),
                     Field("workspace", "string", ("Only profiles of this workspace.", "Только профили этого рабочего пространства.")),
                     Field("status", "string", ("\"running\" or \"stopped\".", "\"running\" или \"stopped\".")),
                     Field("q", "string", ("Part of the name.", "Часть имени.")),
                     Field("limit", "integer", ("How many to return (default 500, at most 5000).", "Сколько вернуть (по умолчанию 500, максимум 5000).")),
                     Field("offset", "integer", ("How many to skip (default 0).", "Сколько пропустить (по умолчанию 0).")),
                 ),
                 returns="{total, items: Profile[]}",
                 response='{"total": 1, "items": [ ...Profile... ]}'),
        Endpoint("POST", "/v1/profiles", ("Create a profile", "Создать профиль"),
                 ("Every profile gets its own fingerprint. With a proxy, the time zone and language match its country.",
                  "Каждый профиль получает свой отпечаток. С прокси часовой пояс и язык подбираются под его страну."),
                 body=(
                     Field("name", "string", ("Unique name, at most 200 characters.", "Уникальное имя, не длиннее 200 символов."), True),
                     Field("platform", "string", ("\"windows\", \"macos\" or \"linux\". Default: this computer's system (the most natural choice).", "\"windows\", \"macos\" или \"linux\". По умолчанию — система этого компьютера (самый естественный выбор).")),
                     Field("proxy", "string | object | null", ("A proxy to add and assign: \"user:pass@host:port\", \"socks5://host:port\", \"host:port:user:pass\", or {\"type\", \"host\", \"port\", \"username\", \"password\"}. It is checked first, so the country is known.", "Прокси, который нужно добавить и назначить: \"user:pass@host:port\", \"socks5://host:port\", \"host:port:user:pass\" или {\"type\", \"host\", \"port\", \"username\", \"password\"}. Он сначала проверяется, чтобы узнать страну.")),
                     Field("proxy_id", "integer | null", ("Instead of proxy: the id of a proxy that is already in your list.", "Вместо proxy: номер прокси, который уже есть в списке.")),
                     Field("proxy_type", "string", ("\"http\", \"https\" or \"socks5\" for a proxy string that does not say.", "\"http\", \"https\" или \"socks5\" для строки прокси без указания типа.")),
                     Field("check_proxy", "boolean", ("false to skip the check of a new proxy (default true).", "false — не проверять новый прокси (по умолчанию true).")),
                     Field("tags", "string[] | string", ("Tags; a comma-separated string works too. Unknown tags are created.", "Теги; подойдёт и строка через запятую. Неизвестные теги создаются.")),
                     Field("workspace", "string | null", ("Workspace name; it is created when it does not exist yet.", "Название рабочего пространства; если его нет — оно создаётся.")),
                     Field("notes", "string", ("Notes.", "Заметки.")),
                     Field("start_url", "string", ("Page to open at start.", "Страница, открываемая при запуске.")),
                     Field("geo_auto", "boolean", ("Match time zone and language to the IP (default true).", "Подстраивать часовой пояс и язык под IP (по умолчанию true).")),
                     Field("webrtc", "string", ("\"auto\" (default), \"block\" or \"allow\"; see Profile.", "\"auto\" (по умолчанию), \"block\" или \"allow\"; см. Profile.")),
                     Field("noise_canvas / noise_audio", "boolean", ("Fingerprint noise on or off (default true).", "Шум отпечатка включён или выключен (по умолчанию true).")),
                     Field("theme", "string", ("\"light\" (default), \"dark\" or \"auto\"; see Profile.", "\"light\" (по умолчанию), \"dark\" или \"auto\"; см. Profile.")),
                     Field("start", "boolean", ("true to start it right away; the answer then holds connection.", "true — сразу запустить; тогда в ответе будет connection.")),
                 ),
                 returns="Profile (201)",
                 request='{\n  "name": "shop-1",\n  "platform": "windows",\n  "proxy": "user:pass@203.0.113.10:8080",\n  "tags": ["eu"],\n  "start": true\n}',
                 response=_RUNNING_JSON),
        Endpoint("GET", "/v1/profiles/{id}", ("Get a profile", "Получить профиль"),
                 returns="Profile", response=_PROFILE_JSON),
        Endpoint("PATCH", "/v1/profiles/{id}", ("Change a profile", "Изменить профиль"),
                 ("Only the fields you send change. A new proxy or fingerprint applies at the next start.",
                  "Меняются только присланные поля. Новый прокси или отпечаток применяются при следующем запуске."),
                 body=(
                     Field("name", "string", ("New name.", "Новое имя.")),
                     Field("notes", "string", ("Notes.", "Заметки.")),
                     Field("tags", "string[] | string", ("Tags (replaces the old ones).", "Теги (заменяют прежние).")),
                     Field("workspace", "string | null", ("Move to this workspace (created when missing); null takes the profile out of its workspace.", "Перенести в это рабочее пространство (создаётся, если нет); null — вынуть профиль из пространства.")),
                     Field("start_url", "string", ("Page to open at start (\"\" to clear).", "Страница при запуске (\"\" — убрать).")),
                     Field("geo_auto", "boolean", ("Follow the IP for time zone and language.", "Подстраивать часовой пояс и язык под IP.")),
                     Field("webrtc", "string", ("\"auto\", \"block\" or \"allow\"; applies at the next start.", "\"auto\", \"block\" или \"allow\"; применяется при следующем запуске.")),
                     Field("noise_canvas / noise_audio", "boolean", ("Fingerprint noise on or off.", "Шум отпечатка включён или выключен.")),
                     Field("theme", "string", ("\"light\", \"dark\" or \"auto\"; applies at the next start.", "\"light\", \"dark\" или \"auto\"; применяется при следующем запуске.")),
                     Field("proxy / proxy_id", "string | object | integer | null", ("As when creating; null removes the proxy.", "Как при создании; null убирает прокси.")),
                     Field("platform", "string", ("Give the profile a new fingerprint for this system.", "Выдать профилю новый отпечаток для этой системы.")),
                     Field("regenerate_fingerprint", "boolean", ("true: a fresh fingerprint for the same system.", "true: новый отпечаток для той же системы.")),
                 ),
                 returns="Profile",
                 request='{"name": "shop-2", "tags": ["eu", "vip"], "proxy": null}', response=_PROFILE_JSON),
        Endpoint("DELETE", "/v1/profiles/{id}", ("Delete a profile", "Удалить профиль"),
                 ("Stops it first, then moves it to the trash: it vanishes from every list, and you can restore it "
                  "in the app (Trash) until it is deleted for good. With permanent=true its folder with cookies and history is removed at once.",
                  "Сначала останавливает, затем переносит в корзину: профиль пропадает из всех списков, "
                  "а в приложении (Корзина) его можно вернуть, пока он не удалён окончательно. С permanent=true папка с cookies и историей удаляется сразу."),
                 query=(Field("permanent", "boolean", ("true: delete for good instead of moving to the trash.", "true: удалить навсегда, а не в корзину.")),),
                 returns="{id, deleted, trashed}", response='{"id": 3, "deleted": true, "trashed": true}'),
        Endpoint("POST", "/v1/profiles/{id}/start", ("Start a profile", "Запустить профиль"),
                 ("Returns when the browser is ready (a few seconds; up to ~30 with a slow proxy). Idempotent: "
                  "if it already runs you get 200 with already_running true and the same connection. "
                  "Two scripts starting the same profile launch it once.",
                  "Отвечает, когда браузер готов (несколько секунд; до ~30 с с медленным прокси). Идемпотентен: "
                  "если профиль уже запущен — 200 с already_running true и тем же connection. "
                  "Два скрипта, запускающие один профиль, запустят его один раз."),
                 returns="Profile (+ already_running)", response=_RUNNING_JSON),
        Endpoint("POST", "/v1/profiles/{id}/stop", ("Stop a profile", "Остановить профиль"),
                 ("Closes the browser properly; cookies and logins stay. Stopping a stopped profile is fine.",
                  "Корректно закрывает браузер; cookies и входы сохраняются. Остановка уже остановленного профиля — не ошибка."),
                 returns="Profile", response='{"id": 3, "status": "stopped", "connection": null, "...": "..."}'),
        Endpoint("GET", "/v1/profiles/{id}/connection", ("Where to connect", "Куда подключаться"),
                 ("The address of a running profile (409 not_running if it is stopped).",
                  "Адрес запущенного профиля (409 not_running, если он остановлен)."),
                 returns="Connection",
                 response='{\n  "ws": "ws://127.0.0.1:60746/devtools/browser/6d07c7e6-...",\n  "http": "http://127.0.0.1:60746",\n'
                          '  "port": 60746,\n  "debugger_address": "127.0.0.1:60746",\n  "pid": 15562\n}'),
        Endpoint("POST", "/v1/profiles/{id}/open", ("Open a page", "Открыть страницу"),
                 ("Opens an address in a new tab of a running profile. Only http:// and https:// addresses.",
                  "Открывает адрес в новой вкладке запущенного профиля. Только адреса http:// и https://."),
                 body=(Field("url", "string", ("The address.", "Адрес."), True),),
                 returns="{id, opened}", request='{"url": "https://example.com"}', response='{"id": 3, "opened": "https://example.com"}'),
        Endpoint("GET", "/v1/profiles/{id}/cookies", ("Read cookies", "Прочитать cookies"),
                 ("All cookies of a running profile.", "Все cookies запущенного профиля."),
                 returns="{count, cookies: Cookie[]}",
                 response='{"count": 1, "cookies": [{"name": "sid", "value": "abc", "domain": "example.com", "path": "/", "expires": -1, "httpOnly": true, "secure": true, "sameSite": "Lax"}]}'),
        Endpoint("POST", "/v1/profiles/{id}/cookies", ("Add cookies", "Добавить cookies"),
                 ("Puts cookies into a running profile (existing ones with the same name, domain and path are replaced). "
                  "Send a list, or {\"cookies\": [...]}.",
                  "Кладёт cookies в запущенный профиль (существующие с тем же именем, доменом и путём заменяются). "
                  "Присылайте список или {\"cookies\": [...]}."),
                 body=(Field("cookies", "Cookie[]", ("The cookies (at most 20 000).", "Cookies (не больше 20 000)."), True),),
                 returns="{imported}",
                 request='{"cookies": [{"name": "sid", "value": "abc", "domain": ".example.com", "path": "/", "secure": true}]}',
                 response='{"imported": 1}'),
        Endpoint("DELETE", "/v1/profiles/{id}/cookies", ("Clear cookies", "Очистить cookies"),
                 ("Deletes every cookie of a running profile.", "Удаляет все cookies запущенного профиля."),
                 returns="{cleared}", response='{"cleared": true}'),
    )),
    Group("proxies", ("Proxies", "Прокси"), (
        Endpoint("GET", "/v1/proxies", ("List proxies", "Список прокси"),
                 query=(
                     Field("status", "string", ("\"unknown\", \"working\", \"dead\" or \"error\".", "\"unknown\", \"working\", \"dead\" или \"error\".")),
                     Field("limit", "integer", ("How many to return (default 500, at most 5000).", "Сколько вернуть (по умолчанию 500, максимум 5000).")),
                     Field("offset", "integer", ("How many to skip.", "Сколько пропустить.")),
                 ),
                 returns="{total, items: Proxy[]}", response='{"total": 1, "items": [ ...Proxy... ]}'),
        Endpoint("POST", "/v1/proxies", ("Add proxies", "Добавить прокси"),
                 ("A proxy you add that is already in the list is reused, not duplicated.",
                  "Прокси, который уже есть в списке, не дублируется, а используется повторно."),
                 body=(
                     Field("proxies", "(string | object)[] | string", ("The proxies: strings like \"user:pass@host:port\", objects {type, host, port, username, password}, or text with one proxy per line.", "Прокси: строки вида \"user:pass@host:port\", объекты {type, host, port, username, password} или текст по одному прокси в строке."), True),
                     Field("type", "string", ("\"http\", \"https\" or \"socks5\" for strings that do not say.", "\"http\", \"https\" или \"socks5\" для строк без указания типа.")),
                     Field("check", "boolean", ("true to check them now (default false).", "true — проверить сразу (по умолчанию false).")),
                 ),
                 returns="{added, existing, invalid, items: Proxy[]}",
                 request='{"proxies": ["user:pass@203.0.113.10:8080", "socks5://203.0.113.11:1080"], "check": true}',
                 response='{"added": 2, "existing": 0, "invalid": [], "items": [ ...Proxy... ]}'),
        Endpoint("POST", "/v1/proxies/{id}/check", ("Check a proxy", "Проверить прокси"),
                 ("Makes a real request through it; fills in country, ping and status.",
                  "Делает настоящий запрос через него; заполняет страну, пинг и статус."),
                 returns="Proxy", response=_PROXY_JSON),
        Endpoint("DELETE", "/v1/proxies/{id}", ("Delete a proxy", "Удалить прокси"),
                 ("Profiles that used it become proxy-less.", "Профили, которые его использовали, остаются без прокси."),
                 returns="{id, deleted}", response='{"id": 5, "deleted": true}'),
    )),
)

# --------------------------------------------------------------------------------------- errors

ERRORS: tuple[tuple[int, str, T], ...] = (
    (400, "bad_request", ("A field is missing or has the wrong type; message says which.", "Поле не указано или имеет неверный тип; message скажет, какое.")),
    (400, "bad_json", ("The body is not valid JSON.", "Тело запроса — не корректный JSON.")),
    (401, "unauthorized", ("No key, or a wrong one.", "Ключа нет или он неверный.")),
    (403, "forbidden_origin", ("The request came from a web page (it has an Origin header).", "Запрос пришёл из веб-страницы (есть заголовок Origin).")),
    (403, "forbidden_host", ("The request was not addressed to 127.0.0.1.", "Запрос адресован не на 127.0.0.1.")),
    (404, "not_found", ("No such method.", "Такого метода нет.")),
    (404, "profile_not_found", ("No profile with this id.", "Нет профиля с таким номером.")),
    (404, "proxy_not_found", ("No proxy with this id.", "Нет прокси с таким номером.")),
    (405, "method_not_allowed", ("The method exists, but not with this HTTP verb (see the Allow header).", "Метод есть, но не с этим HTTP-глаголом (см. заголовок Allow).")),
    (409, "profile_exists", ("A profile with this name already exists.", "Профиль с таким именем уже есть.")),
    (409, "not_running", ("The profile is not running; start it first.", "Профиль не запущен; сначала запустите его.")),
    (409, "cookie_error", ("The cookies could not be handled.", "Не удалось обработать cookies.")),
    (413, "too_large", ("The body is larger than 8 MB.", "Тело запроса больше 8 МБ.")),
    (422, "proxy_unreadable", ("The proxy string could not be understood.", "Строку прокси не удалось разобрать.")),
    (422, "proxy_unusable", ("The proxy exists but cannot be used (dead).", "Прокси есть, но им нельзя пользоваться (не работает).")),
    (500, "browser_error", ("The browser could not be started; message has the reason (a proxy that does not answer, a failed pre-launch check).", "Браузер не удалось запустить; в message причина (прокси не отвечает, не прошла проверка перед запуском).")),
    (500, "stealth_failed", ("The browser started but the fingerprint could not be applied; it was closed.", "Браузер запустился, но отпечаток применить не удалось; браузер закрыт.")),
    (500, "internal_error", ("A bug; the details are on the Log page.", "Ошибка в программе; подробности на странице «Журнал».")),
    (503, "browser_not_found", ("No Chrome is installed (or chosen in Settings).", "Chrome не установлен (или не выбран в настройках).")),
    (503, "connection_unavailable", ("The browser has not published its address yet; retry in a second.", "Браузер ещё не сообщил свой адрес; повторите через секунду.")),
)

# ------------------------------------------------------------------------------------------ tips

TIPS: tuple[Tip, ...] = (
    Tip(("Do not resize the window through automation", "Не меняйте размер окна через автоматизацию"),
        ("The profile has its own screen. Tools that set a viewport replace it, and the site then sees a size that does not fit the "
         "profile. Playwright: work in browser.contexts[0], or make a new context with no_viewport=True (a plain new_context() "
         "forces 1280×720). Puppeteer: connect with defaultViewport: null (its default forces 800×600 and even lets the real "
         "screen of your computer show). Selenium: nothing to set.",
         "У профиля свой экран. Инструменты, задающие размер окна, подменяют его, и сайт видит размер, который не подходит к профилю. "
         "Playwright: работайте в browser.contexts[0] или создавайте контекст с no_viewport=True (обычный new_context() "
         "принудительно ставит 1280×720). Puppeteer: подключайтесь с defaultViewport: null (по умолчанию он ставит 800×600 и "
         "даже показывает реальный экран вашего компьютера). Selenium: настраивать ничего не нужно.")),
    Tip(("Disconnecting does not stop the profile", "Отключение не останавливает профиль"),
        ("browser.close() (Playwright), browser.disconnect() (Puppeteer) and driver.quit() (Selenium) only let go of the browser, "
         "which keeps running. Stop it with POST /v1/profiles/{id}/stop. Closing the last tab does close the browser.",
         "browser.close() (Playwright), browser.disconnect() (Puppeteer) и driver.quit() (Selenium) лишь отпускают браузер, "
         "он продолжает работать. Остановить его можно запросом POST /v1/profiles/{id}/stop. Закрытие последней вкладки "
         "закрывает браузер.")),
    Tip(("The fingerprint is applied while the app is open", "Отпечаток применяется, пока приложение открыто"),
        ("The layer that applies the fingerprint lives in the app. If you quit it, a tab opened later in a running profile is not "
         "covered. Keep the app open while scripts work, or run it without a window: antidetect api serve.",
         "Слой, который применяет отпечаток, живёт в приложении. Если закрыть его, вкладка, открытая позже в запущенном профиле, "
         "защищена не будет. Держите приложение открытым, пока работают скрипты, или запустите его без окна: antidetect api serve.")),
    Tip(("Starting takes time", "Запуск занимает время"),
        ("A start waits for the browser and, with a proxy, for a check of it: allow 60 seconds in your HTTP client. You can start "
         "many different profiles at once; the same profile is started once.",
         "Запуск ждёт браузер и, если есть прокси, его проверку: задайте HTTP-клиенту таймаут 60 секунд. Разные профили можно "
         "запускать одновременно; один и тот же профиль запустится один раз.")),
    Tip(("Be gentle with accounts", "Бережно относитесь к аккаунтам"),
        ("Automation tools talk to the browser through the DevTools protocol, and some sites can notice that. For valuable "
         "accounts log in by hand in the app first, then let the script do the light work, at human speed.",
         "Инструменты автоматизации управляют браузером через протокол DevTools, и некоторые сайты это замечают. Для ценных "
         "аккаунтов сначала войдите вручную в приложении, а скрипту оставьте лёгкую работу в человеческом темпе.")),
    Tip(("Cookies", "Cookies"),
        ("Reading and writing cookies works on a running profile: start it, then call the cookie methods. To move a login "
         "between profiles: GET the cookies of one, POST them into another.",
         "Чтение и запись cookies работают у запущенного профиля: запустите его, затем вызывайте методы cookies. Чтобы "
         "перенести вход между профилями: получите cookies одного (GET) и отправьте их другому (POST).")),
    Tip(("From the command line", "Из командной строки"),
        ("antidetect api serve runs the API without the window; antidetect api keys manages keys; antidetect api examples "
         "prints ready scripts; antidetect api docs prints this instruction.",
         "antidetect api serve запускает API без окна; antidetect api keys управляет ключами; antidetect api examples "
         "печатает готовые скрипты; antidetect api docs печатает эту инструкцию.")),
)

SECTION_TITLES: dict[str, T] = {
    "quickstart": ("Quick start", "Быстрый старт"),
    "auth": ("Access keys", "Ключи доступа"),
    "conventions": ("Conventions", "Общие правила"),
    "connect": ("Connecting tools", "Подключение инструментов"),
    "methods": ("Methods", "Методы"),
    "types": ("Types", "Типы"),
    "errors": ("Errors", "Ошибки"),
    "tips": ("Good to know", "Полезно знать"),
}
FIELD_HEADERS: dict[str, T] = {
    "name": ("Field", "Поле"), "type": ("Type", "Тип"), "required": ("Required", "Обязательно"),
    "desc": ("Description", "Описание"), "status": ("HTTP", "HTTP"), "code": ("Code", "Код"),
    "meaning": ("Meaning", "Значение"),
}
LABELS: dict[str, T] = {
    "query": ("Query parameters", "Параметры запроса (query)"),
    "body": ("JSON body", "Тело запроса (JSON)"),
    "returns": ("Returns", "Возвращает"),
    "request": ("Example request", "Пример запроса"),
    "response": ("Example response", "Пример ответа"),
    "yes": ("yes", "да"),
}


def endpoint_key(method: str, path: str) -> str:
    return f"{method} {path}"


def all_endpoints() -> list[Endpoint]:
    return [endpoint for group in GROUPS for endpoint in group.endpoints]


# -------------------------------------------------------------------------------------- markdown

def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    out += ["| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in row) + " |" for row in rows]
    return out + [""]


def _fields_table(fields: tuple[Field, ...], lang: str, *, required: bool) -> list[str]:
    headers = [pick(FIELD_HEADERS["name"], lang), pick(FIELD_HEADERS["type"], lang)]
    if required:
        headers.append(pick(FIELD_HEADERS["required"], lang))
    headers.append(pick(FIELD_HEADERS["desc"], lang))
    rows = []
    for f in fields:
        row = [f"`{f.name}`", f"`{f.type}`"]
        if required:
            row.append(pick(LABELS["yes"], lang) if f.required else "")
        row.append(pick(f.desc, lang))
        rows.append(row)
    return _table(headers, rows)


def render_markdown(lang: str = "ru") -> str:
    """The whole reference as one Markdown document."""
    t = lambda text: pick(text, lang)                                                    # noqa: E731
    out = [f"# {t(TITLE)}", "", t(INTRO), "", f"## {t(SECTION_TITLES['quickstart'])}", ""]
    out += [f"{i}. {t(step)}" for i, step in enumerate(QUICKSTART, 1)] + [""]
    out += [f"## {t(SECTION_TITLES['auth'])}", ""]
    for paragraph in AUTH:
        text = t(paragraph)
        out += [f"    {text}" if text.startswith("Authorization:") else text, ""]
    out += [f"## {t(SECTION_TITLES['conventions'])}", ""] + [f"- {t(c)}" for c in CONVENTIONS] + [""]
    out += [f"## {t(SECTION_TITLES['connect'])}", "", t(CONNECT_INTRO), ""]
    for item in examples("http://127.0.0.1:47831", "ad_YOUR_KEY", lang):
        out += [f"### {item.title}", ""]
        if item.install:
            out += [f"`{item.install}`", ""]
        out += [f"```{item.fence}", item.code.rstrip("\n"), "```", ""]
    out += [f"## {t(SECTION_TITLES['methods'])}", ""]
    for group in GROUPS:
        out += [f"### {t(group.title)}", ""]
        for e in group.endpoints:
            out += [f"#### `{e.method} {e.path}` — {t(e.summary)}", ""]
            if t(e.desc):
                out += [t(e.desc), ""]
            if e.query:
                out += [f"**{t(LABELS['query'])}**", ""] + _fields_table(e.query, lang, required=False)
            if e.body:
                out += [f"**{t(LABELS['body'])}**", ""] + _fields_table(e.body, lang, required=True)
            if e.returns:
                out += [f"**{t(LABELS['returns'])}:** `{e.returns}`", ""]
            if e.request:
                out += [f"**{t(LABELS['request'])}**", "", "```json", e.request, "```", ""]
            if e.response:
                out += [f"**{t(LABELS['response'])}**", "", "```json", e.response, "```", ""]
    out += [f"## {t(SECTION_TITLES['types'])}", ""]
    for model in MODELS:
        out += [f"### {model.name}", "", t(model.intro), ""] + _fields_table(model.fields, lang, required=any(f.required for f in model.fields))
    out += [f"## {t(SECTION_TITLES['errors'])}", ""]
    out += _table([t(FIELD_HEADERS["status"]), t(FIELD_HEADERS["code"]), t(FIELD_HEADERS["meaning"])],
                  [[str(status), f"`{code}`", t(meaning)] for status, code, meaning in ERRORS])
    out += [f"## {t(SECTION_TITLES['tips'])}", ""]
    for tip in TIPS:
        out += [f"**{t(tip.title)}.** {t(tip.text)}", ""]
    return "\n".join(out).rstrip() + "\n"
