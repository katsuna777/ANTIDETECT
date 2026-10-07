# API instruction

Run profiles from your scripts: start one, connect Playwright, Puppeteer or Selenium to the address you get back, and drive a browser that has its own fingerprint. JSON over HTTP on 127.0.0.1, this computer only.

## Quick start

1. Turn the API on (the switch on the API page) and copy a key.
2. Create a profile: POST /v1/profiles with a name (and a proxy if you have one).
3. Start it: POST /v1/profiles/{id}/start. The answer holds connection.ws, the address of the running browser.
4. Connect Playwright, Puppeteer or Selenium to that address (see “Connecting tools” below) and work as usual.
5. Stop the profile when you are done: POST /v1/profiles/{id}/stop. Cookies and logins stay in it.

## Access keys

Every request except GET /v1/health must carry an access key:

    Authorization: Bearer <key>

The header X-API-Key: <key> works too. You can make as many keys as you like (one per script, machine or teammate), rename them, regenerate or delete them on the API page; a deleted key stops working at once.

Requests from web pages are refused (no CORS, a request with an Origin header gets 403), and the server listens on 127.0.0.1 only. Never put a key into a public repository.

## Conventions

- The base address is http://127.0.0.1:<port>/v1. Bodies are JSON (UTF-8); send Content-Length.
- Success is 200 (201 when something was created). A failure is 4xx/5xx with {"error": {"code": "...", "message": "..."}}: branch on code, show message to people.
- Times are ISO 8601 in UTC (2026-10-05T14:28:39Z). Lists answer {"total": n, "items": [...]}.
- Types: string, integer, number, boolean, object, X[] (a list of X), X | null (may be absent or null).

## Connecting tools

Each script below makes a profile (or reuses “shop-1”), starts it, connects to the address from the answer, opens a page and stops the profile. Replace the address and the key with yours (the app fills them in for you).

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


# 1. A profile: reuse "shop-1" if it exists, otherwise create it (add proxy="user:pass@host:port" for a proxy)
found = [p for p in api("GET", "/profiles?q=shop-1")["items"] if p["name"] == "shop-1"]
profile = found[0] if found else api("POST", "/profiles", name="shop-1", platform="windows")

# 2. Start it. The answer holds the address Playwright connects to
run = api("POST", f"/profiles/{profile['id']}/start")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(run["connection"]["ws"])
    context = browser.contexts[0]        # the profile's own context: its cookies and storage
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()                      # only disconnects; the profile keeps running

# 3. Stop the profile (its cookies and logins stay in it for next time)
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

// 1. A profile: reuse "shop-1" if it exists, otherwise create it (add proxy: "user:pass@host:port" for a proxy)
const found = (await api("GET", "/profiles?q=shop-1")).items.filter((p) => p.name === "shop-1");
const profile = found[0] ?? (await api("POST", "/profiles", { name: "shop-1", platform: "windows" }));

// 2. Start it. The answer holds the address Puppeteer connects to
const run = await api("POST", `/profiles/${profile.id}/start`);

// defaultViewport: null keeps the profile's own screen (Puppeteer's default would override it)
const browser = await puppeteer.connect({ browserWSEndpoint: run.connection.ws, defaultViewport: null });
const [page] = await browser.pages();
await page.goto("https://example.com");
console.log(await page.title());
await browser.disconnect();              // only disconnects; the profile keeps running

// 3. Stop the profile (its cookies and logins stay in it for next time)
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


# 1. A profile: reuse "shop-1" if it exists, otherwise create it (add proxy="user:pass@host:port" for a proxy)
found = [p for p in api("GET", "/profiles?q=shop-1")["items"] if p["name"] == "shop-1"]
profile = found[0] if found else api("POST", "/profiles", name="shop-1", platform="windows")

# 2. Start it. The answer holds the address Selenium attaches to
run = api("POST", f"/profiles/{profile['id']}/start")

options = webdriver.ChromeOptions()
options.debugger_address = run["connection"]["debugger_address"]     # attach to the running profile
driver = webdriver.Chrome(options=options)
driver.get("https://example.com")
print(driver.title)
driver.quit()                            # only detaches; the profile keeps running

# 3. Stop the profile (its cookies and logins stay in it for next time)
api("POST", f"/profiles/{profile['id']}/stop")
```

### curl

```bash
# The address and the key of your Antidetect (API page)
API=http://127.0.0.1:47831/v1
KEY=ad_YOUR_KEY

