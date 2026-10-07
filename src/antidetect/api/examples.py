"""Copy-paste scripts for the API, filled in with this machine's address and key.

Shown in the app (API page → Instruction) and by ``antidetect api examples``; the same scripts are
run against a real browser when the live tests are on, so they work. Only the comments are
translated; the code is the same in every language.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    key: str
    title: str
    filename: str
    install: str
    code: str
    fence: str = ""          # the language tag for a Markdown code block


#: Comments of the scripts: (English, Russian)
_COMMENTS = {
    "profile": ('A profile: reuse "shop-1" if it exists, otherwise create it (add proxy="user:pass@host:port" for a proxy)',
                'Профиль: берём "shop-1", если он есть, иначе создаём (чтобы задать прокси, добавьте proxy="user:pass@host:port")'),
    "profile_js": ('A profile: reuse "shop-1" if it exists, otherwise create it (add proxy: "user:pass@host:port" for a proxy)',
                   'Профиль: берём "shop-1", если он есть, иначе создаём (чтобы задать прокси, добавьте proxy: "user:pass@host:port")'),
    "start_pw": ("Start it. The answer holds the address Playwright connects to",
                 "Запускаем. В ответе — адрес, к которому подключается Playwright"),
    "start_pup": ("Start it. The answer holds the address Puppeteer connects to",
                  "Запускаем. В ответе — адрес, к которому подключается Puppeteer"),
    "start_sel": ("Start it. The answer holds the address Selenium attaches to",
                  "Запускаем. В ответе — адрес, к которому подключается Selenium"),
    "context": ("the profile's own context: its cookies and storage", "собственный контекст профиля: его cookies и хранилище"),
    "disconnect": ("only disconnects; the profile keeps running", "только отключается; профиль продолжает работать"),
    "detach": ("only detaches; the profile keeps running", "только отсоединяется; профиль продолжает работать"),
    "attach": ("attach to the running profile", "подключаемся к запущенному профилю"),
    "viewport": ("defaultViewport: null keeps the profile's own screen (Puppeteer's default would override it)",
                 "defaultViewport: null сохраняет собственный экран профиля (по умолчанию Puppeteer его подменяет)"),
    "stop": ("Stop the profile (its cookies and logins stay in it for next time)",
             "Останавливаем профиль (его cookies и входы сохранятся до следующего раза)"),
    "address": ("The address and the key of your Antidetect (API page)", "Адрес и ключ вашего Antidetect (страница API)"),
    "curl_create": ('Create a profile (add "proxy": "user:pass@host:port" to give it a proxy)',
                    'Создаём профиль (чтобы задать прокси, добавьте "proxy": "user:pass@host:port")'),
    "curl_start": ('Start it (use the "id" from the answer). The answer holds connection.ws, the address to connect to',
                   'Запускаем (подставьте "id" из ответа). В ответе — connection.ws, адрес для подключения'),
    "curl_stop": ("Stop it", "Останавливаем"),
    "curl_more": ("More: list, rename, delete", "Ещё: список, переименование, удаление"),
}

_CURL = '''\
# %(address)s
API=%(url)s/v1
KEY=%(token)s

# 1. %(curl_create)s
curl -s -X POST $API/profiles -H "Authorization: Bearer $KEY" \\
     -d '{"name": "shop-1", "platform": "windows"}'

# 2. %(curl_start)s
curl -s -X POST $API/profiles/1/start -H "Authorization: Bearer $KEY"

# 3. %(curl_stop)s
curl -s -X POST $API/profiles/1/stop -H "Authorization: Bearer $KEY"

# %(curl_more)s
curl -s $API/profiles -H "Authorization: Bearer $KEY"
curl -s -X PATCH $API/profiles/1 -H "Authorization: Bearer $KEY" -d '{"name": "shop-2", "tags": ["eu"]}'
curl -s -X DELETE $API/profiles/1 -H "Authorization: Bearer $KEY"
'''

_PLAYWRIGHT = '''\
import requests
from playwright.sync_api import sync_playwright

API = "%(url)s/v1"
HEADERS = {"Authorization": "Bearer %(token)s"}


def api(method, path, **body):
    reply = requests.request(method, API + path, headers=HEADERS, json=body or None, timeout=120)
    data = reply.json()
    if reply.status_code >= 400:
        raise RuntimeError(data["error"]["message"])
    return data


# 1. %(profile)s
found = [p for p in api("GET", "/profiles?q=shop-1")["items"] if p["name"] == "shop-1"]
profile = found[0] if found else api("POST", "/profiles", name="shop-1", platform="windows")

# 2. %(start_pw)s
run = api("POST", f"/profiles/{profile['id']}/start")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(run["connection"]["ws"])
    context = browser.contexts[0]        # %(context)s
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()                      # %(disconnect)s

# 3. %(stop)s
api("POST", f"/profiles/{profile['id']}/stop")
'''

_PUPPETEER = '''\
// Node 18+.   npm install puppeteer-core
import puppeteer from "puppeteer-core";

const API = "%(url)s/v1";
const HEADERS = { Authorization: "Bearer %(token)s", "Content-Type": "application/json" };

async function api(method, path, body) {
  const reply = await fetch(API + path, { method, headers: HEADERS, body: body && JSON.stringify(body) });
  const data = await reply.json();
  if (!reply.ok) throw new Error(data.error.message);
  return data;
}

// 1. %(profile_js)s
const found = (await api("GET", "/profiles?q=shop-1")).items.filter((p) => p.name === "shop-1");
const profile = found[0] ?? (await api("POST", "/profiles", { name: "shop-1", platform: "windows" }));

// 2. %(start_pup)s
const run = await api("POST", `/profiles/${profile.id}/start`);

// %(viewport)s
const browser = await puppeteer.connect({ browserWSEndpoint: run.connection.ws, defaultViewport: null });
const [page] = await browser.pages();
await page.goto("https://example.com");
console.log(await page.title());
await browser.disconnect();              // %(disconnect)s

// 3. %(stop)s
await api("POST", `/profiles/${profile.id}/stop`);
'''

_SELENIUM = '''\
import requests
from selenium import webdriver

API = "%(url)s/v1"
HEADERS = {"Authorization": "Bearer %(token)s"}


def api(method, path, **body):
    reply = requests.request(method, API + path, headers=HEADERS, json=body or None, timeout=120)
    data = reply.json()
    if reply.status_code >= 400:
        raise RuntimeError(data["error"]["message"])
    return data


# 1. %(profile)s
found = [p for p in api("GET", "/profiles?q=shop-1")["items"] if p["name"] == "shop-1"]
profile = found[0] if found else api("POST", "/profiles", name="shop-1", platform="windows")

# 2. %(start_sel)s
run = api("POST", f"/profiles/{profile['id']}/start")

options = webdriver.ChromeOptions()
options.debugger_address = run["connection"]["debugger_address"]     # %(attach)s
driver = webdriver.Chrome(options=options)
driver.get("https://example.com")
print(driver.title)
driver.quit()                            # %(detach)s

# 3. %(stop)s
api("POST", f"/profiles/{profile['id']}/stop")
'''

_TEMPLATES = (
    ("playwright", "Python · Playwright", "antidetect_playwright.py", "pip install requests playwright", _PLAYWRIGHT, "python"),
    ("puppeteer", "Node.js · Puppeteer", "antidetect_puppeteer.mjs", "npm install puppeteer-core", _PUPPETEER, "javascript"),
    ("selenium", "Python · Selenium", "antidetect_selenium.py", "pip install requests selenium", _SELENIUM, "python"),
    ("curl", "curl", "antidetect_curl.sh", "", _CURL, "bash"),
)

KEYS = tuple(key for key, *_ in _TEMPLATES)


def examples(url: str, token: str, lang: str = "en") -> list[Example]:
    index = 1 if lang == "ru" else 0
    values = {"url": url, "token": token, **{name: texts[index] for name, texts in _COMMENTS.items()}}
    return [Example(key, title, filename, install, code % values, fence)
            for key, title, filename, install, code, fence in _TEMPLATES]


def example(key: str, url: str, token: str, lang: str = "en") -> Example:
    for item in examples(url, token, lang):
        if item.key == key:
            return item
    raise KeyError(key)
