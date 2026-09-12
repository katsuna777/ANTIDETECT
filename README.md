<div align="center">

# 🛡️ ANTIDETECT

### Независимые Chromium-профили · SQLite-хранилище · CLI + GUI поверх одной бизнес-логики

[![CI](https://github.com/katsuna777/ANTIDETECT/actions/workflows/ci.yml/badge.svg)](https://github.com/katsuna777/ANTIDETECT/actions/workflows/ci.yml)
[![Build](https://github.com/katsuna777/ANTIDETECT/actions/workflows/build.yml/badge.svg)](https://github.com/katsuna777/ANTIDETECT/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/katsuna777/ANTIDETECT?style=flat-square&color=blue)](https://github.com/katsuna777/ANTIDETECT/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/GUI-PySide6_Qt6-green?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Tests](https://img.shields.io/badge/tests-580%2B_passing-success?style=flat-square&logo=pytest)](tests/)
[![License](https://img.shields.io/badge/license-Proprietary-red?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows_%7C_macOS-lightgrey?style=flat-square&logo=windows&logoColor=white)](https://github.com/katsuna777/ANTIDETECT/releases)

**Каждый профиль — отдельный браузер со своими cookies, proxy, языком, часовым поясом и fingerprint-настройками.<br/>Перезапустил — всё на месте: вкладки, сессии, localStorage.**

[🚀 Быстрый старт](#-быстрый-старт-за-5-минут) · [📦 Скачать готовую сборку](#-готовые-сборки-без-python--рекомендуется) · [⌨️ CLI](#️-cli--терминал-без-мыши) · [🖥️ GUI](#️-gui-приложение) · [❓ FAQ](#-faq--решение-проблем)

</div>

---

## 📑 Содержание

- [✨ Возможности](#-возможности)
- [🧱 Как это устроено](#-как-это-устроено)
- [📦 Готовые сборки — без Python ⭐](#-готовые-сборки-без-python--рекомендуется)
- [🚀 Быстрый старт за 5 минут](#-быстрый-старт-за-5-минут)
- [📋 Зависимости](#-зависимости)
- [⌨️ CLI — терминал без мыши](#️-cli--терминал-без-мыши)
- [🖥️ GUI-приложение](#️-gui-приложение)
- [🌐 Прокси](#-прокси)
- [🩺 Doctor — gate перед стартом и Google login](#-doctor--gate-перед-стартом-и-google-login)
- [⚙️ Переменные окружения](#️-переменные-окружения)
- [🗂️ Где лежат данные](#️-где-лежат-данные)
- [🌍 Chromium — какой браузер нужен](#-chromium--какой-браузер-нужен)
- [🏗️ Архитектура](#️-архитектура)
- [🧪 Тесты](#-тесты)
- [🔨 Сборка из исходников](#-сборка-из-исходников-разработчикам)
- [🔄 CI/CD](#-cicd)
- [❓ FAQ / Решение проблем](#-faq--решение-проблем)
- [🗺️ Roadmap](#️-roadmap)
- [📄 Лицензия](#-лицензия)

---

## ✨ Возможности

| | Возможность | Что это даёт |
|---|---|---|
| 🧩 | **Изолированные Chromium-профили** | Каждый профиль = свой `--user-data-dir`: cookies, localStorage, IndexedDB, кэш, permissions, вкладки |
| 🔁 | **Persistent state** | Закрыл браузер → открыл → всё на месте. Профили не смешиваются, двойной запуск одного профиля запрещён |
| ⌨️ | **CLI + 🖥️ GUI на одной логике** | Терминал и окно — тонкие оболочки над одним `ProfileService`. Что умеет CLI — то умеет и GUI |
| 🌐 | **Пул прокси с гео** | Сбор из источников, проверка в 64 воркера, пинг, страна, автоподбор конфига под прокси |
| 🩺 | **`doctor` fail-closed gate** | Перед стартом профиль проверяется. `BLOCKED` = старт запрещён + инструкция как чинить |
| 🌍 | **Гео-консистентность** | Язык ↔ часовой пояс ↔ локаль ↔ страна прокси синхронизируются автоматически |
| 🍪 | **Бэкап cookies** | Экспорт/импорт cookies профиля |
| 🇷🇺🇬🇧 | **EN/RU интерфейс** | Переключение языка GUI с сохранением |
| 📦 | **Автономные .exe / .app** | Python, Qt и все зависимости внутри. Ставить Python не нужно |
| 🧪 | **580+ тестов** | CRUD, lifecycle, миграции, Chromium через stub-бинарник, GUI headless |

---

## 🧱 Как это устроено

```
┌─────────────────────────────────────────────────────────┐
│                    ТЫ (пользователь)                     │
│            ⌨️ терминал        🖥️ окно приложения          │
└───────────┬─────────────────────────┬───────────────────┘
            │                         │
            ▼                         ▼
     ┌────────────┐            ┌──────────────┐
     │    CLI     │            │     GUI      │
     │  app ...   │            │  PySide6/Qt6 │
     │ main.py    │            │  + workers   │
     └─────┬──────┘            └──────┬───────┘
           │         один и тот же    │
           └──────────► Container ◄───┘
                    bootstrap() из di.py
                           │
                           ▼
                  ┌─────────────────┐
                  │ ProfileService  │  ← вся бизнес-логика
                  │ ProxyService    │
                  │ + doctor gate   │
                  └────┬───────┬────┘
                       │       │
              ┌────────▼──┐ ┌──▼─────────────┐
              │  SQLite   │ │ ChromiumManager │
              │ +миграции │ │ --user-data-dir │
              └───────────┘ └─────────────────┘
```

> **Золотое правило:** GUI и CLI никогда не трогают SQLite и Chromium напрямую — только через сервисы. Поэтому поведение в окне и в терминале всегда одинаковое.

---

## 📦 Готовые сборки — без Python ⭐ <a id="-готовые-сборки-без-python--рекомендуется"></a>

> **Это самый простой способ.** Ничего ставить не надо: Python, Qt и все библиотеки уже упакованы внутрь.

| ОС | Файл | Что делать |
|---|---|---|
| 🪟 **Windows 10/11 x64** | `Antidetect.exe` | 1. Скачай из [Releases](https://github.com/katsuna777/ANTIDETECT/releases) <br/> 2. Положи в **пустую папку** <br/> 3. Двойной клик — всё |
| 🍎 **macOS 13+** | `Antidetect.dmg` | 1. Скачай из [Releases](https://github.com/katsuna777/ANTIDETECT/releases) <br/> 2. Открой `.dmg` <br/> 3. Перетащи `Antidetect.app` в **Applications** <br/> 4. Запусти |

<details>
<summary><b>⚠️ macOS: «файл повреждён / не удаётся открыть» — что делать</b></summary>

<br/>

Unsigned-приложения macOS блокирует по умолчанию. Решение в терминале:

```bash
xattr -cr /Applications/Antidetect.app
```

Затем правый клик по `Antidetect.app` → **Открыть** → подтвердить.

</details>

<details>
<summary><b>⚠️ Windows SmartScreen ругается — что делать</b></summary>

<br/>

Нажми **«Подробнее» → «Выполнить в любом случае»**. EXE не подписан кодовым сертификатом — это нормально для v0.x.

</details>

**Требования для готовых сборок:**

- 🪟 Windows 10/11 x64 **или** 🍎 macOS 13+
- 🌍 Установленный Chrome / Chromium / Brave / Edge *(внутрь сборки браузер не вшит — см. [почему](#-chromium--какой-браузер-нужен))*
- 💾 ~150 МБ на диске + место под профили

---

## 🚀 Быстрый старт за 5 минут

Запуск **из исходников** — для разработчиков и тех, кто хочет всё контролировать через терминал.

### Шаг 0. Что должно стоять на чистом компьютере

| Зависимость | Версия | Как проверить | Где взять |
|---|---|---|---|
| 🐍 **Python** | **3.12+** (разработка на 3.12 / 3.13) | `python3 --version` | [python.org](https://www.python.org/downloads/) |
| 📦 **Git** | любая свежая | `git --version` | [git-scm.com](https://git-scm.com/) |
| 🌍 **Chromium-браузер** | Chrome / Chromium / Brave / Edge | открой браузер — он есть? | [chrome.google.com](https://www.google.com/chrome/) |

### Шаг 1. Клонируй репозиторий

```bash
git clone https://github.com/katsuna777/ANTIDETECT.git
cd ANTIDETECT
```

### Шаг 2. Создай и активируй виртуальное окружение

**macOS / Linux:**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Если PowerShell ругается на скрипты: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` — и повтори.

### Шаг 3. Установи зависимости

```bash
# ── обязательно: рантайм приложения ──────────────────────
pip install --upgrade pip
pip install -r requirements.txt

# ── чтобы работала команда `app` / `app-gui` из любого места ──
pip install -e .

# ── дополнительно: для запуска тестов ────────────────────
pip install -r requirements-dev.txt
```

Проверка, что всё встало:

```bash
pip list | grep -iE "pyside|websocket|platformdirs|certifi|pytest"
```

### Шаг 4. Настрой окружение (необязательно)

Файл `.env` **не требуется** для запуска — значения по умолчанию уже разумные. Только если автообнаружение не нашло браузер или хочешь свою папку данных:

```bash
cp .env.example .env
```

Открой `.env` и при необходимости задай (подробности — [ниже](#️-переменные-окружения)):

```bash
ANTIDETECT_CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ANTIDETECT_DATA_DIR="./data"
```

> 🔒 `.env` уже в `.gitignore`. Реальные секреты никогда не коммить.

### Шаг 5. Запусти 🚀

**Вариант А — окно приложения (GUI):**

```bash
python -m app.gui
# или коротко, после `pip install -e .`:
app-gui
```

**Вариант Б — терминал (CLI):**

```bash
# через установленный entry-point:
app profile list

# или напрямую без установки:
python main.py profile list
```

Оба способа равнозначны — выбирай любой. Дальше — [полная шпаргалка по CLI](#️-cli--терминал-без-мыши) 👇

### Шаг 6. Первый профиль за 30 секунд

```bash
app profile create "Мой первый"
app profile list
app profile doctor 1
app profile start 1
```

Откроется Chromium с чистым изолированным профилем. Закрой окно браузера или выполни `app profile stop 1` — состояние сохранится.

### Шаг 7. Проверь, что ничего не сломано

```bash
pytest -q
```

Ожидаемо: `581 passed`. GUI-тесты headless (без дисплея / на CI):

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

---

## 📋 Зависимости

Всё, что тянет проект, — 4 runtime-пакета + pytest для тестов + PyInstaller для сборки. Ничего экзотического.

### Runtime (`requirements.txt`)

| Пакет | Зачем нужен |
|---|---|
| `websocket-client >= 1.8` | CDP/общение с Chromium |
| `platformdirs >= 4` | OS user-data dir для собранного приложения (`%APPDATA%`, `~/Library/...`, `~/.local/share`) |
| `PySide6 >= 6.6` | GUI на Qt6 |
| `certifi >= 2024.0` | CA-сертификаты для HTTPS (прокси-источники, пробы) |

### Dev (`requirements-dev.txt`)

| Пакет | Зачем нужен |
|---|---|
| `pytest >= 8` | Тесты (581 шт.) |

### Build (`requirements-build.txt`)

| Пакет | Зачем нужен |
|---|---|
| `pyinstaller >= 6` | Упаковка в `Antidetect.exe` / `Antidetect.app` |

Установка одним блоком (всё сразу — рантайм + тесты + сборка):

```bash
pip install -r requirements-build.txt   # тянет requirements.txt за собой
pip install -r requirements-dev.txt
pip install -e .
```

---

## ⌨️ CLI — терминал без мыши

> Всё делается из терминала. GUI не нужен вообще. Две равнозначные формы вызова:
> `app …` (после `pip install -e .`) **или** `python main.py …` (без установки, из корня репо).

### Профили — основа всего

```bash
app profile create "Test 01"          # создать профиль
app profile list                      # таблица: ID / NAME / STATUS
app profile show 1                    # детали профиля
app profile edit 1 "New Name"         # переименовать (alias: update)
app profile start 1                   # запустить Chromium с этим профилем
app profile stop 1                    # остановить
app profile restart 1                 # перезапустить
app profile duplicate 1               # копия профиля вместе с browser state
app profile delete 1 --yes            # удалить строку и каталог данных
```

### Диагностика перед стартом

```bash
app profile doctor 1                  # OK / BLOCKED + как чинить
app profile doctor 1 --no-probe       # офлайн-режим, без Google-пробы
```

> Если `doctor` говорит `BLOCKED` — `start` откажет с объяснением. Сначала чиним, потом стартуем. Детали — [ниже](#-doctor--gate-перед-стартом-и-google-login).

### Прокси профиля

```bash
app profile proxy 1 --set 3               # назначить прокси #3 (конфиг подтянется сам)
app profile proxy 1 --set 3 --no-auto-config  # назначить, конфиг не трогать
app profile proxy 1 --clear               # отвязать прокси
```

### Пул прокси

```bash
app proxy list                        # таблица: working сверху, лучший пинг первым
app proxy refresh                     # собрать → распарсить → дедуп → проверить → обновить пул
app proxy check 3                     # проверить один прокси по id
app proxy check-all                   # перепроверить все
app proxy remove-dead                 # удалить подтверждённые DEAD
```

### Конфигурации браузера

```bash
app config list                       # список browser-конфигураций
app config show 1                     # детали конфигурации
```

### Cookies

```bash
app cookies backup 1                  # сохранить cookies профиля #1
app cookies restore 1                 # восстановить cookies профиля #1
```

### Справка по любой команде

```bash
app --help
app profile --help
app proxy --help
app profile doctor --help
```

---

## 🖥️ GUI-приложение

GUI — тонкая презентационная прослойка над тем же `Container`/`bootstrap()`, что использует CLI. Напрямую SQLite/Chromium из GUI недоступны.

```bash
python -m app.gui        # основной способ
app-gui                  # тоже самое, после `pip install -e .`
```

**Что внутри:**

- 🧵 Тяжёлые операции (старт браузера, проверка прокси) — на `QThreadPool` через workers. Интерфейс **не зависает**
- 🪟 Один `Container` на весь сеанс, корректно закрывается по `QApplication.aboutToQuit`
- 🇷🇺🇬🇧 Переключение EN/RU с сохранением выбора
- 🌐 Сводка прокси, живой список обновления без лагов, флаг страны и endpoint в строках профилей
- 🎨 Splash screen (`ANTIDETECT_NO_SPLASH=1` — пропустить)

Полезные переменные для запуска GUI:

```bash
ANTIDETECT_NO_SPLASH=1 python -m app.gui   # без сплэша
QT_QPA_PLATFORM=offscreen python -m app.gui  # headless (для тестов/CI)
```

---

## 🌐 Прокси

1. `app proxy refresh` — собирает кандидаты из `ANTIDETECT_PROXY_SOURCES` (или встроенных), дедуплицирует и проверяет в **64 воркера**.
2. `app proxy list` — показывает живые сверху: статус, пинг, страна, endpoint.
3. `app profile proxy 1 --set 3` — привязывает прокси к профилю **и автоматически** подгоняет fingerprint-конфиг (язык, локаль, часовой пояс) под страну прокси.
4. Требование: страна прокси должна быть известна (`app proxy check 3`). Без страны конфиг не трогается — только warning.

```bash
# полный цикл в 4 команды:
app proxy refresh
app proxy list
app proxy check 3
app profile proxy 1 --set 3
```

---

## 🩺 Doctor — gate перед стартом и Google login

Перед каждым `start` профиль проходит **fail-closed** диагностику (проверка fingerprint/прокси, блокирующих вход в Google):

```bash
app profile doctor 1              # verdict: OK / BLOCKED + инструкция
app profile start 1               # при BLOCKED — отказ с объяснением
```

Типичные причины `BLOCKED` и лечение:

| Причина | Что делать |
|---|---|
| Прокси DEAD / таймаут | `app proxy check-all`, затем `remove-dead` + `refresh` |
| Страна прокси неизвестна | `app proxy check <id>` — дождаться гео |
| Рассинхрон гео ↔ часовой пояс | `app profile proxy 1 --set <id>` без `--no-auto-config` |
| Нет сети (офлайн) | `app profile doctor 1 --no-probe` для локальной проверки |

---

## ⚙️ Переменные окружения

Проект читает **только** переменные `ANTIDETECT_*` (плюс legacy `CHROME_PATH`) через `os.environ`. Никакой dotenv-зависимости нет — просто экспортируй или положи в `.env`.

| Переменная | Где взять значение | По умолчанию |
|---|---|---|
| `ANTIDETECT_CHROMIUM_PATH` / `CHROME_PATH` | Полный путь к бинарю Chrome/Chromium/Brave/Edge. Нужен **только если автообнаружение не нашло браузер** | Автопоиск по типовым путям и `PATH` |
| `ANTIDETECT_DATA_DIR` | Любой writable-каталог под SQLite + профили + логи | `./data` (из исходников) · OS user-data dir (в сборке) |
| `ANTIDETECT_LOGS_DIR` | Каталог логов Chromium | Внутри `data_dir` |
| `ANTIDETECT_PROXY_SOURCES` | JSON-список URL источников прокси (`http(s)://…`) | Встроенные источники |
| `ANTIDETECT_PROXY_WORKERS` | Число воркеров проверки (напр. `64`) | `64` |
| `ANTIDETECT_PROXY_TIMEOUT` | Таймаут проверки, сек | см. `.env.example` |
| `ANTIDETECT_PROXY_MAX_FAILURES` / `_DEAD_POLICY` / `_STALE_MINUTES` | Тюнинг смерти/устаревания прокси | см. `.env.example` |
| `ANTIDETECT_DISABLE_STEALTH` | `1` — выключить stealth-инжекты (отладка) | выкл. |
| `ANTIDETECT_NO_SPLASH` | `1` — пропустить splash screen | выкл. |
| `ANTIDETECT_NO_SANDBOX` | `1` — запуск Chromium без sandbox (Linux root/CI) | выкл. |
| `ANTIDETECT_STEALTH_TRACE` | Путь для stealth-trace дампа | выкл. |

Шаблон со всеми ключами: [`.env.example`](.env.example)

---

## 🗂️ Где лежат данные

Каждый профиль получает собственный каталог Chromium, который передаётся через `--user-data-dir`:

```
data/
├── antidetect.db          # SQLite: профили, прокси, конфиги, логи
└── profiles/
    ├── profile_001/       # cookies, localStorage, IndexedDB, cache, вкладки
    ├── profile_002/
    └── profile_003/
```

| Режим | Где данные |
|---|---|
| 🏃 Из исходников | `./data` в корне репозитория |
| 📦 Собранное приложение | OS user-data dir: `%APPDATA%/Antidetect` · `~/Library/Application Support/Antidetect` · `~/.local/share/Antidetect` |
| 🔧 Принудительно | Куда указывает `ANTIDETECT_DATA_DIR` (переопределяет всё) |

Миграции схемы (`schema_migrations` + модули в `src/app/infrastructure/database/migrations/versions/`) применяются **автоматически при старте** — руками ничего делать не надо.

---

## 🌍 Chromium — какой браузер нужен

Используется **установленный** в системе браузер — в сборку он **не вшивается** (лицензии + сотни мегабайт веса). Подходит любой из: **Chrome, Chromium, Brave, Edge**.

Порядок поиска бинарника:

1. Параметр из конфигурации приложения
2. `ANTIDETECT_CHROMIUM_PATH` / `CHROME_PATH`
3. Типовые пути платформы (`/Applications/Google Chrome.app/…`, `C:\Program Files\Google\Chrome\…` и т.п.)
4. `PATH` (`which google-chrome` / `chrome` / `chromium` …)

Проверить, что браузер найден:

```bash
# macOS
ls "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Windows (PowerShell)
Get-Command chrome.exe

# Linux
which google-chrome chromium chromium-browser brave-browser
```

Не нашлось автоматически? Укажи путь явно:

```bash
export ANTIDETECT_CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
app profile start 1
```

---

## 🏗️ Архитектура

```
GUI (src/app/gui)                 — PySide6 shell + workers (никогда напрямую SQLite/Chromium)
CLI (src/app/cli)                 — команды profile/config/cookies/proxy (никакой работы с SQLite/Chromium напрямую)
Application (src/app/application) — ProfileService, ProxyService, ConfigurationService, CookieService, LogService + ports
Domain (src/app/domain)           — модели, enums, ошибки
Repositories (src/app/infrastructure/database) — SQLite, миграции
Infrastructure (src/app/infrastructure/chromium) — ChromiumManager (запуск, reconcile, stub-тестируемый)
Config + composition root         — src/app/config/settings.py, src/app/di.py → bootstrap()
```

Ключевые инварианты:

- `bootstrap()` в `di.py` собирает зависимости и отдаёт готовый `ProfileService` — и для CLI, и для GUI.
- Повторный запуск одного профиля запрещён, пока его процесс жив; упавшие процессы вычищаются через reconcile.
- `duplicate` копирует профиль **вместе с browser state**.
- `delete --yes` удаляет и строку в БД, и каталог данных.

---

## 🧪 Тесты

```bash
pytest                 # все 581 тестов
pytest -q              # коротко
pytest tests/test_lifecycle.py -q     # один файл
QT_QPA_PLATFORM=offscreen pytest -q   # headless GUI-тесты
```

Покрытие: CRUD профилей, `duplicate`, репозитории, генерация путей, lifecycle (start/stop/restart), запрет двойного запуска, reconcile упавших процессов, миграции, ChromiumManager через stub-бинарник, GUI (workers, навигация, preferences, error handling).

CI гоняет тот же `pytest` на Python 3.12 при каждом push в `main` и каждом PR.

---

## 🔨 Сборка из исходников (разработчикам)

> Обычным пользователям это не нужно — берите готовые файлы из [Releases](https://github.com/katsuna777/ANTIDETECT/releases).

**Кросс-сборка не поддерживается:** `.exe` собирается **только на Windows**, `.dmg` — **только на macOS**.

```bash
# Windows (только на Windows), PowerShell:
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
# → release/Antidetect.exe   (PyInstaller --onefile, console=False, build-windows.spec)

# macOS (только на macOS):
bash scripts/build_macos.sh
# → dist/Antidetect.app → release/Antidetect.dmg   (build-macos.spec, bundle com.antidetect.browser)
```

Валидация артефактов:

```bash
python scripts/validate_windows.py --exe release/Antidetect.exe
python3 scripts/validate_macos.py --app dist/Antidetect.app --dmg release/Antidetect.dmg
```

Про macOS-архитектуры: CI собирает нативную архитектуру раннера `macos-latest` (сейчас arm64). Universal 2 возможен, только если все колёса (PySide6, websocket-client, platformdirs) есть как fat/universal — workflow печатает `platform.machine()` и `lipo -archs` для контроля. Intel-Mac требует отдельной сборки на x86_64-раннере.

---

## 🔄 CI/CD

| Workflow | Что делает | Когда запускается |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | checkout → Python 3.12 → install → `pytest` | `push` в `main`, `pull_request`, `workflow_dispatch` (+ `workflow_call`) |
| [`build.yml`](.github/workflows/build.yml) | `tests` → `build-windows` + `build-macos` (сборка не стартует при красных тестах) → artifacts `Antidetect.exe` / `Antidetect.dmg` | `push` в `main`, `workflow_dispatch` |
| [`release.yml`](.github/workflows/release.yml) | то же + публикация **GitHub Release** при push тега `v*` | push тега `v1.0.0`, `workflow_dispatch` |

**Как выпустить новую версию** (для мейнтейнера):

```bash
git tag v0.0.2
git push origin v0.0.2
# → CI прогонит тесты, соберёт exe+dmg и опубликует Release автоматически
```

---

## ❓ FAQ / Решение проблем

<details>
<summary><b>🐍 <code>python -m app.gui</code> — ModuleNotFoundError: app</b></summary>

<br/>

Запускаешь не из корня репозитория или не стоит `pip install -e .`. Решение:

```bash
cd /путь/к/ANTIDETECT
pip install -e .
python -m app.gui
```

Либо без установки: `PYTHONPATH=src python -m app.gui`.

</details>

<details>
<summary><b>🔍 Профиль не стартует: «Chromium binary not found»</b></summary>

<br/>

Поставь Chrome/Chromium/Brave/Edge или укажи путь вручную:

```bash
export ANTIDETECT_CHROMIUM_PATH="/полный/путь/к/chrome"
app profile doctor 1
app profile start 1
```

</details>

<details>
<summary><b>🩺 <code>doctor</code> говорит BLOCKED</b></summary>

<br/>

Смотри [таблицу причин](#-doctor--gate-перед-стартом-и-google-login). Коротко: `app proxy check-all` → `remove-dead` → `refresh` → привяжи живой прокси с известной страной.

</details>

<details>
<summary><b>🪟 PowerShell не даёт активировать venv</b></summary>

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

</details>

<details>
<summary><b>🧪 Падают GUI-тесты на headless-сервере</b></summary>

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

</details>

<details>
<summary><b>💾 Где моя база? Хочу бэкап</b></summary>

Из исходников — `./data/antidetect.db`. Скопируй файл целиком на остановленном приложении. В сборке — см. [таблицу путей](#️-где-лежат-данные).

</details>

---

## 🗺️ Roadmap

- [x] v0.0.1 — CLI + GUI, изолированные профили, пул прокси, doctor-gate, сборки exe/dmg
- [ ] Подписанные сборки (Windows cert + macOS notarization — убрать варнинги)
- [ ] Universal 2 dmg (arm64 + x86_64)
- [ ] Автообновление приложения из Releases
- [ ] Расширенные fingerprint-пресеты

---

## 📄 Лицензия

Proprietary — все права защищены. Использование, копирование и распространение без письменного разрешения автора запрещены.

---

<div align="center">

**Сделано с ❤️ и большим количеством терминалов**

[⬆ Наверх](#-antidetect) · [🚀 Быстрый старт](#-быстрый-старт-за-5-минут) · [📦 Releases](https://github.com/katsuna777/ANTIDETECT/releases) · [🐛 Issues](https://github.com/katsuna777/ANTIDETECT/issues)

</div>
