"""The main window: sidebar navigation + lazily built pages + toasts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from antidetect.api import ApiSettings
from antidetect.gui import platform as native
from antidetect.gui import workers
from antidetect.gui.catalog import Catalog
from antidetect.gui.components import StyledMenu, ToastHost, confirm
from antidetect.gui.components.palette import CommandPalette, Entry
from antidetect.gui.errors import friendly_error_text
from antidetect.gui.menubar import AppMenu
from antidetect.gui.preferences import Preferences
from antidetect.gui.sidebar import (
    SECTION_ACTIVITY,
    SECTION_API,
    SECTION_PROFILES,
    SECTION_PROXIES,
    SECTION_SETTINGS,
    SECTION_TRASH,
    SECTIONS,
    Sidebar,
)
from antidetect.gui.theme import apply_theme, bus, current_theme, resolve_theme
from antidetect.gui.theme import icons as ic
from antidetect.gui.theme.tags import slot_color
from antidetect.gui.resources import APP_ICON_PATH
from antidetect.gui.workers import TaskRunner
from antidetect.i18n import get_language, set_language, tr

if TYPE_CHECKING:
    from antidetect.api import ApiManager
    from antidetect.container import Container

WINDOW_SIZE = (1360, 840)
WINDOW_MIN_SIZE = (1040, 660)


class Sheet(QFrame):
    """The white page floating on the grey canvas; its top edge doubles as the window's drag handle."""

    DRAG_HEIGHT = 60

    def __init__(self, draggable: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sheet")
        self._draggable = draggable

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._draggable and event.button() == Qt.MouseButton.LeftButton and event.position().y() < self.DRAG_HEIGHT:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._draggable and event.position().y() < self.DRAG_HEIGHT:
            window = self.window()
            window.showNormal() if window.isMaximized() else window.showMaximized()
            return
        super().mouseDoubleClickEvent(event)


class _ApiBridge(QObject):
    """The API server runs on its own threads; this carries "something changed" to the GUI thread."""

    changed = Signal()


class MainWindow(QMainWindow):
    def __init__(self, container: "Container", parent: QWidget | None = None, *, defer_first_page: bool = False,
                 prewarm: bool = False) -> None:
        super().__init__(parent)
        self._container = container
        self._runner = TaskRunner(self, error_sink=container.logs)
        self._prefs = Preferences(container.settings)
        self._catalog = Catalog(container, self._runner, self)
        self._closing = False
        self._browser_info: tuple = (None, None)
        self._api: "ApiManager | None" = None
        self._api_bridge = _ApiBridge(self)
        self._api_refresh = QTimer(self)               # many calls in a row refresh the tables once
        self._api_refresh.setSingleShot(True)
        self._api_refresh.setInterval(200)
        self._api_refresh.timeout.connect(self._refresh_after_api)
        self._api_bridge.changed.connect(self._api_refresh.start, Qt.ConnectionType.QueuedConnection)

        try:
            set_language(self._prefs.get_language(get_language()))
        except Exception:
            pass

        self.setWindowTitle(tr("app.title"))
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(*WINDOW_MIN_SIZE)

        inset = native.expand_into_titlebar(self)    # macOS: the sidebar runs up under the traffic lights
        central = QWidget()
        central.setObjectName("Canvas")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._sidebar = Sidebar(top_inset=inset)
        self._sheet = Sheet(draggable=bool(inset))
        sheet_layout = QVBoxLayout(self._sheet)
        sheet_layout.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        sheet_layout.addWidget(self._stack)
        self._toasts = ToastHost(central)
        layout.addWidget(self._sidebar)
        layout.addWidget(self._sheet, 1)
        layout.setContentsMargins(0, 10, 10, 10)
        self.setCentralWidget(central)
        self._prewarm_left: list[str] = []
        self._titlebar_done = False
        self._focus_set = False

        # Pages are built the first time they are opened: start-up only pays for Profiles.
        self._pages: dict[str, QWidget] = {}
        self._factories: dict[str, Callable[[], QWidget]] = {
            SECTION_PROFILES: self._make_profiles,
            SECTION_PROXIES: self._make_proxies,
            SECTION_ACTIVITY: self._make_activity,
            SECTION_API: self._make_api,
            SECTION_TRASH: self._make_trash,
            SECTION_SETTINGS: self._make_settings,
        }

        self._sidebar.sectionRequested.connect(self._on_nav)
        self._sidebar.themeToggleRequested.connect(self.toggle_theme)
        self._sidebar.tagRequested.connect(self.show_tag)
        self._sidebar.tagsFolded.connect(lambda folded: self._prefs.set_bool(Preferences.KEY_TAGS_COLLAPSED, folded))
        self._sidebar.fold_tags(self._prefs.get_bool(Preferences.KEY_TAGS_COLLAPSED, default=False))
        self._sidebar.workspaceRequested.connect(self.show_workspace)
        self._sidebar.workspacesFolded.connect(
            lambda folded: self._prefs.set_bool(Preferences.KEY_WORKSPACES_COLLAPSED, folded))
        self._sidebar.fold_workspaces(self._prefs.get_bool(Preferences.KEY_WORKSPACES_COLLAPSED, default=False))
        self._sidebar.newWorkspaceRequested.connect(self.new_workspace)
        self._sidebar.workspaceMenuRequested.connect(self._workspace_menu)
        self._sidebar.newTagRequested.connect(self.new_tag)
        self._sidebar.manageTagsRequested.connect(self.manage_tags)
        self._sidebar.tagMenuRequested.connect(self._tag_menu)
        self._catalog.changed.connect(self._on_catalog)
        self._catalog.profilesAffected.connect(self._reload_profiles)
        bus.changed.connect(self._sidebar.update)
        app = QApplication.instance()
        if app is not None:
            try:
                app.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
            except Exception:
                pass
        self._sidebar.set_theme_state(self._resolved())
        self._sidebar.set_count(SECTION_API, ApiSettings(container.settings).key_count())
        if defer_first_page:
            # Qt's first text field alone costs ~100 ms: paint the frame now, fill the page next turn.
            QTimer.singleShot(0, lambda: self.show_section(SECTION_PROFILES))
        else:
            self.show_section(SECTION_PROFILES)
        self._register_shortcuts()
        self._prefs.load_geometry(self)
        self.refresh_browser()
        if self._prefs.get_bool("api.enabled"):
            QTimer.singleShot(0, self._start_api)      # switched on last time: listen again, once the window is up
        self._catalog.refresh()
        QTimer.singleShot(1500, self._housekeeping)
        self._catalog_timer = QTimer(self)               # counters that other things change: the feed, a script's profiles
        self._catalog_timer.setInterval(20_000)
        self._catalog_timer.timeout.connect(self._poll_catalog)
        self._catalog_timer.start()
        if prewarm:
            # Build the other pages in idle time, one per turn, so that opening them later is instant.
            self._prewarm_left = [SECTION_PROXIES, SECTION_ACTIVITY, SECTION_API, SECTION_TRASH, SECTION_SETTINGS]
            QTimer.singleShot(350, self._prewarm_next)

    def _prewarm_next(self) -> None:
        if self._closing or not self._prewarm_left:
            return
        self.page(self._prewarm_left.pop(0))
        if self._prewarm_left:
            QTimer.singleShot(120, self._prewarm_next)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and not self._focus_set:
            self._focus_set = True
            # Qt hands the first text field the cursor when the window activates: take it back, once
            QTimer.singleShot(0, self._initial_focus)

    def _initial_focus(self) -> None:
        if self._closing:
            return
        try:
            page = self._stack.currentWidget()
        except RuntimeError:              # the window was deleted before this deferred call ran
            return
        if hasattr(page, "focus_primary"):
            page.focus_primary()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._titlebar_done:
            self._titlebar_done = True
            native.finish_titlebar(self)
            handle = self.windowHandle()
            if handle is not None:
                handle.screenChanged.connect(lambda *_: self._sync_pixel_ratio())
        self._sync_pixel_ratio()

    def _sync_pixel_ratio(self) -> None:
        """Icons are rendered for the pixel ratio of the screen the window is on (crisp on 1x as well as Retina)."""
        if ic.set_device_ratio(self.devicePixelRatioF()):
            bus.changed.emit()

    # ------------------------------------------------------------ page factories
    def _make_profiles(self) -> QWidget:
        from antidetect.gui.pages.profiles import ProfilesPage

        page = ProfilesPage(self._container, self._runner, self._toasts, self._catalog, self)
        page.runningChanged.connect(lambda n: self._sidebar.set_running(SECTION_PROFILES, n))
        page.countsChanged.connect(lambda total: self._sidebar.set_count(SECTION_PROFILES, total))
        page.tagChanged.connect(self._sidebar.set_active_tag)
        page.workspaceChanged.connect(self._sidebar.set_active_workspace)
        page.browserChanged.connect(self.refresh_browser)
        page.browserDownloadRequested.connect(self.download_browser)
        page.trashChanged.connect(self._on_trash_changed)
        return page

    def _make_proxies(self) -> QWidget:
        from antidetect.gui.pages.proxies import ProxiesPage

        page = ProxiesPage(self._container, self._runner, self._toasts, self)
        page.countChanged.connect(lambda total: self._sidebar.set_count(SECTION_PROXIES, total))
        return page

    def _make_activity(self) -> QWidget:
        from antidetect.gui.pages.activity import ActivityPage

        page = ActivityPage(self._container, self._runner, self._toasts, self._catalog, self)
        return page

    def _make_trash(self) -> QWidget:
        from antidetect.gui.pages.trash import TrashPage

        page = TrashPage(self._container, self._runner, self._toasts, self._catalog, self)
        page.changed.connect(self._on_trash_changed)
        return page

    def _make_api(self) -> QWidget:
        from antidetect.gui.pages.api import ApiPage

        page = ApiPage(self._container, self._toasts, lambda: self.api, self)
        page.countChanged.connect(lambda n: self._sidebar.set_count(SECTION_API, n))
        return page

    def _make_settings(self) -> QWidget:
        from antidetect.gui.pages.settings import SettingsPage

        page = SettingsPage(self._container, self._runner, self._toasts, self)
        page.themeChanged.connect(self.set_theme)
        page.languageChanged.connect(self.set_language)
        page.browserChanged.connect(self.refresh_browser)
        page.browserDownloadRequested.connect(self.download_browser)
        page.profilesChanged.connect(self._reload_profiles)
        page.show_browser(self._browser_info)
        return page

    def _reload_profiles(self) -> None:
        page = self._pages.get(SECTION_PROFILES)
        if page is not None:
            page.reload()                                         # type: ignore[attr-defined]

    def _on_trash_changed(self) -> None:
        """Something went to the trash or came back: both lists and the counters must agree."""
        self._catalog.refresh()
        for key in (SECTION_PROFILES, SECTION_TRASH):
            page = self._pages.get(key)
            if page is not None and key != self.current_section():
                page.reload()                                     # type: ignore[attr-defined]

    def _on_catalog(self) -> None:
        catalog = self._catalog
        self._sidebar.set_workspaces(catalog.workspaces, catalog.unassigned)
        self._sidebar.set_tags(catalog.tags)
        self._sidebar.set_count(SECTION_TRASH, catalog.trash)
        looking = self.current_section() == SECTION_ACTIVITY
        # new entries are a quiet number; a failure (a profile that did not start) is a red chip
        self._sidebar.set_count(SECTION_ACTIVITY, 0 if looking else catalog.unseen)
        self._sidebar.set_badge(SECTION_ACTIVITY, 0 if looking else catalog.unseen_errors)

    def _poll_catalog(self) -> None:
        if not self._closing and self.isActiveWindow():
            self._catalog.refresh()

    def _housekeeping(self) -> None:
        """After start-up: profiles that have been in the trash longer than the retention period go for good."""
        if self._closing:
            return
        self._runner.submit(
            workers.tasks.purge_expired_trash(self._container),
            on_result=lambda removed: self._catalog.refresh() if removed else None,
            on_error=lambda _exc: None,
        )

    # ------------------------------------------------------------------ automation api
    @property
    def api(self) -> "ApiManager":
        """The API server's manager, created (and its code loaded) the first time it is needed."""
        if self._api is None:
            from antidetect.api import ApiManager

            self._api = ApiManager(self._container, on_change=self._api_bridge.changed.emit)
        return self._api

    def _start_api(self) -> None:
        if self._closing:
            return
        self.api.apply()
        if self.api.error is not None:
            self._toasts.show_message(tr("api.toast.failed", error=self._api_error_text()), kind="error")
        page = self._pages.get(SECTION_API)
        if page is not None:
            page.refresh()                                            # type: ignore[attr-defined]

    def _api_error_text(self) -> str:
        error = self.api.error
        if error is None:
            return ""
        return tr("api.error.busy", port=error.port) if error.busy else str(error)

    def _refresh_after_api(self) -> None:
        """A script created, changed, started or stopped something: show it."""
        for key in (SECTION_PROFILES, SECTION_PROXIES):
            page = self._pages.get(key)
            if page is not None:
                page.reload()                                         # type: ignore[attr-defined]

    # ------------------------------------------------------------------ navigation
    def page(self, key: str) -> QWidget | None:
        """The page for ``key``, built on first use (``None`` for an unknown key)."""
        page = self._pages.get(key)
        if page is None:
            factory = self._factories.get(key)
            if factory is None:
                return None
            page = self._pages[key] = factory()
            self._stack.addWidget(page)
        return page

    def show_section(self, key: str) -> None:
        page = self.page(key)
        if page is None:
            return
        self._sidebar.select(key)
        self._stack.setCurrentWidget(page)
        self._drop_stray_focus(page)
        if key == SECTION_ACTIVITY:
            self._sidebar.set_badge(SECTION_ACTIVITY, 0)
            self._sidebar.set_count(SECTION_ACTIVITY, 0)

    def _drop_stray_focus(self, page: QWidget) -> None:
        """Opening a page must not leave the cursor (and the accent ring) on its first control.

        The page we leave hides the focused widget, and Qt hands the focus to the next one in the chain,
        which is the search box of the page that appears. A page that has a natural focus target (the table) keeps it.
        """
        focus = QApplication.focusWidget()
        if focus is not None and focus is not page and page.isAncestorOf(focus):
            if hasattr(page, "focus_primary"):
                page.focus_primary()
            else:
                page.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_nav(self, key: str) -> None:
        """A click on 'Profiles' always means *all* profiles: it also leaves a tag or workspace view."""
        if key == SECTION_PROFILES:
            page = self.page(SECTION_PROFILES)
            if page is not None:
                if page.tag() is not None:                         # type: ignore[attr-defined]
                    page.set_tag(None)                             # type: ignore[attr-defined]
                if page.workspace() is not None:                   # type: ignore[attr-defined]
                    page.set_workspace(None)                       # type: ignore[attr-defined]
        self.show_section(key)

    def show_tag(self, tag: str | None) -> None:
        """Open the profiles narrowed to ``tag`` (``None`` = all of them)."""
        self.show_section(SECTION_PROFILES)
        page = self.page(SECTION_PROFILES)
        if page is not None:
            page.set_tag(tag)                                      # type: ignore[attr-defined]

    def show_workspace(self, workspace: int | None) -> None:
        """Open the profiles of a workspace (``NO_WORKSPACE``: those in none; ``None``: all of them)."""
        self.show_section(SECTION_PROFILES)
        page = self.page(SECTION_PROFILES)
        if page is not None:
            page.set_workspace(workspace)                          # type: ignore[attr-defined]

    # ------------------------------------------------------- workspaces and tags
    def _fail(self, exc: object) -> None:
        self._toasts.show_message(friendly_error_text(exc), kind="error")

    def new_workspace(self) -> None:
        from antidetect.gui.dialogs.name_color import NameColorDialog

        dialog = NameColorDialog(
            tr("workspace.new.title"), placeholder=tr("workspace.name.hint"), confirm=tr("tags.create"),
            taken={w.name for w in self._catalog.workspaces}, used_colors=[w.color for w in self._catalog.workspaces],
            parent=self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self._catalog.create_workspace(
                dialog.name(), dialog.color(), on_error=self._fail,
                on_result=lambda ws: (self.show_workspace(ws.id),
                                      self._toasts.show_message(tr("toast.workspace.created", name=ws.name))))

    def _workspace_menu(self, workspace_id: int, position) -> None:
        item = self._catalog.workspace(workspace_id)
        if item is None:
            return
        menu = StyledMenu(self)
        menu.item(tr("workspace.edit"), lambda: self.edit_workspace(workspace_id), icon="edit")
        menu.addSeparator()
        menu.item(tr("workspace.delete"), lambda: self.delete_workspace(workspace_id), icon="trash", danger=True)
        menu.exec(position)

    def edit_workspace(self, workspace_id: int) -> None:
        from antidetect.gui.dialogs.name_color import NameColorDialog

        item = self._catalog.workspace(workspace_id)
        if item is None:
            return
        dialog = NameColorDialog(
            tr("workspace.edit.title"), name=item.name, color=item.color, confirm=tr("common.save"),
            taken={w.name for w in self._catalog.workspaces}, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        if dialog.color() != item.color:
            self._catalog.recolor_workspace(workspace_id, dialog.color(), on_error=self._fail)
        if dialog.name() != item.name:
            self._catalog.rename_workspace(workspace_id, dialog.name(), on_error=self._fail)

    def delete_workspace(self, workspace_id: int) -> None:
        item = self._catalog.workspace(workspace_id)
        if item is None:
            return
        if not confirm(self, tr("workspace.delete.title", name=item.name), tr("workspace.delete.text", n=item.count),
                       tr("common.delete"), danger=True):
            return
        self._catalog.delete_workspace(
            workspace_id, on_error=self._fail,
            on_result=lambda _n: self._toasts.show_message(tr("toast.workspace.deleted", name=item.name)))

    def new_tag(self) -> None:
        from antidetect.gui.dialogs.name_color import NameColorDialog

        dialog = NameColorDialog(
            tr("tags.new.title"), placeholder=tr("tags.name"), confirm=tr("tags.create"),
            taken={t.name for t in self._catalog.tags}, used_colors=[t.color for t in self._catalog.tags], parent=self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self._catalog.create_tag(dialog.name(), dialog.color(), on_error=self._fail)

    def manage_tags(self) -> None:
        from antidetect.gui.dialogs.tags import TagManagerDialog

        TagManagerDialog(self._catalog, self).exec()

    def _tag_menu(self, name: str, position) -> None:
        item = self._catalog.tag(name)
        if item is None:
            return
        menu = StyledMenu(self)
        menu.item(tr("tags.edit"), lambda: self.edit_tag(name), icon="edit")
        menu.addSeparator()
        menu.item(tr("tags.delete"), lambda: self.delete_tag(name), icon="trash", danger=True)
        menu.exec(position)

    def edit_tag(self, name: str) -> None:
        from antidetect.gui.dialogs.name_color import NameColorDialog

        item = self._catalog.tag(name)
        if item is None:
            return
        dialog = NameColorDialog(
            tr("tags.edit.title"), name=item.name, color=item.color, confirm=tr("common.save"),
            taken={t.name for t in self._catalog.tags}, parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        if dialog.color() != item.color:
            self._catalog.recolor_tag(item.id, dialog.color(), on_error=self._fail)
        if dialog.name() != item.name:
            self._catalog.rename_tag(item.id, dialog.name(), on_error=self._fail)

    def delete_tag(self, name: str) -> None:
        item = self._catalog.tag(name)
        if item is None:
            return
        if item.count and not confirm(self, tr("tags.delete.title", name=item.name), tr("tags.delete.text", n=item.count),
                                      tr("common.delete"), danger=True):
            return
        self._catalog.delete_tag(item.id, on_error=self._fail)

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    def show_settings_tab(self, tab: str) -> None:
        """Open Settings on one of its tabs (``check``, ``logs`` or ``general``)."""
        self.show_section(SECTION_SETTINGS)
        page = self.page(SECTION_SETTINGS)
        if page is not None:
            page.show_tab(tab)                                     # type: ignore[attr-defined]

    def current_section(self) -> str | None:
        widget = self._stack.currentWidget()
        return next((k for k, p in self._pages.items() if p is widget), None)

    @property
    def toasts(self) -> ToastHost:
        return self._toasts

    def _register_shortcuts(self) -> None:
        self._menu = AppMenu(self)      # the menu bar owns every shortcut: Ctrl+1..5, Ctrl+K, Ctrl+N, ...
        self._sidebar.searchRequested.connect(self.open_palette)

    # ------------------------------------------------------------------ quick search
    def new_profile(self) -> None:
        self.show_section(SECTION_PROFILES)
        self.page(SECTION_PROFILES).new_profile()                  # type: ignore[union-attr]

    def bulk_create(self) -> None:
        self.show_section(SECTION_PROFILES)
        self.page(SECTION_PROFILES).bulk_create()                  # type: ignore[union-attr]

    def import_profile(self) -> None:
        self.show_section(SECTION_PROFILES)
        self.page(SECTION_PROFILES).import_profile()               # type: ignore[union-attr]

    def add_proxies(self) -> None:
        self.show_section(SECTION_PROXIES)
        self.page(SECTION_PROXIES).add_proxies()                   # type: ignore[union-attr]

    def palette_entries(self) -> list[Entry]:
        """Everything quick search can reach, in the order shown for an empty query."""
        from PySide6.QtGui import QKeySequence as Keys

        def hint(sequence: str) -> str:
            return Keys(sequence).toString(Keys.SequenceFormat.NativeText)

        entries: list[Entry] = []
        page = self._pages.get(SECTION_PROFILES)
        if page is not None:
            for row in page._model.rows():                                                                   # type: ignore[attr-defined]
                sub = " · ".join(x for x in (row.proxy_endpoint or tr("proxy.none"), row.browser) if x)
                entries.append(Entry(
                    "profile", row.name, sub,
                    hint=tr("palette.stop") if row.running else tr("palette.start"),
                    run=lambda r=row: page.toggle_profile(r),                                                # type: ignore[attr-defined]
                    keywords=" ".join(row.tags), running=row.running))
        entries += [
            Entry("action", tr("menu.file.new"), icon="plus", hint=hint("Ctrl+N"), run=self.new_profile,
                  keywords="create new profile добавить создать"),
            Entry("action", tr("menu.more.bulk"), icon="plus", hint=hint("Ctrl+Shift+N"), run=self.bulk_create,
                  keywords="bulk several many create массово несколько создать"),
            Entry("action", tr("menu.more.import"), icon="download", run=self.import_profile,
                  keywords="import export archive zip импорт архив файл"),
            Entry("action", tr("menu.browser.download"), icon="download", run=self.download_browser,
                  keywords="chrome browser download update скачать обновить браузер"),
            Entry("action", tr("menu.file.proxies"), icon="globe", run=self.add_proxies, keywords="proxy прокси import"),
            Entry("action", tr("menu.view.theme"), icon="moon", hint=hint("Ctrl+Shift+L"), run=self.toggle_theme,
                  keywords="theme dark light тема тёмная светлая"),
        ]
        for index, key in enumerate(SECTIONS, start=1):
            icon = {SECTION_PROFILES: "layers", SECTION_PROXIES: "globe", SECTION_ACTIVITY: "activity",
                    SECTION_API: "terminal", SECTION_TRASH: "trash", SECTION_SETTINGS: "sliders"}[key]
            entries.append(Entry("page", tr(self._sidebar.label_key(key)), icon=icon, hint=hint(f"Ctrl+{index}"),
                                 run=lambda k=key: self.show_section(k)))
        for key, icon in (("check", "shield-check"), ("logs", "file-text")):         # tabs of Settings
            entries.append(Entry("page", tr(f"settings.tab.{key}"), icon=icon, run=lambda k=key: self.show_settings_tab(k),
                                 keywords="check fingerprint проверка отпечаток log журнал"))
        for item in self._catalog.workspaces:
            entries.append(Entry("workspace", item.name, tr("palette.workspace", n=item.count),
                                 run=lambda w=item.id: self.show_workspace(w), keywords="workspace пространство",
                                 color=slot_color(item.color)))
        for item in self._catalog.tags:
            entries.append(Entry("tag", item.name, tr("palette.tag", n=item.count), run=lambda t=item.name: self.show_tag(t),
                                 keywords="tag тег", color=slot_color(item.color)))
        return entries

    def open_palette(self) -> CommandPalette:
        palette = CommandPalette(self.palette_entries(), self)
        self._palette = palette
        palette.popup_over(self)
        return palette

    # ----------------------------------------------------------------- browser
    def refresh_browser(self) -> None:
        """Re-read which Chrome will run profiles and tell everyone who shows it."""
        self._runner.submit(
            workers.tasks.browser_info(self._container),
            on_result=self._apply_browser,
            on_error=lambda _exc: None,
        )

    def download_browser(self) -> None:
        """Fetch Google's current Chrome for the app (or say that the newest is already here)."""
        from antidetect.gui.dialogs.browser_download import BrowserDownloadDialog

        dialog = BrowserDownloadDialog(self._container, self._runner, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._container.use_downloaded_browser()          # a path chosen earlier would still win over the one just fetched
        version = dialog.release.version if dialog.release is not None else ""
        self._toasts.show_message(tr("toast.browser.latest" if dialog.already else "toast.browser.installed", version=version))
        self.refresh_browser()

    def _apply_browser(self, info: tuple) -> None:
        self._browser_info = info
        path, version = info
        self._sidebar.set_browser(version, path is not None)
        profiles = self._pages.get(SECTION_PROFILES)
        if profiles is not None:
            profiles.set_browser_found(path is not None)  # type: ignore[attr-defined]
        settings = self._pages.get(SECTION_SETTINGS)
        if settings is not None:
            settings.show_browser(info)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ theme / language
    def _resolved(self) -> str:
        return resolve_theme(current_theme(), QApplication.instance())

    def set_theme(self, theme: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        try:
            self._prefs.set_theme(theme)
        except Exception:
            pass
        self._sidebar.set_theme_state(self._resolved())
        self._container.logs.info("gui", f"Theme switched to {theme}")
        settings = self._pages.get(SECTION_SETTINGS)
        if settings is not None:
            settings.sync_theme(theme)  # type: ignore[attr-defined]

    def toggle_theme(self) -> str:
        nxt = "light" if self._resolved() == "dark" else "dark"
        self.set_theme(nxt)
        return nxt

    def current_theme(self) -> str:
        return self._resolved()

    def _on_system_scheme(self, *_args) -> None:
        if current_theme() == "system":
            app = QApplication.instance()
            if app is not None:
                apply_theme(app, "system")
                self._sidebar.set_theme_state(self._resolved())

    def set_language(self, code: str) -> None:
        set_language(code)
        try:
            self._prefs.set_language(code)
        except Exception:
            pass
        self._container.logs.info("gui", f"Language switched to {code}")
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("app.title"))
        self._menu.retranslate()
        self._sidebar.retranslate(self._resolved())
        self._on_catalog()
        self._sidebar.set_browser(self._browser_info[1], self._browser_info[0] is not None)
        for page in self._pages.values():
            if hasattr(page, "retranslate"):
                page.retranslate()

    # ------------------------------------------------------------------ lifecycle
    def _running_rows(self):
        try:
            return [p for p in self._container.profiles.list_profiles() if p.status.value == "RUNNING"]
        except Exception:
            return []

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._closing:
            running = self._running_rows()
            if running:
                title = f"{tr('quit.title')} ({len(running)})"
                if not confirm(self, title, tr("quit.text"), tr("quit.confirm"), danger=True):
                    event.ignore()
                    return
                for profile in running:
                    try:
                        self._container.profiles.stop_profile(profile.id)
                    except Exception:
                        pass
            self._closing = True
        for page in self._pages.values():
            if hasattr(page, "shutdown"):
                page.shutdown()
        if self._api is not None:
            self._api.stop()
        self._prefs.save_geometry(self)
        self._runner.shutdown()
        super().closeEvent(event)
