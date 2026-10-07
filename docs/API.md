# Инструкция по API

Управляйте профилями из скриптов: запустите профиль, подключите Playwright, Puppeteer или Selenium к полученному адресу и работайте в браузере со своим отпечатком. JSON поверх HTTP на 127.0.0.1, только на этом компьютере.

## Быстрый старт

1. Включите API (переключатель на странице API) и скопируйте ключ.
2. Создайте профиль: POST /v1/profiles с именем (и прокси, если он есть).
3. Запустите его: POST /v1/profiles/{id}/start. В ответе будет connection.ws — адрес запущенного браузера.
4. Подключите Playwright, Puppeteer или Selenium к этому адресу (см. «Подключение инструментов» ниже) и работайте как обычно.
5. Когда закончите, остановите профиль: POST /v1/profiles/{id}/stop. Cookies и входы в нём сохранятся.

## Ключи доступа

Каждый запрос, кроме GET /v1/health, должен содержать ключ доступа:

    Authorization: Bearer <ключ>

Подойдёт и заголовок X-API-Key: <ключ>. Ключей можно сделать сколько угодно (по одному на скрипт, компьютер или коллегу), переименовывать, перевыпускать и удалять на странице API; удалённый ключ перестаёт работать сразу.

Запросы из веб-страниц отклоняются (CORS нет, запрос с заголовком Origin получает 403), а сервер слушает только 127.0.0.1. Не кладите ключ в публичный репозиторий.

## Общие правила

- Базовый адрес — http://127.0.0.1:<порт>/v1. Тела запросов — JSON (UTF-8), указывайте Content-Length.
- Успех — 200 (201, если что-то создано). Ошибка — 4xx/5xx с телом {"error": {"code": "...", "message": "..."}}: ветвитесь по code, а message показывайте людям.
- Время — ISO 8601 в UTC (2026-10-05T14:28:39Z). Списки отвечают {"total": n, "items": [...]}.
- Типы: string (строка), integer (целое), number (число), boolean (да/нет), object, X[] (список X), X | null (может быть пустым).

## Подключение инструментов

Каждый скрипт ниже создаёт профиль (или берёт существующий «shop-1»), запускает его, подключается по адресу из ответа, открывает страницу и останавливает профиль. Подставьте свой адрес и ключ (приложение подставляет их за вас).

### Python · Playwright

`pip install requests playwright`

```python
import requests
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:47831/v1"
HEADERS = {"Authorization": "Bearer ad_YOUR_KEY"}


def api(method, path, **body):
    reply = requests.request(method, API + path, headers=HEADERS, json=body or None, timeout=120)
    data = reply.json()
    if reply.status_code >= 400:
        raise RuntimeError(data["error"]["message"])
    return data


# 1. Профиль: берём "shop-1", если он есть, иначе создаём (чтобы задать прокси, добавьте proxy="user:pass@host:port")
found = [p for p in api("GET", "/profiles?q=shop-1")["items"] if p["name"] == "shop-1"]
profile = found[0] if found else api("POST", "/profiles", name="shop-1", platform="windows")

# 2. Запускаем. В ответе — адрес, к которому подключается Playwright
run = api("POST", f"/profiles/{profile['id']}/start")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(run["connection"]["ws"])
    context = browser.contexts[0]        # собственный контекст профиля: его cookies и хранилище
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()                      # только отключается; профиль продолжает работать

# 3. Останавливаем профиль (его cookies и входы сохранятся до следующего раза)
api("POST", f"/profiles/{profile['id']}/stop")
```

### Node.js · Puppeteer

`npm install puppeteer-core`