# 1. Create a profile (add "proxy": "user:pass@host:port" to give it a proxy)
curl -s -X POST $API/profiles -H "Authorization: Bearer $KEY" \
     -d '{"name": "shop-1", "platform": "windows"}'

# 2. Start it (use the "id" from the answer). The answer holds connection.ws, the address to connect to
curl -s -X POST $API/profiles/1/start -H "Authorization: Bearer $KEY"

# 3. Stop it
curl -s -X POST $API/profiles/1/stop -H "Authorization: Bearer $KEY"

# More: list, rename, delete
curl -s $API/profiles -H "Authorization: Bearer $KEY"
curl -s -X PATCH $API/profiles/1 -H "Authorization: Bearer $KEY" -d '{"name": "shop-2", "tags": ["eu"]}'
curl -s -X DELETE $API/profiles/1 -H "Authorization: Bearer $KEY"
```

## Methods

### Service

#### `GET /v1/health` — Is the API up?

The only method that needs no key. Handy for waiting until the app is ready.

**Returns:** `{ok, app}`

**Example response**

```json
{"ok": true, "app": "antidetect"}
```

#### `GET /v1/status` — App status

Version, how many profiles exist and run, and which browser is used.

**Returns:** `{ok, version, profiles, running, browser}`

**Example response**

```json
{
  "ok": true,
  "version": "0.2.0",
  "profiles": 12,
  "running": 2,
  "browser": {"path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "version": "154.0.8037.93"}
}
```

### Profiles

#### `GET /v1/profiles` — List profiles

In the order the profiles were created. Filters combine.

**Query parameters**

| Field | Type | Description |
| --- | --- | --- |
| `tag` | `string` | Only profiles with this tag. |
| `workspace` | `string` | Only profiles of this workspace. |
| `status` | `string` | "running" or "stopped". |
| `q` | `string` | Part of the name. |
| `limit` | `integer` | How many to return (default 500, at most 5000). |
| `offset` | `integer` | How many to skip (default 0). |

**Returns:** `{total, items: Profile[]}`

**Example response**

```json
{"total": 1, "items": [ ...Profile... ]}
```

#### `POST /v1/profiles` — Create a profile

Every profile gets its own fingerprint. With a proxy, the time zone and language match its country.

**JSON body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | yes | Unique name, at most 200 characters. |
| `platform` | `string` |  | "windows", "macos" or "linux". Default: this computer's system (the most natural choice). |
| `proxy` | `string \| object \| null` |  | A proxy to add and assign: "user:pass@host:port", "socks5://host:port", "host:port:user:pass", or {"type", "host", "port", "username", "password"}. It is checked first, so the country is known. |
| `proxy_id` | `integer \| null` |  | Instead of proxy: the id of a proxy that is already in your list. |
| `proxy_type` | `string` |  | "http", "https" or "socks5" for a proxy string that does not say. |
| `check_proxy` | `boolean` |  | false to skip the check of a new proxy (default true). |
| `tags` | `string[] \| string` |  | Tags; a comma-separated string works too. Unknown tags are created. |
| `workspace` | `string \| null` |  | Workspace name; it is created when it does not exist yet. |
| `notes` | `string` |  | Notes. |
| `start_url` | `string` |  | Page to open at start. |
| `geo_auto` | `boolean` |  | Match time zone and language to the IP (default true). |
| `webrtc` | `string` |  | "auto" (default), "block" or "allow"; see Profile. |
| `noise_canvas / noise_audio` | `boolean` |  | Fingerprint noise on or off (default true). |
| `theme` | `string` |  | "light" (default), "dark" or "auto"; see Profile. |
| `start` | `boolean` |  | true to start it right away; the answer then holds connection. |

**Returns:** `Profile (201)`

**Example request**

```json
{
  "name": "shop-1",
  "platform": "windows",
  "proxy": "user:pass@203.0.113.10:8080",
  "tags": ["eu"],
  "start": true
}
```

**Example response**

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

#### `GET /v1/profiles/{id}` — Get a profile

**Returns:** `Profile`

**Example response**

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

#### `PATCH /v1/profiles/{id}` — Change a profile

Only the fields you send change. A new proxy or fingerprint applies at the next start.

**JSON body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` |  | New name. |
| `notes` | `string` |  | Notes. |
| `tags` | `string[] \| string` |  | Tags (replaces the old ones). |
| `workspace` | `string \| null` |  | Move to this workspace (created when missing); null takes the profile out of its workspace. |
| `start_url` | `string` |  | Page to open at start ("" to clear). |
| `geo_auto` | `boolean` |  | Follow the IP for time zone and language. |
| `webrtc` | `string` |  | "auto", "block" or "allow"; applies at the next start. |
| `noise_canvas / noise_audio` | `boolean` |  | Fingerprint noise on or off. |
| `theme` | `string` |  | "light", "dark" or "auto"; applies at the next start. |
| `proxy / proxy_id` | `string \| object \| integer \| null` |  | As when creating; null removes the proxy. |
| `platform` | `string` |  | Give the profile a new fingerprint for this system. |
| `regenerate_fingerprint` | `boolean` |  | true: a fresh fingerprint for the same system. |

**Returns:** `Profile`

**Example request**

```json
{"name": "shop-2", "tags": ["eu", "vip"], "proxy": null}
```

**Example response**

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

#### `DELETE /v1/profiles/{id}` — Delete a profile

Stops it first, then moves it to the trash: it vanishes from every list, and you can restore it in the app (Trash) until it is deleted for good. With permanent=true its folder with cookies and history is removed at once.

**Query parameters**

| Field | Type | Description |
| --- | --- | --- |
| `permanent` | `boolean` | true: delete for good instead of moving to the trash. |

**Returns:** `{id, deleted, trashed}`

**Example response**

```json
{"id": 3, "deleted": true, "trashed": true}
```

#### `POST /v1/profiles/{id}/start` — Start a profile

Returns when the browser is ready (a few seconds; up to ~30 with a slow proxy). Idempotent: if it already runs you get 200 with already_running true and the same connection. Two scripts starting the same profile launch it once.

**Returns:** `Profile (+ already_running)`

**Example response**

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

#### `POST /v1/profiles/{id}/stop` — Stop a profile

Closes the browser properly; cookies and logins stay. Stopping a stopped profile is fine.

**Returns:** `Profile`

**Example response**

```json
{"id": 3, "status": "stopped", "connection": null, "...": "..."}
```

#### `GET /v1/profiles/{id}/connection` — Where to connect

The address of a running profile (409 not_running if it is stopped).

**Returns:** `Connection`

**Example response**

```json
{
  "ws": "ws://127.0.0.1:60746/devtools/browser/6d07c7e6-...",
  "http": "http://127.0.0.1:60746",
  "port": 60746,
  "debugger_address": "127.0.0.1:60746",
  "pid": 15562
}
```

#### `POST /v1/profiles/{id}/open` — Open a page

Opens an address in a new tab of a running profile. Only http:// and https:// addresses.

**JSON body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `url` | `string` | yes | The address. |

**Returns:** `{id, opened}`

**Example request**

```json
{"url": "https://example.com"}
```

**Example response**

```json
{"id": 3, "opened": "https://example.com"}
```

#### `GET /v1/profiles/{id}/cookies` — Read cookies

All cookies of a running profile.

**Returns:** `{count, cookies: Cookie[]}`

**Example response**

```json
{"count": 1, "cookies": [{"name": "sid", "value": "abc", "domain": "example.com", "path": "/", "expires": -1, "httpOnly": true, "secure": true, "sameSite": "Lax"}]}
```

#### `POST /v1/profiles/{id}/cookies` — Add cookies

Puts cookies into a running profile (existing ones with the same name, domain and path are replaced). Send a list, or {"cookies": [...]}.

**JSON body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `cookies` | `Cookie[]` | yes | The cookies (at most 20 000). |

**Returns:** `{imported}`

**Example request**

```json
{"cookies": [{"name": "sid", "value": "abc", "domain": ".example.com", "path": "/", "secure": true}]}
```

**Example response**

```json
{"imported": 1}
```

#### `DELETE /v1/profiles/{id}/cookies` — Clear cookies

Deletes every cookie of a running profile.

**Returns:** `{cleared}`

**Example response**

```json
{"cleared": true}
```

### Proxies

#### `GET /v1/proxies` — List proxies

**Query parameters**

| Field | Type | Description |
| --- | --- | --- |
| `status` | `string` | "unknown", "working", "dead" or "error". |
| `limit` | `integer` | How many to return (default 500, at most 5000). |
| `offset` | `integer` | How many to skip. |

**Returns:** `{total, items: Proxy[]}`

**Example response**

```json
{"total": 1, "items": [ ...Proxy... ]}
```

#### `POST /v1/proxies` — Add proxies

A proxy you add that is already in the list is reused, not duplicated.

**JSON body**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `proxies` | `(string \| object)[] \| string` | yes | The proxies: strings like "user:pass@host:port", objects {type, host, port, username, password}, or text with one proxy per line. |
| `type` | `string` |  | "http", "https" or "socks5" for strings that do not say. |
| `check` | `boolean` |  | true to check them now (default false). |

**Returns:** `{added, existing, invalid, items: Proxy[]}`

**Example request**

```json
{"proxies": ["user:pass@203.0.113.10:8080", "socks5://203.0.113.11:1080"], "check": true}
```

**Example response**

```json
{"added": 2, "existing": 0, "invalid": [], "items": [ ...Proxy... ]}
```

#### `POST /v1/proxies/{id}/check` — Check a proxy

Makes a real request through it; fills in country, ping and status.

**Returns:** `Proxy`

**Example response**

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

#### `DELETE /v1/proxies/{id}` — Delete a proxy

Profiles that used it become proxy-less.

**Returns:** `{id, deleted}`

**Example response**

```json
{"id": 5, "deleted": true}
```

## Types

### Profile

A browser profile: its own fingerprint, cookies and (optionally) proxy.

| Field | Type | Description |
| --- | --- | --- |
| `id` | `integer` | Profile number. |
| `name` | `string` | Unique name. |
| `status` | `string` | "running" or "stopped". |
| `tags` | `string[]` | Labels you put on the profile. |
| `workspace` | `string \| null` | The workspace the profile is in (a group of profiles you made in the app). |
| `notes` | `string` | Free-form notes. |
| `start_url` | `string \| null` | Page opened at start (instead of a new tab). |
| `geo_auto` | `boolean` | Time zone and language follow the exit IP address. |
| `webrtc` | `string` | What WebRTC may do: "auto" (hidden while a proxy is set), "block" (always hidden) or "allow" (left alone). |
| `noise_canvas` | `boolean` | The profile's picture (canvas) fingerprint is made unique. |
| `noise_audio` | `boolean` | The same for the sound fingerprint. |
| `theme` | `string` | The colour scheme sites are told the profile prefers: "light" (default for new profiles), "dark" or "auto" (follow the computer, as profiles made earlier do). |
| `platform` | `string \| null` | Operating system shown to sites: "windows", "macos" or "linux". |
| `user_agent` | `string \| null` | The User-Agent the browser sends. |
| `language` | `string \| null` | Main language, e.g. "de". |
| `locale` | `string \| null` | Locale, e.g. "de-DE". |
| `timezone` | `string \| null` | IANA time zone, e.g. "Europe/Berlin". |
| `screen` | `string \| null` | Screen size "WIDTHxHEIGHT", e.g. "1920x1080". |
| `cores` | `integer \| null` | Processor cores shown to sites. |
| `memory_gb` | `number \| null` | Memory (GB) shown to sites. |
| `proxy` | `Proxy \| null` | The assigned proxy, or null for a direct connection. |
| `connection` | `Connection \| null` | Where to connect to the running browser; null while it is stopped. |
| `created_at` | `string` | When it was created. |
| `last_started_at` | `string \| null` | When it was started last. |
| `last_stopped_at` | `string \| null` | When it was stopped last. |
| `already_running` | `boolean` | Only in the answer to start: true if the profile was running already. |

### Connection

How to attach an automation tool to a running profile.

| Field | Type | Description |
| --- | --- | --- |
| `ws` | `string` | The address for Playwright (connect_over_cdp) and Puppeteer (browserWSEndpoint). |
| `debugger_address` | `string` | host:port for Selenium (debugger_address). |
| `http` | `string` | The same browser over HTTP (for tools that want a URL). |
| `port` | `integer` | The debugging port. |
| `pid` | `integer \| null` | The browser process id. |

### Proxy

A proxy from your list. The password is never returned.

| Field | Type | Description |
| --- | --- | --- |
| `id` | `integer` | Proxy number. |
| `type` | `string` | "http", "https" or "socks5". |
| `host` | `string` | Address. |
| `port` | `integer` | Port. |
| `username` | `string \| null` | Login, if it has one. |
| `has_password` | `boolean` | Whether a password is stored. |
| `country` | `string \| null` | Exit country name (known after a check). |
| `country_code` | `string \| null` | Two-letter country code, e.g. "DE". |
| `status` | `string` | "unknown" (not checked), "working", "dead" or "error". |
| `latency_ms` | `integer \| null` | Response time of the last check. |
| `ip` | `string \| null` | The IP address sites see through it. |
| `source` | `string \| null` | "manual" for proxies you added. |
| `checked_at` | `string \| null` | When it was checked last. |

### Cookie

A cookie in the format of Chrome DevTools. Exports of the common cookie-editor extensions are accepted too.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | `string` | yes | Name. |
| `value` | `string` | yes | Value. |
| `domain` | `string` | yes | Domain, e.g. ".example.com". Needed unless url is given. |
| `url` | `string` |  | Instead of domain: the address the cookie belongs to. |
| `path` | `string` |  | Path, default "/". |
| `expires` | `number` |  | Expiry in Unix seconds; leave out (or -1) for a session cookie. expirationDate is accepted as well. |
| `httpOnly` | `boolean` |  | Hidden from page scripts. |
| `secure` | `boolean` |  | Sent over HTTPS only. |
| `sameSite` | `string` |  | "Strict", "Lax" or "None". |

### Error

What every failed request answers.

| Field | Type | Description |
| --- | --- | --- |
| `error.code` | `string` | A stable name of the problem (see the table of errors). |
| `error.message` | `string` | A sentence for people. |

## Errors

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `bad_request` | A field is missing or has the wrong type; message says which. |
| 400 | `bad_json` | The body is not valid JSON. |
| 401 | `unauthorized` | No key, or a wrong one. |
| 403 | `forbidden_origin` | The request came from a web page (it has an Origin header). |
| 403 | `forbidden_host` | The request was not addressed to 127.0.0.1. |
| 404 | `not_found` | No such method. |
| 404 | `profile_not_found` | No profile with this id. |
| 404 | `proxy_not_found` | No proxy with this id. |
| 405 | `method_not_allowed` | The method exists, but not with this HTTP verb (see the Allow header). |
| 409 | `profile_exists` | A profile with this name already exists. |
| 409 | `not_running` | The profile is not running; start it first. |
| 409 | `cookie_error` | The cookies could not be handled. |
| 413 | `too_large` | The body is larger than 8 MB. |
| 422 | `proxy_unreadable` | The proxy string could not be understood. |
| 422 | `proxy_unusable` | The proxy exists but cannot be used (dead). |
| 500 | `browser_error` | The browser could not be started; message has the reason (a proxy that does not answer, a failed pre-launch check). |
| 500 | `stealth_failed` | The browser started but the fingerprint could not be applied; it was closed. |
| 500 | `internal_error` | A bug; the details are on the Log page. |
| 503 | `browser_not_found` | No Chrome is installed (or chosen in Settings). |
| 503 | `connection_unavailable` | The browser has not published its address yet; retry in a second. |

## Good to know

**Do not resize the window through automation.** The profile has its own screen. Tools that set a viewport replace it, and the site then sees a size that does not fit the profile. Playwright: work in browser.contexts[0], or make a new context with no_viewport=True (a plain new_context() forces 1280×720). Puppeteer: connect with defaultViewport: null (its default forces 800×600 and even lets the real screen of your computer show). Selenium: nothing to set.

**Disconnecting does not stop the profile.** browser.close() (Playwright), browser.disconnect() (Puppeteer) and driver.quit() (Selenium) only let go of the browser, which keeps running. Stop it with POST /v1/profiles/{id}/stop. Closing the last tab does close the browser.

**The fingerprint is applied while the app is open.** The layer that applies the fingerprint lives in the app. If you quit it, a tab opened later in a running profile is not covered. Keep the app open while scripts work, or run it without a window: antidetect api serve.

**Starting takes time.** A start waits for the browser and, with a proxy, for a check of it: allow 60 seconds in your HTTP client. You can start many different profiles at once; the same profile is started once.

**Be gentle with accounts.** Automation tools talk to the browser through the DevTools protocol, and some sites can notice that. For valuable accounts log in by hand in the app first, then let the script do the light work, at human speed.

**Cookies.** Reading and writing cookies works on a running profile: start it, then call the cookie methods. To move a login between profiles: GET the cookies of one, POST them into another.

**From the command line.** antidetect api serve runs the API without the window; antidetect api keys manages keys; antidetect api examples prints ready scripts; antidetect api docs prints this instruction.
