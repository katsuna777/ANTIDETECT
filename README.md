# Antidetect Browser

Репозиторий: https://github.com/katsuna777/browser.git

Независимые Chromium-профили, SQLite-хранилище, CLI + PySide6 GUI поверх одной бизнес-логики.

## Запуск с нуля (чистый компьютер)

1. Установите зависимости окружения: Python 3.12 (минимально поддерживается 3.12; разработка ведётся на 3.12/3.13), Git и установленный Chromium-браузер (Google Chrome, Chromium, Brave или Edge). Windows 10/11 x64, macOS 13+ (см. раздел «Сборка и архитектуры»).
2. Клонируйте репозиторий и перейдите в него:
   ```bash
   git clone https://github.com/katsuna777/browser.git
   cd browser
   ```
3. Создайте и активируйте виртуальное окружение:
   ```bash
   python3.12 -m venv .venv
   ```
   Windows:
   ```bash
   .\.venv\Scripts\activate
   ```
   macOS / Linux:
   ```bash
   source .venv/bin/activate
   ```
4. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
   Для тестов дополнительно:
   ```bash
   pip install -r requirements-dev.txt
   ```
5. Настройте переменные окружения (необязательно, файл `.env` не требуется для запуска). Проект читает только `ANTIDETECT_*` переменные через `os.environ` (см. `src/app/config/settings.py`, `.env.example`). Скопируйте шаблон при необходимости:
   ```bash
   cp .env.example .env
   ```
   Основные переменные:
   | Переменная | Где взять значение | По умолчанию |
   |---|---|---|
   | `ANTIDETECT_CHROMIUM_PATH` / `CHROME_PATH` | полный путь к бинарю Chrome/Chromium/Brave/Edge; нужен только если автообнаружение не нашло браузер | автопоиск по типовым путям и `PATH` |
   | `ANTIDETECT_DATA_DIR` | любой writable-каталог для SQLite + профилей + логов | `./data` в checkout, OS user-data dir в собранном приложении |
   | `ANTIDETECT_LOGS_DIR` | каталог логов Chromium | внутри `data_dir` |
   | `ANTIDETECT_PROXY_SOURCES` | JSON-список URL источников прокси (`http(s)://...`) | встроенные источники |
   | `ANTIDETECT_PROXY_WORKERS/TIMEOUT/MAX_FAILURES/DEAD_POLICY/STALE_MINUTES` | числа/строки для тюнинга проверки прокси | см. `.env.example` |
   Реальные секреты/токены в проекте не используются; ничего секретного в репозиторий не коммитьте (`.env` уже в `.gitignore`).
6. Запустите проект. GUI (основное приложение):
   ```bash
   pip install -e .
   python -m app.gui
   ```
   (из корня репозитория; либо команда `app-gui` после `pip install -e .`). CLI:
   ```bash
   python main.py profile list
   app profile create "Test 01"
   app profile list
   ```
7. Проверьте тесты:
   ```bash
   pytest
   ```
   GUI-тесты headless: `QT_QPA_PLATFORM=offscreen pytest`.

## Готовые сборки (без Python)

Каждая сборка полностью автономна: внутри лежат Python runtime, все зависимости (включая PySide6), иконки и ресурсы. Устанавливать Python, pip, venv или копировать рядом DLL/ресурсы не нужно. Пользовательские данные (БД, профили, логи) создаются при первом запуске в OS user-data dir (`%APPDATA%/Antidetect`, `~/Library/Application Support/Antidetect`, `~/.local/share/Antidetect`) или по `ANTIDETECT_DATA_DIR`.

* Windows: скачайте `Antidetect.exe` из Actions/Release, положите в пустую папку, запустите двойным кликом. Один файл, режим `--onefile`, папок с DLL рядом не требуется.
* macOS: скачайте `Antidetect.dmg`, откройте, перетащите `Antidetect.app` в Applications, запустите. Все runtime-компоненты внутри `.app`.

## Сборка приложения

Требуется только разработчику; обычным пользователям достаточно готовых `Antidetect.exe` / `Antidetect.dmg` из GitHub Actions/Release.

* Windows (только на Windows, `windows-latest`): `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1` → `release/Antidetect.exe`. Используется `build-windows.spec` (PyInstaller `--onefile`, `console=False`).
* macOS (только на macOS, `macos-latest`): `bash scripts/build_macos.sh` → `dist/Antidetect.app` → `release/Antidetect.dmg` (через `hdiutil`). Используется `build-macos.spec` (bundle `com.antidetect.browser`).
* Кросс-сборка не поддерживается: exe собирается только на Windows-раннере, dmg только на macOS-раннере.
* Валидация: `python scripts/validate_windows.py --exe release/Antidetect.exe`, `python3 scripts/validate_macos.py --app dist/Antidetect.app --dmg release/Antidetect.dmg`.

### Архитектуры macOS