```javascript
// Node 18+.   npm install puppeteer-core
import puppeteer from "puppeteer-core";

const API = "http://127.0.0.1:47831/v1";
const HEADERS = { Authorization: "Bearer ad_YOUR_KEY", "Content-Type": "application/json" };

async function api(method, path, body) {
  const reply = await fetch(API + path, { method, headers: HEADERS, body: body && JSON.stringify(body) });
  const data = await reply.json();
  if (!reply.ok) throw new Error(data.error.message);
  return data;
}

// 1. Профиль: берём "shop-1", если он есть, иначе создаём (чтобы задать прокси, добавьте proxy: "user:pass@host:port")
const found = (await api("GET", "/profiles?q=shop-1")).items.filter((p) => p.name === "shop-1");
const profile = found[0] ?? (await api("POST", "/profiles", { name: "shop-1", platform: "windows" }));

// 2. Запускаем. В ответе — адрес, к которому подключается Puppeteer
const run = await api("POST", `/profiles/${profile.id}/start`);

// defaultViewport: null сохраняет собственный экран профиля (по умолчанию Puppeteer его подменяет)
const browser = await puppeteer.connect({ browserWSEndpoint: run.connection.ws, defaultViewport: null });
const [page] = await browser.pages();
await page.goto("https://example.com");
console.log(await page.title());
await browser.disconnect();              // только отключается; профиль продолжает работать

// 3. Останавливаем профиль (его cookies и входы сохранятся до следующего раза)
await api("POST", `/profiles/${profile.id}/stop`);
```

### Python · Selenium

`pip install requests selenium`

```python
import requests
from selenium import webdriver

API = "http://127.0.0.1:47831/v1"
HEADERS = {"Authorization": "Bearer ad_YOUR_KEY"}


def api(method, path, **body):
    reply = requests.request(method, API + path, headers=HEADERS, json=body or None, timeout=120)
    data = reply.json()
    if reply.status_code >= 400:
        raise RuntimeError(data["error"]["message"])
    return data


# 1. Профиль: берём "shop-1", если он есть, иначе создаём (чтобы задать прокси, добавьте proxy="user:pass@host:port")
found = [p for p in api("GET", "/profiles?q=shop-1")["items"] if p["name"] == "shop-1"]
profile = found[0] if found else api("POST", "/profiles", name="shop-1", platform="windows")

# 2. Запускаем. В ответе — адрес, к которому подключается Selenium
run = api("POST", f"/profiles/{profile['id']}/start")

options = webdriver.ChromeOptions()
options.debugger_address = run["connection"]["debugger_address"]     # подключаемся к запущенному профилю
driver = webdriver.Chrome(options=options)
driver.get("https://example.com")
print(driver.title)
driver.quit()                            # только отсоединяется; профиль продолжает работать

# 3. Останавливаем профиль (его cookies и входы сохранятся до следующего раза)
api("POST", f"/profiles/{profile['id']}/stop")
```

### curl

```bash
# Адрес и ключ вашего Antidetect (страница API)
API=http://127.0.0.1:47831/v1
KEY=ad_YOUR_KEY

# 1. Создаём профиль (чтобы задать прокси, добавьте "proxy": "user:pass@host:port")
curl -s -X POST $API/profiles -H "Authorization: Bearer $KEY" \
     -d '{"name": "shop-1", "platform": "windows"}'

# 2. Запускаем (подставьте "id" из ответа). В ответе — connection.ws, адрес для подключения
curl -s -X POST $API/profiles/1/start -H "Authorization: Bearer $KEY"

# 3. Останавливаем
curl -s -X POST $API/profiles/1/stop -H "Authorization: Bearer $KEY"

# Ещё: список, переименование, удаление
curl -s $API/profiles -H "Authorization: Bearer $KEY"
curl -s -X PATCH $API/profiles/1 -H "Authorization: Bearer $KEY" -d '{"name": "shop-2", "tags": ["eu"]}'
curl -s -X DELETE $API/profiles/1 -H "Authorization: Bearer $KEY"
```

## Методы

### Служебные

#### `GET /v1/health` — API работает?

Единственный метод без ключа. Удобен, чтобы дождаться готовности приложения.

