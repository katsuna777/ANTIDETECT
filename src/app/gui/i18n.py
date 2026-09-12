"""Application UI language: English / Russian.

Two languages only: ``"en"`` and ``"ru"``. The choice is persisted in the
settings table (``gui.language``) via :class:`Preferences`, applied live to
every window/page/dialog, and every switch is written to the app log.

Visuals are untouched: the theme keeps the same single font family/weight
(Inter → Helvetica fallbacks, both with full Cyrillic coverage), so Russian
text renders in the identical ledger style with no font problems.

Usage::

    from app.gui.i18n import tr, set_language, get_language, LANG_EN, LANG_RU

    label = tr("sidebar.profiles")          # -> "PROFILES" / "ПРОФИЛИ"
    msg = tr("profiles.created", id=7, name="shop")  # formatted
"""

from __future__ import annotations

LANG_EN = "en"
LANG_RU = "ru"
SUPPORTED = (LANG_EN, LANG_RU)
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


_STRINGS: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------- window/sidebar
    "app.title": {"en": "ANTIDETECT", "ru": "ANTIDETECT"},
    "sidebar.profiles": {"en": "PROFILES", "ru": "ПРОФИЛИ"},
    "sidebar.proxies": {"en": "PROXIES", "ru": "ПРОКСИ"},
    "sidebar.configurations": {"en": "CONFIGURATIONS", "ru": "КОНФИГУРАЦИИ"},
    "sidebar.log": {"en": "LOG", "ru": "ЖУРНАЛ"},
    "sidebar.settings": {"en": "SETTINGS", "ru": "НАСТРОЙКИ"},
    "sidebar.tip.profiles": {
        "en": "Browser profiles · list, launch, edit (1)",
        "ru": "Профили браузера · список, запуск, редактирование (1)",
    },
    "sidebar.tip.proxies": {
        "en": "Proxy pool · refresh, check, lookup IP (2)",
        "ru": "Пул прокси · обновление, проверка, узнать IP (2)",
    },
    "sidebar.tip.configurations": {
        "en": "Fingerprints · generate, reuse (3)",
        "ru": "Отпечатки · генерация, повторное использование (3)",
    },
    "sidebar.tip.log": {
        "en": "Live session log · export, clear (4)",
        "ru": "Журнал сессии · экспорт, очистка (4)",
    },
    "sidebar.tip.settings": {
        "en": "App preferences · theme, confirmations (5)",
        "ru": "Настройки приложения · тема, подтверждения (5)",
    },
    "sidebar.theme.dark": {"en": "◐  DARK", "ru": "◐  ТЁМНАЯ"},
    "sidebar.theme.light": {"en": "●  LIGHT", "ru": "●  СВЕТЛАЯ"},
    "sidebar.theme.tip": {
        "en": "Switch light / dark theme (T)",
        "ru": "Переключить светлую / тёмную тему (T)",
    },
    "sidebar.footer": {"en": "GUI · MONO LEDGER", "ru": "GUI · МОНО-ЖУРНАЛ"},
    "statusbar": {
        "en": "data dir · {data}   chrome · {chrome}",
        "ru": "каталог данных · {data}   chrome · {chrome}",
    },
    # ---------------------------------------------------------------- settings
    "settings.title": {"en": "Settings", "ru": "Настройки"},
    "settings.kicker": {"en": "SECTION 05", "ru": "РАЗДЕЛ 05"},
    "settings.runtime": {"en": "1 · Runtime", "ru": "1 · Среда выполнения"},
    "settings.runtime.text": {
        "en": "data dir        {data}\ndatabase        {db}\nchromium        {chrome}",
        "ru": "каталог данных  {data}\nбаза данных     {db}\nchromium        {chrome}",
    },
    "settings.runtime.auto": {
        "en": "auto (discovered at start)",
        "ru": "авто (определяется при запуске)",
    },
    "settings.safety": {"en": "2 · Safety", "ru": "2 · Безопасность"},
    "settings.confirm": {
        "en": "Confirm before destructive actions",
        "ru": "Подтверждать опасные действия",
    },
    "settings.confirm.tip": {
        "en": "When off, DELETE and REFRESH POOL run immediately",
        "ru": "Когда выключено, DELETE и REFRESH POOL выполняются сразу",
    },
    "settings.safety.hint": {
        "en": "Covers profile delete, configuration delete and proxy pool refresh.",
        "ru": "Касается удаления профиля, удаления конфигурации и обновления пула прокси.",
    },
    "settings.appearance": {"en": "3 · Appearance", "ru": "3 · Оформление"},
    "settings.theme.light": {"en": "Light · paper ledger", "ru": "Светлая · бумажный журнал"},
    "settings.theme.dark": {"en": "Dark · inverted ledger", "ru": "Тёмная · инвертированный журнал"},
    "settings.theme.tip": {
        "en": "Switch light / dark theme (T). Saved in gui.theme.",
        "ru": "Переключить светлую / тёмную тему (T). Сохраняется в gui.theme.",
    },
    "settings.accent.mono": {"en": "Mono · strict ledger", "ru": "Моно · строгий журнал"},
    "settings.accent.red": {"en": "Red accent", "ru": "Красный акцент"},
    "settings.accent.orange": {"en": "Orange accent", "ru": "Оранжевый акцент"},
    "settings.accent.yellow": {"en": "Yellow accent", "ru": "Жёлтый акцент"},
    "settings.accent.green": {"en": "Green accent", "ru": "Зелёный акцент"},
    "settings.accent.cyan": {"en": "Cyan accent", "ru": "Голубой акцент"},
    "settings.accent.blue": {"en": "Blue accent", "ru": "Синий акцент"},
    "settings.accent.purple": {"en": "Purple accent", "ru": "Фиолетовый акцент"},
    "settings.accent.pink": {"en": "Pink accent", "ru": "Розовый акцент"},
    "settings.accent.lime": {"en": "Lime accent", "ru": "Лаймовый акцент"},
    "settings.accent.tip": {
        "en": "Accent foreground: replaces the black/white ink, paper background stays. Saved in gui.accent.",
        "ru": "Акцентный цвет текста: заменяет чёрные/белые чернила, фон-бумага не меняется. Сохраняется в gui.accent.",
    },
    "settings.appearance.hint": {
        "en": "Background stays paper/ink · only the foreground accent changes.",
        "ru": "Фон остаётся бумага/чернила · меняется только акцент текста.",
    },
    "settings.toggle": {"en": "TOGGLE THEME (T)", "ru": "ПЕРЕКЛЮЧИТЬ ТЕМУ (T)"},
    "settings.toggle.tip": {
        "en": "Flip light / dark immediately",
        "ru": "Сразу переключить светлую / тёмную",
    },
    "settings.design": {
        "en": "design        ink on paper · 1px hairlines · one family, one weight",
        "ru": "дизайн        чернила на бумаге · линии 1px · один шрифт, одно начертание",
    },
    "settings.language": {"en": "4 · Language", "ru": "4 · Язык"},
    "settings.language.english": {"en": "English", "ru": "Английский"},
    "settings.language.russian": {"en": "Russian", "ru": "Русский"},
    "settings.language.tip": {
        "en": "Interface language (English / Russian). Saved in gui.language.",
        "ru": "Язык интерфейса (английский / русский). Сохраняется в gui.language.",
    },
    "settings.language.hint": {
        "en": "Applies instantly to menus, tabs, windows and errors.",
        "ru": "Применяется сразу к меню, вкладкам, окнам и ошибкам.",
    },
    "log.language": {
        "en": "Language switched to {lang}",
        "ru": "Язык переключён на {lang}",
    },
    "log.language.name.en": {"en": "English", "ru": "английский"},
    "log.language.name.ru": {"en": "Russian", "ru": "русский"},
    "log.theme": {"en": "Theme switched to {theme}", "ru": "Тема переключена на {theme}"},
    "log.theme.light": {"en": "light", "ru": "светлую"},
    "log.theme.dark": {"en": "dark", "ru": "тёмную"},
    "log.accent": {"en": "Accent switched to {accent}", "ru": "Акцент переключён на {accent}"},
    "log.confirm.on": {
        "en": "Destructive-action confirmations enabled",
        "ru": "Подтверждения опасных действий включены",
    },
    "log.confirm.off": {
        "en": "Destructive-action confirmations disabled",
        "ru": "Подтверждения опасных действий выключены",
    },
    # ---------------------------------------------------------------- profiles
    "profiles.title": {"en": "Profiles", "ru": "Профили"},
    "profiles.kicker": {"en": "SECTION 01", "ru": "РАЗДЕЛ 01"},
    "metric.total": {"en": "TOTAL", "ru": "ВСЕГО"},
    "metric.running": {"en": "RUNNING", "ru": "ЗАПУЩЕНО"},
    "metric.working": {"en": "WORKING", "ru": "РАБОЧИЕ"},
    "metric.dead": {"en": "DEAD", "ru": "МЁРТВЫЕ"},
    "profiles.new": {"en": "NEW", "ru": "НОВЫЙ"},
    "profiles.new.tip": {"en": "Create profile (Ctrl+N)", "ru": "Создать профиль (Ctrl+N)"},
    "profiles.duplicate": {"en": "DUPLICATE", "ru": "ДУБЛИРОВАТЬ"},
    "profiles.duplicate.tip": {
        "en": "Clone the selected profile with its browser state",
        "ru": "Клонировать выбранный профиль с его данными браузера",
    },
    "profiles.edit": {"en": "EDIT", "ru": "ИЗМЕНИТЬ"},
    "profiles.edit.tip": {
        "en": "Edit name / configuration / proxy (Enter)",
        "ru": "Изменить имя / конфигурацию / прокси (Enter)",
    },
    "profiles.delete": {"en": "DELETE", "ru": "УДАЛИТЬ"},
    "profiles.delete.tip": {
        "en": "Delete profile with its browser data (Del)",
        "ru": "Удалить профиль с его данными браузера (Del)",
    },
    "profiles.start": {"en": "START", "ru": "ЗАПУСК"},
    "profiles.start.tip": {
        "en": "Launch Chromium for the selected profile",
        "ru": "Запустить Chromium для выбранного профиля",
    },
    "profiles.stop": {"en": "STOP", "ru": "СТОП"},
    "profiles.stop.tip": {
        "en": "Stop the running Chromium process",
        "ru": "Остановить запущенный процесс Chromium",
    },
    "profiles.restart": {"en": "RESTART", "ru": "ПЕРЕЗАПУСК"},
    "profiles.restart.tip": {"en": "Stop and start again", "ru": "Остановить и запустить снова"},
    "profiles.list.tip": {
        "en": "Double-click a row to edit it",
        "ru": "Двойной клик по строке — редактировать",
    },
    "profiles.empty": {
        "en": "No profiles yet — press NEW to create the first one.",
        "ru": "Профилей пока нет — нажмите НОВЫЙ, чтобы создать первый.",
    },
    "profiles.hint": {
        "en": "Tip: double-click a row to edit · Enter edits · Del deletes.",
        "ru": "Подсказка: двойной клик — изменить · Enter — изменить · Del — удалить.",
    },
    "profiles.idle": {"en": "Idle.", "ru": "Готов."},
    "profiles.new.dialog": {"en": "New profile", "ru": "Новый профиль"},
    "profiles.new.name": {"en": "Name:", "ru": "Имя:"},
    "profiles.name.empty": {
        "en": "Name is empty — profile not created.",
        "ru": "Имя пустое — профиль не создан.",
    },
    "profiles.name.exists": {
        "en": "A profile named '{name}' already exists.",
        "ru": "Профиль с именем «{name}» уже существует.",
    },
    "profiles.creating": {
        "en": "Creating profile '{name}'…",
        "ru": "Создание профиля «{name}»…",
    },
    "profiles.created": {
        "en": "Profile #{id:03d} '{name}' created.",
        "ru": "Профиль #{id:03d} «{name}» создан.",
    },
    "profiles.loading": {"en": "Loading profile #{id:03d}…", "ru": "Загрузка профиля #{id:03d}…"},
    "profiles.edit.cancelled": {"en": "Edit cancelled.", "ru": "Редактирование отменено."},
    "profiles.no.changes": {"en": "No changes.", "ru": "Без изменений."},
    "profiles.saving": {"en": "Saving profile #{id:03d}…", "ru": "Сохранение профиля #{id:03d}…"},
    "profiles.updated": {
        "en": "Profile #{id:03d} updated.",
        "ru": "Профиль #{id:03d} обновлён.",
    },
    "profiles.duplicating": {
        "en": "Duplicating profile #{id:03d}…",
        "ru": "Дублирование профиля #{id:03d}…",
    },
    "profiles.duplicated": {
        "en": "Profile #{id:03d} '{name}' duplicated.",
        "ru": "Профиль #{id:03d} «{name}» дублирован.",
    },
    "profiles.delete.dialog": {"en": "Delete profile", "ru": "Удалить профиль"},
    "profiles.delete.question": {
        "en": "Delete profile #{id:03d} · {name} and its browser data?",
        "ru": "Удалить профиль #{id:03d} · {name} и его данные браузера?",
    },
    "profiles.deleting": {
        "en": "Deleting profile #{id:03d}…",
        "ru": "Удаление профиля #{id:03d}…",
    },
    "profiles.deleted": {
        "en": "Profile #{id:03d} · {name} deleted.",
        "ru": "Профиль #{id:03d} · {name} удалён.",
    },
    "profiles.actioning": {
        "en": "{action}ting profile {id}…",
        "ru": "{action} профиля {id}…",
    },
    "profiles.action.start": {"en": "Star", "ru": "Запуск"},
    "profiles.action.stop": {"en": "Stop", "ru": "Остановка"},
    "profiles.action.restart": {"en": "Restart", "ru": "Перезапуск"},
    "profiles.status": {
        "en": "Profile {id} · {status}",
        "ru": "Профиль {id} · {status}",
    },
    "profiles.status.running": {"en": "RUNNING", "ru": "ЗАПУЩЕН"},
    "profiles.status.stopped": {"en": "STOPPED", "ru": "ОСТАНОВЛЕН"},
    "profiles.row.edit.tip": {
        "en": "Double-click to edit {name}",
        "ru": "Двойной клик — изменить {name}",
    },
    "profiles.row.no.config": {"en": "—", "ru": "—"},
    "profiles.row.proxy": {"en": "proxy #{id}", "ru": "прокси #{id}"},
    "profiles.row.proxy.full": {
        "en": "proxy #{id} · {endpoint} · {location}",
        "ru": "прокси #{id} · {endpoint} · {location}",
    },
    "profiles.fix": {"en": "FIX", "ru": "ИСПРАВИТЬ"},
    "profiles.geo.aligning": {
        "en": "Aligning configuration #{id:03d} to {country}…",
        "ru": "Привязка конфигурации #{id:03d} к {country}…",
    },
    "profiles.geo.fixed": {
        "en": "Timezone auto-fixed to {tz} ({locale}). Start the profile again.",
        "ru": "Часовой пояс автоматически исправлен на {tz} ({locale}). Запустите профиль снова.",
    },
    "profiles.ver.regenerating": {
        "en": "Regenerating configuration #{id:03d} for Chrome/{major}…",
        "ru": "Перегенерация конфигурации #{id:03d} под Chrome/{major}…",
    },
    "profiles.ver.fixed": {
        "en": "Browser version auto-fixed to Chrome/{major}. Start the profile again.",
        "ru": "Версия браузера автоматически исправлена на Chrome/{major}. Запустите профиль снова.",
    },
    # ----------------------------------------------------------------- proxies
    "proxies.title": {"en": "Proxies", "ru": "Прокси"},
    "proxies.kicker": {"en": "SECTION 02", "ru": "РАЗДЕЛ 02"},
    "proxies.refresh": {"en": "REFRESH POOL", "ru": "ОБНОВИТЬ ПУЛ"},
    "proxies.refresh.tip": {
        "en": "Wipe the pool and check a fresh one (destructive)",
        "ru": "Очистить пул и проверить новый (опасное действие)",
    },
    "proxies.lookup": {"en": "LOOKUP IP", "ru": "УЗНАТЬ IP"},
    "proxies.lookup.tip": {
        "en": "Show the current public exit IP",
        "ru": "Показать текущий внешний IP",
    },
    "proxies.stop": {"en": "STOP", "ru": "СТОП"},
    "proxies.stop.tip": {"en": "Stop the running check", "ru": "Остановить текущую проверку"},
    "proxies.hint": {
        "en": "REFRESH POOL wipes stored proxies and re-checks them live. Dead ones are purged automatically.",
        "ru": "ОБНОВИТЬ ПУЛ стирает сохранённые прокси и проверяет новые вживую. Мёртвые удаляются автоматически.",
    },
    "proxies.idle": {"en": "Idle.", "ru": "Готов."},
    "proxies.refresh.dialog": {"en": "Refresh pool", "ru": "Обновить пул"},
    "proxies.refresh.question": {
        "en": "Wipe all stored proxies and check a fresh pool?",
        "ru": "Стереть все сохранённые прокси и проверить новый пул?",
    },
    "proxies.stopping": {"en": "Stopping…", "ru": "Остановка…"},
    "proxies.resolving": {"en": "Resolving public IP…", "ru": "Определение внешнего IP…"},
    "proxies.public.ip": {"en": "Public IP: {ip}", "ru": "Внешний IP: {ip}"},
    "proxies.public.fail": {
        "en": "Public IP could not be resolved.",
        "ru": "Не удалось определить внешний IP.",
    },
    "proxies.checked": {
        "en": "Checked {done} / {total}",
        "ru": "Проверено {done} / {total}",
    },
    "proxies.summary": {
        "en": "{prefix} {checked} · working {working} · failed {failed} · removed {removed}",
        "ru": "{prefix} {checked} · рабочие {working} · сбой {failed} · удалено {removed}",
    },
    "proxies.summary.checked": {"en": "Checked", "ru": "Проверено"},
    "proxies.summary.stopped": {"en": "Stopped", "ru": "Остановлено"},
    "proxies.summary.collected": {
        "en": " · collected {n}",
        "ru": " · собрано {n}",
    },
    "proxies.summary.elapsed": {"en": " ({s:.1f}s)", "ru": " ({s:.1f} с)"},
    "proxies.summary.sources": {
        "en": " · Sources failed: {errs}",
        "ru": " · Источники с ошибкой: {errs}",
    },
    "proxies.row.working": {"en": "WORKING", "ru": "РАБОЧИЙ"},
    "log.proxy.stopped": {
        "en": "Proxy check stopped by user",
        "ru": "Проверка прокси остановлена пользователем",
    },
    "log.proxy.resolved": {"en": "Public IP resolved", "ru": "Внешний IP определён"},
    "log.proxy.unresolved": {
        "en": "Public IP could not be resolved",
        "ru": "Не удалось определить внешний IP",
    },
    # ---------------------------------------------------------- configurations
    "configs.title": {"en": "Configurations", "ru": "Конфигурации"},
    "configs.kicker": {"en": "SECTION 03", "ru": "РАЗДЕЛ 03"},
    "configs.random": {"en": "random", "ru": "случайно"},
    "configs.template": {"en": "Template", "ru": "Шаблон"},
    "configs.platform": {"en": "Platform", "ru": "Платформа"},
    "configs.screen": {"en": "Screen", "ru": "Экран"},
    "configs.timezone": {"en": "Timezone", "ru": "Часовой пояс"},
    "configs.timezone.tip": {
        "en": "Pin the generated fingerprint to this timezone's country (timezone + locale + language are aligned, so the doctor stays green)",
        "ru": "Привязать генерируемый отпечаток к стране этого часового пояса (пояс + локаль + язык согласуются, проверка останется зелёной)",
    },
    "configs.generate": {"en": "GENERATE", "ru": "СГЕНЕРИРОВАТЬ"},
    "configs.generate.tip": {
        "en": "Generate a coherent fingerprint with the knobs on the left",
        "ru": "Сгенерировать согласованный отпечаток с параметрами слева",
    },
    "configs.new": {"en": "NEW CUSTOM", "ru": "НОВАЯ СВОЯ"},
    "configs.new.tip": {
        "en": "Create a custom configuration by hand (timezone picker included)",
        "ru": "Создать свою конфигурацию вручную (с выбором часового пояса)",
    },
    "configs.edit": {"en": "EDIT", "ru": "ИЗМЕНИТЬ"},
    "configs.edit.tip": {
        "en": "Edit the selected configuration",
        "ru": "Изменить выбранную конфигурацию",
    },
    "configs.delete": {"en": "DELETE", "ru": "УДАЛИТЬ"},
    "configs.delete.tip": {
        "en": "Delete the selected configuration",
        "ru": "Удалить выбранную конфигурацию",
    },
    "configs.hint": {
        "en": "Template = base fingerprint · Platform/Screen/Timezone = overrides (random = coherent pick). Timezone pins the whole geo trio, so the doctor stays green.",
        "ru": "Шаблон = базовый отпечаток · Платформа/Экран/Пояс = переопределения (случайно = согласованный выбор). Пояс фиксирует всё гео-трио, проверка останется зелёной.",
    },
    "configs.idle": {"en": "Idle.", "ru": "Готов."},
    "configs.generating": {
        "en": "Generating a coherent fingerprint…",
        "ru": "Генерация согласованного отпечатка…",
    },
    "configs.creating": {
        "en": "Creating configuration {name!r}…",
        "ru": "Создание конфигурации {name!r}…",
    },
    "configs.created": {
        "en": "Created #{id} · {name} · {tz}",
        "ru": "Создана #{id} · {name} · {tz}",
    },
    "configs.no.timezone": {"en": "no timezone", "ru": "без пояса"},
    "configs.loading": {
        "en": "Loading configuration #{id:03d}…",
        "ru": "Загрузка конфигурации #{id:03d}…",
    },
    "configs.edit.cancelled": {"en": "Edit cancelled.", "ru": "Редактирование отменено."},
    "configs.saving": {
        "en": "Saving configuration #{id:03d}…",
        "ru": "Сохранение конфигурации #{id:03d}…",
    },
    "configs.updated": {
        "en": "Updated #{id} · {name} · {tz}",
        "ru": "Обновлена #{id} · {name} · {tz}",
    },
    "configs.delete.dialog": {
        "en": "Delete configuration",
        "ru": "Удалить конфигурацию",
    },
    "configs.delete.question": {
        "en": "Delete configuration #{id}?",
        "ru": "Удалить конфигурацию #{id}?",
    },
    "configs.deleting": {
        "en": "Deleting configuration #{id:03d}…",
        "ru": "Удаление конфигурации #{id:03d}…",
    },
    "configs.deleted": {
        "en": "Configuration #{id:03d} deleted.",
        "ru": "Конфигурация #{id:03d} удалена.",
    },
    "configs.generated": {
        "en": "Created #{id} · {name} · {platform} · {w}×{h} · {lang} · {tz}",
        "ru": "Создана #{id} · {name} · {platform} · {w}×{h} · {lang} · {tz}",
    },
    "configs.no.platform": {"en": "—", "ru": "—"},
    "configs.no.lang": {"en": "—", "ru": "—"},
    # --------------------------------------------------------------------- log
    "logs.title": {"en": "Log", "ru": "Журнал"},
    "logs.kicker": {"en": "LIVE SESSION LOG", "ru": "ЖУРНАЛ СЕССИИ · ВЖИВУЮ"},
    "logs.entries": {
        "en": "{n} entries · last id {last}",
        "ru": "{n} записей · последний id {last}",
    },
    "logs.export": {"en": "EXPORT", "ru": "ЭКСПОРТ"},
    "logs.export.tip": {
        "en": "Write the whole session to a UTF-8 text file",
        "ru": "Записать всю сессию в текстовый файл UTF-8",
    },
    "logs.clear": {"en": "CLEAR", "ru": "ОЧИСТИТЬ"},
    "logs.clear.tip": {"en": "Wipe the current session's rows", "ru": "Стереть строки текущей сессии"},
    "logs.pause": {"en": "PAUSE", "ru": "ПАУЗА"},
    "logs.resume": {"en": "RESUME", "ru": "ПРОДОЛЖИТЬ"},
    "logs.pause.tip": {"en": "Pause live polling", "ru": "Приостановить живое обновление"},
    "logs.ready": {"en": "Ready.", "ru": "Готов."},
    "logs.poll.fail": {"en": "Log poll failed: {err}", "ru": "Ошибка чтения журнала: {err}"},
    "logs.export.dialog": {"en": "Export log", "ru": "Экспорт журнала"},
    "logs.exporting": {"en": "Exporting…", "ru": "Экспорт…"},
    "logs.export.fail": {"en": "Export failed: {err}", "ru": "Ошибка экспорта: {err}"},
    "logs.exported": {
        "en": "Exported {n} rows → {path}",
        "ru": "Экспортировано {n} строк → {path}",
    },
    "logs.clearing": {"en": "Clearing log…", "ru": "Очистка журнала…"},
    "logs.clear.fail": {"en": "Clear failed: {err}", "ru": "Ошибка очистки: {err}"},
    "logs.cleared": {"en": "Cleared {n} entries.", "ru": "Очищено записей: {n}."},
    "log.exported": {"en": "Log exported", "ru": "Журнал экспортирован"},
    "log.cleared": {"en": "Log cleared", "ru": "Журнал очищен"},
    "log.app.started": {"en": "Application started", "ru": "Приложение запущено"},
    "log.app.exiting": {"en": "Application exiting", "ru": "Приложение завершается"},
    "log.session.started": {"en": "Log session started", "ru": "Сессия журнала начата"},
    # ----------------------------------------------------------------- dialogs
    "error.unexpected": {
        "en": "The operation failed unexpectedly.",
        "ru": "Операция завершилась с непредвиденной ошибкой.",
    },
    "error.details": {"en": "Details", "ru": "Подробности"},
    "dlg.profile.title": {"en": "Edit profile · {name}", "ru": "Изменить профиль · {name}"},
    "dlg.profile.header": {"en": "Edit #{id:03d} · {name}", "ru": "Изменение #{id:03d} · {name}"},
    "dlg.profile.subtitle": {
        "en": "Only changed fields are saved — the rest stays untouched.",
        "ru": "Сохраняются только изменённые поля — остальное не трогается.",
    },
    "dlg.group.identity": {"en": "1 · Identity", "ru": "1 · Имя"},
    "dlg.name": {"en": "Name *", "ru": "Имя *"},
    "dlg.profile.name.ph": {
        "en": "e.g. shop-01 · minimum 1 character",
        "ru": "напр. shop-01 · минимум 1 символ",
    },
    "dlg.profile.name.tip": {
        "en": "Profile name — shown in the list and used for the data dir.",
        "ru": "Имя профиля — видно в списке и используется для каталога данных.",
    },
    "dlg.name.empty": {
        "en": "Name cannot be empty — give the profile a name.",
        "ru": "Имя не может быть пустым — дайте профилю имя.",
    },
    "dlg.group.fingerprint": {"en": "2 · Fingerprint", "ru": "2 · Отпечаток"},
    "dlg.config.tip": {
        "en": "Browser fingerprint (OS, screen, locale). Generate new ones on the Configurations tab.",
        "ru": "Отпечаток браузера (ОС, экран, локаль). Новые создаются на вкладке Конфигурации.",
    },
    "dlg.configuration": {"en": "Configuration", "ru": "Конфигурация"},
    "dlg.config.hint": {
        "en": "{n} stored · change applies on next launch",
        "ru": "{n} сохранено · изменение применится при следующем запуске",
    },
    "dlg.group.network": {"en": "3 · Network", "ru": "3 · Сеть"},
    "dlg.proxy.tip": {
        "en": "Only WORKING proxies are offered. A dead assignment stays visible but locked so you never clear it by accident.",
        "ru": "Предлагаются только РАБОЧИЕ прокси. Мёртвое назначение остаётся видимым, но заблокированным, чтобы не сбросить его случайно.",
    },
    "dlg.proxy": {"en": "Proxy", "ru": "Прокси"},
    "dlg.proxy.hint": {
        "en": "working-only list · dead assignment is kept locked",
        "ru": "только рабочие · мёртвое назначение заблокировано",
    },
    "dlg.proxy.none": {"en": "— no proxy —", "ru": "— без прокси —"},
    "dlg.proxy.dead": {"en": "dead", "ru": "мёртвый"},
    "dlg.proxy.assigned": {"en": "(assigned)", "ru": "(назначен)"},
    "dlg.save.tip": {
        "en": "Save only the fields you changed (Enter)",
        "ru": "Сохранить только изменённые поля (Enter)",
    },
    "dlg.config.new.title": {
        "en": "New custom configuration",
        "ru": "Новая своя конфигурация",
    },
    "dlg.config.edit.title": {
        "en": "Edit configuration · {name}",
        "ru": "Изменить конфигурацию · {name}",
    },
    "dlg.config.new.header": {
        "en": "New custom fingerprint",
        "ru": "Новый свой отпечаток",
    },
    "dlg.config.edit.header": {
        "en": "Edit #{id:03d} · {name}",
        "ru": "Изменение #{id:03d} · {name}",
    },
    "dlg.config.subtitle": {
        "en": "Only valid timezones are offered — the doctor maps each of them to an exit country.",
        "ru": "Предлагаются только корректные часовые пояса — проверка сопоставляет каждый со страной выхода.",
    },
    "dlg.config.name.ph": {
        "en": "e.g. shop-de-01 · minimum 1 character",
        "ru": "напр. shop-de-01 · минимум 1 символ",
    },
    "dlg.config.name.tip": {
        "en": "Configuration name — must be unique.",
        "ru": "Имя конфигурации — должно быть уникальным.",
    },
    "dlg.config.name.empty": {
        "en": "Name cannot be empty — give the configuration a name.",
        "ru": "Имя не может быть пустым — дайте конфигурации имя.",
    },
    "dlg.platform": {"en": "Platform", "ru": "Платформа"},
    "dlg.platform.tip": {
        "en": "OS the fingerprint pretends to run on.",
        "ru": "ОС, под которую маскируется отпечаток.",
    },
    "dlg.language": {"en": "Language", "ru": "Язык"},
    "dlg.language.tip": {
        "en": "Browser language — your own choice, never auto-changed. Pick from the pool or type any custom tag.",
        "ru": "Язык браузера — ваш собственный выбор, никогда не меняется сам. Выберите из списка или введите свой тег.",
    },
    "dlg.locale": {"en": "Locale", "ru": "Локаль"},
    "dlg.locale.ph": {"en": "e.g. en-US, de-DE", "ru": "напр. en-US, de-DE, ru-RU"},
    "dlg.locale.tip": {
        "en": "Locale tag with region — should match the timezone country.",
        "ru": "Тег локали с регионом — должен совпадать со страной часового пояса.",
    },
    "dlg.timezone": {"en": "Timezone", "ru": "Часовой пояс"},
    "dlg.timezone.tip": {
        "en": "IANA timezone. Only zones the app can map to a country are listed.",
        "ru": "Часовой пояс IANA. Перечислены только пояса, которые приложение может сопоставить со страной.",
    },
    "dlg.geo.hint": {
        "en": "Timezone ↔ locale sync automatically · language is always yours.",
        "ru": "Пояс ↔ локаль синхронизируются автоматически · язык всегда ваш.",
    },
    "dlg.group.screen": {"en": "3 · Screen (optional)", "ru": "3 · Экран (необязательно)"},
    "dlg.width": {"en": "Width", "ru": "Ширина"},
    "dlg.width.tip": {
        "en": "Screen width in pixels (0 = leave unset).",
        "ru": "Ширина экрана в пикселях (0 = не задана).",
    },
    "dlg.height": {"en": "Height", "ru": "Высота"},
    "dlg.height.tip": {
        "en": "Screen height in pixels (0 = leave unset).",
        "ru": "Высота экрана в пикселях (0 = не задана).",
    },
    "dlg.screen.hint": {
        "en": "Width and height must be set together or both left unset.",
        "ru": "Ширина и высота задаются вместе либо обе остаются пустыми.",
    },
    # ------------------------------------------------------------------ splash
    "splash.init": {"en": "Initializing…", "ru": "Инициализация…"},
    "splash.core": {"en": "Core…", "ru": "Ядро…"},
    "splash.profiles": {"en": "Profiles…", "ru": "Профили…"},
    "splash.proxies": {"en": "Proxies…", "ru": "Прокси…"},
    "splash.chromium": {"en": "Chromium…", "ru": "Chromium…"},
    "splash.ui": {"en": "Interface…", "ru": "Интерфейс…"},
    "splash.done": {"en": "Done", "ru": "Готово"},
    # ------------------------------------------------------------------ errors
    "err.profile.notfound": {
        "en": "Profile with id={id} does not exist.",
        "ru": "Профиль с id={id} не существует.",
    },
    "err.profile.exists": {
        "en": "A profile named {name!r} already exists.",
        "ru": "Профиль с именем {name!r} уже существует.",
    },
    "err.profile.running": {
        "en": "Profile with id={id} is already running (pid={pid}).",
        "ru": "Профиль с id={id} уже запущен (pid={pid}).",
    },
    "err.profile.notrunning": {
        "en": "Profile with id={id} is not running.",
        "ru": "Профиль с id={id} не запущен.",
    },
    "err.profile.noconfig": {
        "en": "Profile with id={id} has no browser configuration assigned. Assign one with: app profile update <id> --configuration-id <cfg>",
        "ru": "Профилю с id={id} не назначена конфигурация браузера. Назначьте: app profile update <id> --configuration-id <cfg>",
    },
    "err.config.notfound": {
        "en": "Browser configuration with id={id} does not exist.",
        "ru": "Конфигурация браузера с id={id} не существует.",
    },
    "err.config.invalid": {
        "en": "Invalid browser configuration: {msg}",
        "ru": "Некорректная конфигурация браузера: {msg}",
    },
    "err.chromium.notfound": {
        "en": "Could not locate a Chromium-based browser executable. Set ANTIDETECT_CHROMIUM_PATH or add one of the known install paths.",
        "ru": "Не найден исполняемый файл Chromium-браузера. Задайте ANTIDETECT_CHROMIUM_PATH или добавьте один из известных путей установки.",
    },
    "err.proxy.notfound": {
        "en": "Proxy with id={id} does not exist.",
        "ru": "Прокси с id={id} не существует.",
    },
    "err.proxy.unusable": {
        "en": "Proxy with id={id} is not usable: {detail}",
        "ru": "Прокси с id={id} нельзя использовать: {detail}",
    },
    "err.proxy.source": {
        "en": "Proxy source {source!r} failed: {detail}",
        "ru": "Источник прокси {source!r} дал сбой: {detail}",
    },
    "err.cookie.nocookies": {
        "en": "Profile {id} has no cookies: {detail}",
        "ru": "У профиля {id} нет cookies: {detail}",
    },
}
