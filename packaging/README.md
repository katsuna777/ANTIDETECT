# Сборка и выпуск

## Локально

```bash
pip install -e ".[build]"
python packaging/build.py                      # то, что соберётся, зависит от ОС, на которой запущено
python packaging/build.py --qt-platform offscreen   # самотест без окон (удобно по SSH)
```

Результат в `release/`: `Antidetect-<версия>-windows-x64.exe` или `Antidetect-<версия>-macos-<arm64|x64>.dmg` и `.sha256`.
Кросс-сборки нет: Windows собирается на Windows, macOS — на Mac (arm64 даёт приложение для Apple Silicon, на Intel-Mac соберётся Intel-версия).

Что делает `build.py`: проверка окружения → PyInstaller → поиск «пропавших» модулей → проверка бандла → (macOS: подпись, `.dmg`, нотаризация) → **запуск собранного приложения в режиме `--selftest`** (БД и миграции, главное окно, все страницы, ресурсы) → файл с версией в имени + SHA-256. Если самотест не прошёл, файл в `release/` не появится.

## Релиз

1. Поднимите `__version__` в `src/antidetect/__init__.py`, закоммитьте, `git push`.
2. `git tag v0.2.0 && git push origin v0.2.0` — **тег обязан совпадать с версией в коде**, иначе workflow остановится.
3. Actions → Release: тесты → сборка Windows, macOS arm64 и macOS Intel → GitHub Release с файлами, `SHA256SUMS.txt` и текстом из `.github/release-notes.md`.

Сборка каждого пуша в `main` (workflow Build) кладёт файлы в Artifacts запуска на 7 дней; Intel-Mac там по умолчанию выключен (галочка при ручном запуске).

## Деньги и место

Репозиторий приватный: минуты macOS-раннера считаются ×10, Windows — ×2 (в бесплатные 2000 минут в месяц). Одна сборка Mac ≈ 2–4 минуты, поэтому Intel-версия собирается только в релизах. Artifacts занимают место в квоте 500 МБ — отсюда срок хранения 7 дней (у релиза 1 день: файлы остаются в самом Release).

## Подпись (необязательно)

Без подписи всё работает, но Windows SmartScreen и macOS Gatekeeper показывают предупреждения (см. `.github/release-notes.md`).

**macOS** (нужен Apple Developer Program, $99/год). В Settings → Secrets and variables → Actions добавьте:

| Секрет | Что |
|---|---|
| `MACOS_CERTIFICATE_P12` | сертификат «Developer ID Application» в `.p12`, закодированный в base64 |
| `MACOS_CERTIFICATE_PASSWORD` | пароль от `.p12` |
| `MACOS_CODESIGN_IDENTITY` | например `Developer ID Application: Имя (TEAMID)` |
| `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` | для нотаризации (пароль приложения с appleid.apple.com) |

Тогда `build.py` подпишет приложение с hardened runtime (`entitlements.plist`), нотаризует и «проштампует» `.dmg`; текст в `.github/release-notes.md` про `xattr` после этого можно убрать. *Эта ветка написана, но на настоящих сертификатах ни разу не запускалась.*

**Windows**: подпись требует сертификата (OV/EV или Azure Trusted Signing) и в сборке не настроена. В свойствах exe уже есть имя и версия — это снижает, но не убирает подозрения антивирусов к onefile-сборке.

## Версии и воспроизводимость

CI ставит зависимости строго по `uv.lock` (`uv sync --frozen`, Python 3.12): после `uv add`/`uv lock` закоммитьте и `uv.lock`. Приложению нужна macOS 13+ (колёса PySide6 помечены `macosx_13_0`).