**Возвращает:** `{ok, app}`

**Пример ответа**

```json
{"ok": true, "app": "antidetect"}
```

#### `GET /v1/status` — Состояние приложения

Версия, сколько профилей существует и запущено, какой браузер используется.

**Возвращает:** `{ok, version, profiles, running, browser}`

**Пример ответа**

```json
{
  "ok": true,
  "version": "0.2.0",
  "profiles": 12,
  "running": 2,
  "browser": {"path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "version": "154.0.8037.93"}
}
```

### Профили

#### `GET /v1/profiles` — Список профилей

В порядке создания профилей. Фильтры сочетаются.

**Параметры запроса (query)**

| Поле | Тип | Описание |
| --- | --- | --- |
| `tag` | `string` | Только профили с этим тегом. |
| `workspace` | `string` | Только профили этого рабочего пространства. |
| `status` | `string` | "running" или "stopped". |
| `q` | `string` | Часть имени. |
| `limit` | `integer` | Сколько вернуть (по умолчанию 500, максимум 5000). |
| `offset` | `integer` | Сколько пропустить (по умолчанию 0). |

**Возвращает:** `{total, items: Profile[]}`

**Пример ответа**

```json
{"total": 1, "items": [ ...Profile... ]}
```

#### `POST /v1/profiles` — Создать профиль

Каждый профиль получает свой отпечаток. С прокси часовой пояс и язык подбираются под его страну.

**Тело запроса (JSON)**

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `name` | `string` | да | Уникальное имя, не длиннее 200 символов. |
| `platform` | `string` |  | "windows", "macos" или "linux". По умолчанию — система этого компьютера (самый естественный выбор). |
| `proxy` | `string \| object \| null` |  | Прокси, который нужно добавить и назначить: "user:pass@host:port", "socks5://host:port", "host:port:user:pass" или {"type", "host", "port", "username", "password"}. Он сначала проверяется, чтобы узнать страну. |
| `proxy_id` | `integer \| null` |  | Вместо proxy: номер прокси, который уже есть в списке. |
| `proxy_type` | `string` |  | "http", "https" или "socks5" для строки прокси без указания типа. |
| `check_proxy` | `boolean` |  | false — не проверять новый прокси (по умолчанию true). |
| `tags` | `string[] \| string` |  | Теги; подойдёт и строка через запятую. Неизвестные теги создаются. |
| `workspace` | `string \| null` |  | Название рабочего пространства; если его нет — оно создаётся. |
| `notes` | `string` |  | Заметки. |
| `start_url` | `string` |  | Страница, открываемая при запуске. |
| `geo_auto` | `boolean` |  | Подстраивать часовой пояс и язык под IP (по умолчанию true). |
| `webrtc` | `string` |  | "auto" (по умолчанию), "block" или "allow"; см. Profile. |
| `noise_canvas / noise_audio` | `boolean` |  | Шум отпечатка включён или выключен (по умолчанию true). |
| `theme` | `string` |  | "light" (по умолчанию), "dark" или "auto"; см. Profile. |
| `start` | `boolean` |  | true — сразу запустить; тогда в ответе будет connection. |

**Возвращает:** `Profile (201)`

**Пример запроса**

```json
{
  "name": "shop-1",
  "platform": "windows",
  "proxy": "user:pass@203.0.113.10:8080",
  "tags": ["eu"],
  "start": true
}
```

**Пример ответа**

```json
{
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
}
```

#### `GET /v1/profiles/{id}` — Получить профиль

**Возвращает:** `Profile`

**Пример ответа**

```json
{
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
}
```

#### `PATCH /v1/profiles/{id}` — Изменить профиль

Меняются только присланные поля. Новый прокси или отпечаток применяются при следующем запуске.

