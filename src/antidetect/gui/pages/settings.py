"""Settings: appearance, browser, behaviour, data — grouped cards, no tabs to hunt through."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from antidetect import __version__
from antidetect.gui import workers
from antidetect.gui.components import (
    Button,
    PageHeader,
    Segmented,
    SettingGroup,
    SettingRow,
    Switch,
    label,
    set_role,
)
from antidetect.gui.metrics import CONTENT_MAX_WIDTH, PAGE_MARGINS
from antidetect.gui.preferences import Preferences
from antidetect.gui.theme import current_theme
from antidetect.gui.resources import APP_MARK_PATH
from antidetect.i18n import get_language, tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost
    from antidetect.gui.workers import TaskRunner

TAB_GENERAL, TAB_CHECK, TAB_LOGS = "general", "check", "logs"



_Row = SettingRow
_Group = SettingGroup


class SettingsPage(QWidget):
    themeChanged = Signal(str)       # "light" | "dark" | "system"
    languageChanged = Signal(str)    # "en" | "ru"
    browserChanged = Signal()
    browserDownloadRequested = Signal()    # "Download / Update Chrome": the window runs the dialog
    profilesChanged = Signal()       # the fingerprint check started or stopped a profile

    def __init__(self, container: "Container", runner: "TaskRunner", toasts: "ToastHost",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = runner
        self._toasts = toasts
        self._prefs = Preferences(container.settings)
        self._subpages: dict[str, QWidget] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QWidget()
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(PAGE_MARGINS[0], PAGE_MARGINS[1], PAGE_MARGINS[2], 14)
        self._header = PageHeader(tr("settings.title"))
        self._tabs = Segmented(self._tab_options(), TAB_GENERAL)
        self._header.actions.addWidget(self._tabs)
        head_layout.addWidget(self._header)
        outer.addWidget(head)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)
        self._tabs.changed.connect(self._show_tab)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._stack.addWidget(scroll)
        self._subpages[TAB_GENERAL] = scroll
        body = QWidget()
        scroll.setWidget(body)
        holder = QHBoxLayout(body)
        holder.setContentsMargins(PAGE_MARGINS[0], 0, PAGE_MARGINS[2], 20)
        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        holder.addWidget(column, 1)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(24)

        # ---- appearance
        self._g_appearance = _Group(tr("settings.appearance"))
        self._theme = Segmented(self._theme_options(), current_theme())
        self._lang = Segmented([("en", "English"), ("ru", "Русский")], get_language())
        self._r_theme = _Row(tr("settings.theme"), tr("settings.theme.desc"), self._theme)
        self._r_lang = _Row(tr("settings.language"), tr("settings.language.desc"), self._lang)
        self._g_appearance.add(self._r_theme)
        self._g_appearance.add(self._r_lang)
        col.addWidget(self._g_appearance)
        self._theme.changed.connect(self.themeChanged)
        self._lang.changed.connect(self.languageChanged)

        # ---- browser
        self._g_browser = _Group(tr("settings.browser"))
        self._download = Button(tr("settings.browser.download"), None, icon="download", size="sm")
        self._download.clicked.connect(self.browserDownloadRequested)
        self._choose = Button(tr("common.choose"), None, icon="folder", size="sm")
        self._choose.clicked.connect(self._choose_browser)
        self._auto = Button(tr("settings.browser.auto"), None, icon="refresh", size="sm")
        self._auto.clicked.connect(self._auto_browser)
        self._r_browser = _Row(tr("settings.browser.name"), "", self._download, self._choose, self._auto, stacked=True)
        self._r_browser.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._g_browser.add(self._r_browser)
        col.addWidget(self._g_browser)
        self._browser_note = label(tr("settings.browser.note"), "small", wrap=True)
        col.addWidget(self._browser_note)

        # ---- behaviour
        self._g_behavior = _Group(tr("settings.behavior"))
        self._confirm = Switch(self._prefs.get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, default=True))
        self._confirm.toggled.connect(lambda v: self._prefs.set_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, v))
        self._r_confirm = _Row(tr("settings.confirm"), tr("settings.confirm.desc"), self._confirm)
        self._g_behavior.add(self._r_confirm)
        col.addWidget(self._g_behavior)

        # ---- data
        self._g_data = _Group(tr("settings.data"))
        self._open_data = Button(tr("common.open"), None, icon="folder", size="sm")
        self._open_data.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(container.config.data_dir)))
        )
        self._r_data = _Row(tr("settings.data.folder"), str(container.config.data_dir), self._open_data)
        self._r_data.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._g_data.add(self._r_data)
        col.addWidget(self._g_data)

        # ---- about
        self._g_about = _Group(tr("settings.about"))
        about = QWidget()
        about_row = QHBoxLayout(about)
        about_row.setContentsMargins(20, 16, 20, 16)
        about_row.setSpacing(14)
        mark = QLabel()
        pixmap = QPixmap(str(APP_MARK_PATH))
        if not pixmap.isNull():
            mark.setPixmap(pixmap)
            mark.setFixedSize(44, 44)
            mark.setScaledContents(True)
        about_row.addWidget(mark)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(f"{tr('app.title')}  ·  {tr('settings.version', version=__version__)}", "h3"))
        self._about_text = label(tr("settings.about.text"), "small", wrap=True)
        texts.addWidget(self._about_text)
        about_row.addLayout(texts, 1)
        self._g_about.add(about)
        col.addWidget(self._g_about)
        col.addStretch(1)

    def _tab_options(self) -> list[tuple[str, str]]:
        return [(TAB_GENERAL, tr("settings.tab.general")), (TAB_CHECK, tr("settings.tab.check")),
                (TAB_LOGS, tr("settings.tab.logs"))]

    # ------------------------------------------------------------------ tabs
    def _show_tab(self, key: str) -> None:
        """The fingerprint check and the technical log live here; they are built when first opened."""
        page = self._subpages.get(key)
        if page is None:
            if key == TAB_CHECK:
                from antidetect.gui.pages.check import CheckPage

                page = CheckPage(self._container, self._runner, self._toasts, self, embedded=True)
                page.profilesChanged.connect(self.profilesChanged)
            else:
                from antidetect.gui.pages.logs import LogsPage

                page = LogsPage(self._container, self._runner, self._toasts, self, embedded=True)
            self._subpages[key] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def show_tab(self, key: str) -> None:
        self._tabs.set_value(key)
        self._show_tab(key)

    def _theme_options(self) -> list[tuple[str, str]]:
        return [("system", tr("theme.system")), ("light", tr("theme.light")), ("dark", tr("theme.dark"))]

    # ------------------------------------------------------------------ appearance
    def sync_theme(self, requested: str) -> None:
        self._theme.set_value(requested)

    # ------------------------------------------------------------------ browser
    def show_browser(self, info) -> None:
        path, version = info
        if path is None:
            self._r_browser.description.setText(tr("settings.browser.missing"))
            set_role(self._r_browser.description, "danger")
        else:
            source = self._container.browser.browser_source()
            text = tr("settings.browser.found", path=str(path))
            if version:
                text += "  ·  " + tr("settings.browser.version", version=version)
            if source in ("managed", "configured", "auto"):
                text = tr(f"settings.browser.source.{source}") + "  ·  " + text
            self._r_browser.description.setText(text)
            set_role(self._r_browser.description, "small")
        has_download = bool(self._container.browsers.status_downloaded())
        self._download.setText(tr("settings.browser.update" if has_download else "settings.browser.download"))

    def _choose_browser(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window(), tr("dlg.choose.browser"))
        if path:
            self._container.set_browser_path(path)
            self.browserChanged.emit()

    def _auto_browser(self) -> None:
        self._container.set_browser_path(None)
        self.browserChanged.emit()

    # ------------------------------------------------------------------ i18n
    def retranslate(self) -> None:
        self._header.title.setText(tr("settings.title"))
        for key, text in self._tab_options():
            self._tabs.set_text(key, text)
        for page in self._subpages.values():
            if hasattr(page, "retranslate"):
                page.retranslate()
        self._g_appearance.set_title(tr("settings.appearance"))
        self._g_browser.set_title(tr("settings.browser"))
        self._g_behavior.set_title(tr("settings.behavior"))
        self._g_data.set_title(tr("settings.data"))
        self._g_about.set_title(tr("settings.about"))
        self._r_theme.set_texts(tr("settings.theme"), tr("settings.theme.desc"))
        self._r_lang.set_texts(tr("settings.language"), tr("settings.language.desc"))
        for key, text in self._theme_options():
            self._theme.set_text(key, text)
        self._download.setText(tr("settings.browser.update" if self._container.browsers.status_downloaded()
                                  else "settings.browser.download"))
        self._choose.setText(tr("common.choose"))
        self._auto.setText(tr("settings.browser.auto"))
        self._r_browser.title.setText(tr("settings.browser.name"))
        self._browser_note.setText(tr("settings.browser.note"))
        self._r_confirm.set_texts(tr("settings.confirm"), tr("settings.confirm.desc"))
        self._r_data.title.setText(tr("settings.data.folder"))
        self._open_data.setText(tr("common.open"))
        self._about_text.setText(tr("settings.about.text"))
        self._runner.submit(
            workers.tasks.browser_info(self._container),
            on_result=self.show_browser,
            on_error=lambda _e: None,
        )