CI собирает нативную архитектуру раннера `macos-latest` (сейчас arm64). Universal 2 (arm64+x86_64) возможен только если все колёса зависимостей (PySide6, websocket-client, platformdirs) доступны как fat/universal — workflow печатает `platform.machine()` и `lipo -archs` для контроля. Если часть зависимостей без universal-колёс, зафиксирована нативная сборка arm64; Intel-Mac требует отдельной сборки на x86_64-раннере. PyInstaller-бандл всегда содержит свой Python и Qt внутри `.app`.

## CI/CD

* `.github/workflows/ci.yml` — проверки: checkout → Python 3.12 → install → `pytest`. Триггеры: `push` в `main`, `pull_request`, `workflow_dispatch` (+ `workflow_call` для переиспользования).
* `.github/workflows/build.yml` — `tests` → `build-windows` + `build-macos` (через `needs`, сборка не стартует при красных тестах). Публикует `Antidetect.exe` / `Antidetect.dmg` как Actions artifacts.
* `.github/workflows/release.yml` — то же + публикация GitHub Release при push тега `v*` (например `v1.0.0`) с обоими файлами.

---

## CLI

CLI доступен двумя способами: команда `app` (после `pip install -e .`) или `python main.py`.

```bash
app profile create "Test 01"          # создать профиль
app profile list                      # таблица: ID / NAME / STATUS
app profile show 1                    # детали профиля
app profile edit 1 "New Name"         # переименовать (alias: update)
app profile start 1                   # запустить Chromium
app profile stop 1
app profile restart 1
app profile duplicate 1               # копия профиля вместе с browser state
app profile delete 1 --yes            # удалить строку и data dir
```

## GUI

GUI на PySide6 (`pip install -e .` уже включает PySide6), затем:

```bash
python -m app.gui        # или команда app-gui
```

GUI — тонкая презентационная прослойка: работает только через тот же `Container`/`bootstrap()`, что и CLI. SQLite, Chromium и repositories напрямую не используются; тяжёлые операции выполняются на `QThreadPool` через workers, UI-поток не блокируется. При завершении один на весь сеанс `Container` закрывается через `QApplication.aboutToQuit`.

## Persistent state

Каждый профиль получает собственный каталог Chromium:

```
data/
└── profiles/
    ├── profile_001/
    ├── profile_002/
    └── profile_003/
```

Каталог передаётся в Chromium через `--user-data-dir`, поэтому cookies, localStorage, IndexedDB, cache, permissions и открытые вкладки сохраняются между запусками. Профили не смешиваются; повторный запуск одного профиля запрещён, пока его процесс жив.

Расположение данных: `data/` в корне репозитория при разработке, либо OS user-data dir в собранном приложении (см. выше), либо `ANTIDETECT_DATA_DIR` (переопределяет всё).

## Chromium

Используется установленный Chromium-браузер (Chrome/Chromium/Brave/Edge). Поиск бинарника:

1. параметр из конфигурации;
2. `ANTIDETECT_CHROMIUM_PATH` / `CHROME_PATH`;
3. типовые пути платформы (`/Applications/Google Chrome.app/...` и т.п.);
4. `PATH`.

В собранное приложение браузер НЕ встраивается (лицензии + размер): на машине пользователя должен стоять Chrome/Chromium/Brave/Edge, либо укажите путь через `ANTIDETECT_CHROMIUM_PATH`.

## Архитектура

```
GUI (src/app/gui)          — PySide6 shell + workers (никогда напрямую SQLite/Chromium)
CLI (src/app/cli)          — никакой работы с SQLite/Chromium напрямую
Application (src/app/application) — ProfileService + ports
Domain (src/app/domain)      — модели, enums, ошибки
Repositories (src/app/infrastructure/database) — SQLite, migrations
Infrastructure (src/app/infrastructure/chromium) — ChromiumManager
Config + composition root    — src/app/config, src/app/di.py
```

`bootstrap()` в `di.py` собирает зависимости и отдаёт готовый `ProfileService`; GUI использует тот же `bootstrap()`.

## Миграции

Лёгкий in-house runner (`schema_migrations` + модули в `src/app/infrastructure/database/migrations/versions/`). Применяются автоматически при старте.

## Google login (doctor gate + прогрев)

Перед стартом профиль проходит fail-closed диагностику:

```bash
app profile doctor 1            # OK / BLOCKED + как чинить
app profile doctor 1 --no-probe # офлайн-режим без Google-пробы
app profile start 1             # при BLOCKED старт запрещён с объяснением
```

Автоподбор конфига под прокси:

```bash
app profile proxy 1 --set 3              # конфиг подтянется сам
app profile proxy 1 --set 3 --no-auto-config  # оставить конфиг как есть
```

Требование: страна прокси должна быть известна (`app proxy check 3`). Без страны конфиг не трогается (только warning).

## Тесты

```bash
pytest
```

Покрытие: CRUD профилей, duplicate, репозитории, генерация путей, lifecycle (start/stop/restart), запрет двойного запуска, reconcile упавших процессов, миграции, менеджер Chromium через stub-бинарник, а также GUI (workers, навигация, preferences, error handling — headless через `QT_QPA_PLATFORM=offscreen`).