**Тело запроса (JSON)**

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `name` | `string` |  | Новое имя. |
| `notes` | `string` |  | Заметки. |
| `tags` | `string[] \| string` |  | Теги (заменяют прежние). |
| `workspace` | `string \| null` |  | Перенести в это рабочее пространство (создаётся, если нет); null — вынуть профиль из пространства. |
| `start_url` | `string` |  | Страница при запуске ("" — убрать). |
| `geo_auto` | `boolean` |  | Подстраивать часовой пояс и язык под IP. |
| `webrtc` | `string` |  | "auto", "block" или "allow"; применяется при следующем запуске. |
| `noise_canvas / noise_audio` | `boolean` |  | Шум отпечатка включён или выключен. |
| `theme` | `string` |  | "light", "dark" или "auto"; применяется при следующем запуске. |
| `proxy / proxy_id` | `string \| object \| integer \| null` |  | Как при создании; null убирает прокси. |
| `platform` | `string` |  | Выдать профилю новый отпечаток для этой системы. |
| `regenerate_fingerprint` | `boolean` |  | true: новый отпечаток для той же системы. |

**Возвращает:** `Profile`

**Пример запроса**

```json
{"name": "shop-2", "tags": ["eu", "vip"], "proxy": null}
```

**Пример ответа**

```json
{
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
}
```

#### `DELETE /v1/profiles/{id}` — Удалить профиль

Сначала останавливает, затем переносит в корзину: профиль пропадает из всех списков, а в приложении (Корзина) его можно вернуть, пока он не удалён окончательно. С permanent=true папка с cookies и историей удаляется сразу.

**Параметры запроса (query)**

| Поле | Тип | Описание |
| --- | --- | --- |
| `permanent` | `boolean` | true: удалить навсегда, а не в корзину. |

**Возвращает:** `{id, deleted, trashed}`

**Пример ответа**

```json
{"id": 3, "deleted": true, "trashed": true}
```

#### `POST /v1/profiles/{id}/start` — Запустить профиль

Отвечает, когда браузер готов (несколько секунд; до ~30 с с медленным прокси). Идемпотентен: если профиль уже запущен — 200 с already_running true и тем же connection. Два скрипта, запускающие один профиль, запустят его один раз.

**Возвращает:** `Profile (+ already_running)`

**Пример ответа**

```json
{
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
}
```

#### `POST /v1/profiles/{id}/stop` — Остановить профиль

Корректно закрывает браузер; cookies и входы сохраняются. Остановка уже остановленного профиля — не ошибка.

**Возвращает:** `Profile`

**Пример ответа**

```json
{"id": 3, "status": "stopped", "connection": null, "...": "..."}
```

#### `GET /v1/profiles/{id}/connection` — Куда подключаться

Адрес запущенного профиля (409 not_running, если он остановлен).

**Возвращает:** `Connection`

**Пример ответа**

```json
{
  "ws": "ws://127.0.0.1:60746/devtools/browser/6d07c7e6-...",
  "http": "http://127.0.0.1:60746",
  "port": 60746,
  "debugger_address": "127.0.0.1:60746",
  "pid": 15562
}
```

#### `POST /v1/profiles/{id}/open` — Открыть страницу

Открывает адрес в новой вкладке запущенного профиля. Только адреса http:// и https://.

**Тело запроса (JSON)**

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `url` | `string` | да | Адрес. |

**Возвращает:** `{id, opened}`

**Пример запроса**

```json
{"url": "https://example.com"}
```

**Пример ответа**

```json
{"id": 3, "opened": "https://example.com"}
```

#### `GET /v1/profiles/{id}/cookies` — Прочитать cookies

Все cookies запущенного профиля.

**Возвращает:** `{count, cookies: Cookie[]}`

**Пример ответа**

```json
{"count": 1, "cookies": [{"name": "sid", "value": "abc", "domain": "example.com", "path": "/", "expires": -1, "httpOnly": true, "secure": true, "sameSite": "Lax"}]}
```

#### `POST /v1/profiles/{id}/cookies` — Добавить cookies

Кладёт cookies в запущенный профиль (существующие с тем же именем, доменом и путём заменяются). Присылайте список или {"cookies": [...]}.

**Тело запроса (JSON)**

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `cookies` | `Cookie[]` | да | Cookies (не больше 20 000). |

**Возвращает:** `{imported}`

**Пример запроса**

```json
{"cookies": [{"name": "sid", "value": "abc", "domain": ".example.com", "path": "/", "secure": true}]}
```

**Пример ответа**

```json
{"imported": 1}
```

#### `DELETE /v1/profiles/{id}/cookies` — Очистить cookies

Удаляет все cookies запущенного профиля.

**Возвращает:** `{cleared}`

**Пример ответа**

```json
{"cleared": true}
```

### Прокси

#### `GET /v1/proxies` — Список прокси

**Параметры запроса (query)**

| Поле | Тип | Описание |
| --- | --- | --- |
| `status` | `string` | "unknown", "working", "dead" или "error". |
| `limit` | `integer` | Сколько вернуть (по умолчанию 500, максимум 5000). |
| `offset` | `integer` | Сколько пропустить. |

**Возвращает:** `{total, items: Proxy[]}`

**Пример ответа**

```json
{"total": 1, "items": [ ...Proxy... ]}
```

#### `POST /v1/proxies` — Добавить прокси

Прокси, который уже есть в списке, не дублируется, а используется повторно.

**Тело запроса (JSON)**

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `proxies` | `(string \| object)[] \| string` | да | Прокси: строки вида "user:pass@host:port", объекты {type, host, port, username, password} или текст по одному прокси в строке. |
| `type` | `string` |  | "http", "https" или "socks5" для строк без указания типа. |
| `check` | `boolean` |  | true — проверить сразу (по умолчанию false). |

**Возвращает:** `{added, existing, invalid, items: Proxy[]}`

**Пример запроса**

```json
{"proxies": ["user:pass@203.0.113.10:8080", "socks5://203.0.113.11:1080"], "check": true}
```

**Пример ответа**

```json
{"added": 2, "existing": 0, "invalid": [], "items": [ ...Proxy... ]}
```

#### `POST /v1/proxies/{id}/check` — Проверить прокси

Делает настоящий запрос через него; заполняет страну, пинг и статус.

**Возвращает:** `Proxy`

**Пример ответа**

```json
{
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
}
```

#### `DELETE /v1/proxies/{id}` — Удалить прокси

Профили, которые его использовали, остаются без прокси.

**Возвращает:** `{id, deleted}`

**Пример ответа**

```json
{"id": 5, "deleted": true}
```

## Типы

### Profile

Профиль браузера: свой отпечаток, свои cookies и (по желанию) прокси.

| Поле | Тип | Описание |
| --- | --- | --- |
| `id` | `integer` | Номер профиля. |
| `name` | `string` | Уникальное имя. |
| `status` | `string` | "running" (запущен) или "stopped" (остановлен). |
| `tags` | `string[]` | Метки профиля. |
| `workspace` | `string \| null` | Рабочее пространство профиля (группа профилей, созданная в приложении). |
| `notes` | `string` | Заметки. |
| `start_url` | `string \| null` | Страница, открываемая при запуске (вместо новой вкладки). |
| `geo_auto` | `boolean` | Часовой пояс и язык подстраиваются под IP-адрес выхода. |
| `webrtc` | `string` | Что может WebRTC: "auto" (скрыт, пока задан прокси), "block" (скрыт всегда) или "allow" (не трогается). |
| `noise_canvas` | `boolean` | Отпечаток картинки (canvas) делается уникальным у профиля. |
| `noise_audio` | `boolean` | То же для отпечатка звука. |
| `theme` | `string` | Цветовая схема, которую профиль сообщает сайтам: "light" (по умолчанию у новых профилей), "dark" или "auto" (как в системе, так работают профили, созданные раньше). |
| `platform` | `string \| null` | ОС, которую видят сайты: "windows", "macos" или "linux". |
| `user_agent` | `string \| null` | User-Agent, который отправляет браузер. |
| `language` | `string \| null` | Основной язык, например "de". |
| `locale` | `string \| null` | Региональные настройки, например "de-DE". |
| `timezone` | `string \| null` | Часовой пояс IANA, например "Europe/Berlin". |
| `screen` | `string \| null` | Размер экрана «ШИРИНАxВЫСОТА», например "1920x1080". |
| `cores` | `integer \| null` | Число ядер процессора, которое видят сайты. |
| `memory_gb` | `number \| null` | Память (ГБ), которую видят сайты. |
| `proxy` | `Proxy \| null` | Назначенный прокси или null — прямое соединение. |
| `connection` | `Connection \| null` | Куда подключаться к запущенному браузеру; null, пока он остановлен. |
| `created_at` | `string` | Когда создан. |
| `last_started_at` | `string \| null` | Когда запускался в последний раз. |
| `last_stopped_at` | `string \| null` | Когда останавливался в последний раз. |
| `already_running` | `boolean` | Только в ответе на start: true, если профиль уже был запущен. |

### Connection

Как подключить инструмент автоматизации к запущенному профилю.

| Поле | Тип | Описание |
| --- | --- | --- |
| `ws` | `string` | Адрес для Playwright (connect_over_cdp) и Puppeteer (browserWSEndpoint). |
| `debugger_address` | `string` | host:port для Selenium (debugger_address). |
| `http` | `string` | Тот же браузер по HTTP (для инструментов, которым нужен URL). |
| `port` | `integer` | Порт отладки. |
| `pid` | `integer \| null` | Номер процесса браузера. |

### Proxy

Прокси из вашего списка. Пароль никогда не возвращается.

| Поле | Тип | Описание |
| --- | --- | --- |
| `id` | `integer` | Номер прокси. |
| `type` | `string` | "http", "https" или "socks5". |
| `host` | `string` | Адрес. |
| `port` | `integer` | Порт. |
| `username` | `string \| null` | Логин, если есть. |
| `has_password` | `boolean` | Сохранён ли пароль. |
| `country` | `string \| null` | Страна выхода (известна после проверки). |
| `country_code` | `string \| null` | Двухбуквенный код страны, например "DE". |
| `status` | `string` | "unknown" (не проверен), "working" (работает), "dead" (не работает) или "error" (ошибка). |
| `latency_ms` | `integer \| null` | Время ответа при последней проверке. |
| `ip` | `string \| null` | IP-адрес, который видят сайты через него. |
| `source` | `string \| null` | "manual" для прокси, которые добавили вы. |
| `checked_at` | `string \| null` | Когда проверялся в последний раз. |

### Cookie

Cookie в формате Chrome DevTools. Экспорт популярных расширений-редакторов cookie тоже принимается.

| Поле | Тип | Обязательно | Описание |
| --- | --- | --- | --- |
| `name` | `string` | да | Имя. |
| `value` | `string` | да | Значение. |
| `domain` | `string` | да | Домен, например ".example.com". Нужен, если не указан url. |
| `url` | `string` |  | Вместо domain: адрес, к которому относится cookie. |
| `path` | `string` |  | Путь, по умолчанию "/". |
| `expires` | `number` |  | Срок действия в секундах Unix; не указывайте (или -1) для сессионной cookie. Подходит и expirationDate. |
| `httpOnly` | `boolean` |  | Скрыта от скриптов страницы. |
| `secure` | `boolean` |  | Отправляется только по HTTPS. |
| `sameSite` | `string` |  | "Strict", "Lax" или "None". |

### Error

Ответ на любой неудачный запрос.

| Поле | Тип | Описание |
| --- | --- | --- |
| `error.code` | `string` | Постоянное имя проблемы (см. таблицу ошибок). |
| `error.message` | `string` | Фраза для людей. |

## Ошибки

| HTTP | Код | Значение |
| --- | --- | --- |
| 400 | `bad_request` | Поле не указано или имеет неверный тип; message скажет, какое. |
| 400 | `bad_json` | Тело запроса — не корректный JSON. |
| 401 | `unauthorized` | Ключа нет или он неверный. |
| 403 | `forbidden_origin` | Запрос пришёл из веб-страницы (есть заголовок Origin). |
| 403 | `forbidden_host` | Запрос адресован не на 127.0.0.1. |
| 404 | `not_found` | Такого метода нет. |
| 404 | `profile_not_found` | Нет профиля с таким номером. |
| 404 | `proxy_not_found` | Нет прокси с таким номером. |
| 405 | `method_not_allowed` | Метод есть, но не с этим HTTP-глаголом (см. заголовок Allow). |
| 409 | `profile_exists` | Профиль с таким именем уже есть. |
| 409 | `not_running` | Профиль не запущен; сначала запустите его. |
| 409 | `cookie_error` | Не удалось обработать cookies. |
| 413 | `too_large` | Тело запроса больше 8 МБ. |
| 422 | `proxy_unreadable` | Строку прокси не удалось разобрать. |
| 422 | `proxy_unusable` | Прокси есть, но им нельзя пользоваться (не работает). |
| 500 | `browser_error` | Браузер не удалось запустить; в message причина (прокси не отвечает, не прошла проверка перед запуском). |
| 500 | `stealth_failed` | Браузер запустился, но отпечаток применить не удалось; браузер закрыт. |
| 500 | `internal_error` | Ошибка в программе; подробности на странице «Журнал». |
| 503 | `browser_not_found` | Chrome не установлен (или не выбран в настройках). |
| 503 | `connection_unavailable` | Браузер ещё не сообщил свой адрес; повторите через секунду. |

## Полезно знать

**Не меняйте размер окна через автоматизацию.** У профиля свой экран. Инструменты, задающие размер окна, подменяют его, и сайт видит размер, который не подходит к профилю. Playwright: работайте в browser.contexts[0] или создавайте контекст с no_viewport=True (обычный new_context() принудительно ставит 1280×720). Puppeteer: подключайтесь с defaultViewport: null (по умолчанию он ставит 800×600 и даже показывает реальный экран вашего компьютера). Selenium: настраивать ничего не нужно.

**Отключение не останавливает профиль.** browser.close() (Playwright), browser.disconnect() (Puppeteer) и driver.quit() (Selenium) лишь отпускают браузер, он продолжает работать. Остановить его можно запросом POST /v1/profiles/{id}/stop. Закрытие последней вкладки закрывает браузер.

**Отпечаток применяется, пока приложение открыто.** Слой, который применяет отпечаток, живёт в приложении. Если закрыть его, вкладка, открытая позже в запущенном профиле, защищена не будет. Держите приложение открытым, пока работают скрипты, или запустите его без окна: antidetect api serve.

**Запуск занимает время.** Запуск ждёт браузер и, если есть прокси, его проверку: задайте HTTP-клиенту таймаут 60 секунд. Разные профили можно запускать одновременно; один и тот же профиль запустится один раз.

**Бережно относитесь к аккаунтам.** Инструменты автоматизации управляют браузером через протокол DevTools, и некоторые сайты это замечают. Для ценных аккаунтов сначала войдите вручную в приложении, а скрипту оставьте лёгкую работу в человеческом темпе.

**Cookies.** Чтение и запись cookies работают у запущенного профиля: запустите его, затем вызывайте методы cookies. Чтобы перенести вход между профилями: получите cookies одного (GET) и отправьте их другому (POST).

**Из командной строки.** antidetect api serve запускает API без окна; antidetect api keys управляет ключами; antidetect api examples печатает готовые скрипты; antidetect api docs печатает эту инструкцию.
