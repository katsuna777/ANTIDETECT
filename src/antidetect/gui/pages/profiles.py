"""Profiles: a searchable table with one-click start/stop, filters, workspaces, tags, bulk actions and a drawer per row."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from antidetect.domain.errors import ChromiumNotFoundError
from antidetect.gui import workers
from antidetect.gui.catalog import Catalog
from antidetect.gui.components import (
    Button,
    Callout,
    EmptyState,
    SearchField,
    StyledMenu,
    label,
)
from antidetect.gui.components.bulk_bar import BulkBar
from antidetect.gui.components.filter_popover import FilterPopover, FilterState
from antidetect.gui.components.profile_drawer import ProfileDrawer
from antidetect.gui.components.proxy_info import ProxyInfoPopover
from antidetect.gui.components.tags import TagPicker, tag_states, workspace_icon
from antidetect.application.transfer_service import safe_file_name
from antidetect.gui.dialogs.bulk import BulkDialog
from antidetect.gui.dialogs.export import ExportDialog
from antidetect.gui.dialogs.profile import ProfileDialog
from antidetect.gui.errors import friendly_error_text, show_error
from antidetect.gui.metrics import COMPACT_HEIGHT, HEADER_HEIGHT, PAGE_MARGINS
from antidetect.gui.models import ProfileRow
from antidetect.gui.models.profiles import (
    COL_COOKIES,
    COL_CREATED,
    COL_LAST,
    COL_MORE,
    COL_NAME,
    COL_PLAY,
    COL_PROXY,
    COL_STATUS,
    ProfilesModel,
)
from antidetect.gui.models.roles import ROW_ROLE
from antidetect.gui.models.rows import NO_WORKSPACE
from antidetect.gui.preferences import Preferences
from antidetect.gui.theme import current_palette
from antidetect.gui.theme import icons as ic
from antidetect.gui.theme.tags import slot_color, tag_color
from antidetect.gui.views.delegates import PROFILE_ROW_HEIGHT, ProfileDelegate
from antidetect.gui.views.expander import RowExpander
from antidetect.gui.views.table import DataTable
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost
    from antidetect.gui.workers import TaskRunner

CHECK_SITES = (
    ("creepjs", "https://abrahamjuliot.github.io/creepjs/"),
    ("pixelscan", "https://pixelscan.net/fingerprint-check"),
    ("iphey", "https://iphey.com/"),
    ("browserleaks", "https://browserleaks.com/webrtc"),
    ("sannysoft", "https://bot.sannysoft.com/"),
)

_POLL_MS = 2500
_CLOCK_EVERY = 24  # polls (≈ 1 min): refresh the "last run" captions
_COLUMN_WIDTHS = (
    (COL_PLAY, 58), (COL_PROXY, 258), (COL_STATUS, 146), (COL_COOKIES, 104),
    (COL_LAST, 124), (COL_CREATED, 118), (COL_MORE, 48),
)
# columns that give way, least important first, as the table narrows: (column, viewport width below which it hides)
_NARROW = ((COL_CREATED, 1050), (COL_LAST, 950), (COL_COOKIES, 850))
_SORTS = ((COL_NAME, "sort.name"), (COL_LAST, "sort.last"), (COL_CREATED, "sort.created"), (COL_STATUS, "sort.status"))


class _ScopePill(QFrame):
    """What the list is narrowed to (a workspace, a tag): marker, name and a cross to leave it.

    Same height as the counter beside it (``COMPACT_HEIGHT``). The name is painted, not a QLabel: when the
    header runs out of room the pill gives way and cuts the name with an ellipsis instead of clipping it.
    """

    cleared = Signal()
    _PAD_L, _MARKER, _GAP, _CROSS, _PAD_R = 12, 10, 8, 12, 10
    _MIN_TEXT = 48

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(COMPACT_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._name = ""
        self._color = "#888888"
        self._tile = False
        self._hover = False
        self.setMouseTracking(True)
        self.setVisible(False)

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _chrome(self) -> int:
        return self._PAD_L + self._MARKER + self._GAP + self._GAP + self._CROSS + self._PAD_R

    def sizeHint(self) -> QSize:  # noqa: N802
        text = QFontMetrics(self._font()).horizontalAdvance(self._name)
        return QSize(self._chrome() + text, COMPACT_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        text = min(QFontMetrics(self._font()).horizontalAdvance(self._name), self._MIN_TEXT)
        return QSize(self._chrome() + text, COMPACT_HEIGHT)

    def set_scope(self, name: str | None, color: str | None = None, *, tile: bool = False) -> None:
        self._name = name or ""
        self._color = color or "#888888"
        self._tile = tile
        self.setToolTip(self._name)
        self.setVisible(bool(name))
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._name:
            return
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.nav_selected if self._hover else pal.subtle))
        painter.drawRoundedRect(self.rect(), 9, 9)
        painter.setBrush(QColor(self._color))
        middle = self.height() / 2
        if self._tile:
            painter.drawRoundedRect(QRectF(self._PAD_L, middle - 5, 10, 10), 3, 3)
        else:
            painter.drawEllipse(QRectF(self._PAD_L + 1.5, middle - 3.5, 7, 7))
        left = self._PAD_L + self._MARKER + self._GAP
        room = self.width() - left - self._GAP - self._CROSS - self._PAD_R
        font = self._font()
        painter.setFont(font)
        painter.setPen(QColor(pal.text))
        shown = QFontMetrics(font).elidedText(self._name, Qt.TextElideMode.ElideRight, max(0, room))
        painter.drawText(QRectF(left, 0, max(0, room), self.height()), Qt.AlignmentFlag.AlignVCenter, shown)
        painter.drawPixmap(self.width() - self._PAD_R - self._CROSS, int(middle - 6),
                           ic.pixmap("x", pal.text if self._hover else pal.muted, 12, 2.0,
                                     painter.device().devicePixelRatioF()))

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.cleared.emit()


class ProfilesPage(QWidget):
    runningChanged = Signal(int)   # number of running profiles (sidebar badge)
    countsChanged = Signal(int)    # total profiles (sidebar)
    tagChanged = Signal(object)    # the tag the list is narrowed to, or None
    workspaceChanged = Signal(object)    # the workspace it is narrowed to (id / NO_WORKSPACE), or None
    browserChanged = Signal()      # the user picked another Chrome
    browserDownloadRequested = Signal()    # the banner's "Download Chrome"
    trashChanged = Signal()        # something went to the trash / came back: the trash counter changed

    def __init__(self, container: "Container", runner: "TaskRunner", toasts: "ToastHost", catalog: Catalog,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._container = container
        self._runner = runner
        self._toasts = toasts
        self._catalog = catalog
        self._prefs = Preferences(container.settings)
        self._reloading = False
        self._reload_again = False
        self._dialog_open = False
        self._settling: dict[int, str] = {}   # profiles still being set up in the background -> busy state
        self._polling = False
        self._shown_once = False
        self._warmed = False                   # the drawer has been rendered once, unseen (see ``warm_drawer``)
        self._ticks = 0
        self._catalog_key: tuple = ()
        self._filter_popover: FilterPopover | None = None
        self._info_popover: ProxyInfoPopover | None = None
        self._picker: TagPicker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE_MARGINS)
        root.setSpacing(14)

        # ---- header: title, counts, scope, then search / filter / sort / new
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._title = label(tr("profiles.title"), "page-title")
        self._count = QLabel("0")
        self._count.setProperty("role", "count")
        self._count.setFixedHeight(COMPACT_HEIGHT)
        self._workspace_pill = _ScopePill()
        self._workspace_pill.cleared.connect(lambda: self.set_workspace(None))
        self._tag_pill = _ScopePill()
        self._tag_pill.cleared.connect(lambda: self.set_tag(None))
        bar.addWidget(self._title)
        bar.addSpacing(2)
        for chip in (self._count, self._workspace_pill, self._tag_pill):
            bar.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        bar.addStretch(1)
        self._search = SearchField(tr("profiles.search"))
        self._search.setMinimumWidth(120)
        self._search.setMaximumWidth(260)
        self._filter_button = Button(tr("filter.button"), "soft", icon="filter")
        self._filter_button.clicked.connect(self._open_filter)
        self._sort_button = Button(tr("sort.button"), "soft", icon="arrow-up-down")
        self._sort_button.clicked.connect(self._open_sort)
        self._more = Button("", "soft", icon="more")           # the rarer ways to make profiles: several at once, from a file
        self._more.setToolTip(tr("menu.more"))
        self._more.clicked.connect(self._open_more)
        self._new = Button(tr("profiles.new"), "primary", icon="plus")
        self._new.clicked.connect(self.new_profile)
        self._new.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)   # the primary action never gets squeezed
        for widget in (self._search, self._filter_button, self._sort_button, self._more, self._new):
            bar.addWidget(widget)
        self._toolbar_widgets = (self._search, self._filter_button, self._sort_button)
        self._toolbar = QWidget()
        self._toolbar.setMinimumHeight(HEADER_HEIGHT)
        bar.setContentsMargins(0, 0, 0, 0)
        self._toolbar.setLayout(bar)
        root.addWidget(self._toolbar)

        # ---- browser banner
        self._banner = Callout("warning", "alert")
        self._banner.set_content(tr("banner.nobrowser"), tr("banner.download"))
        self._banner.activated.connect(self.browserDownloadRequested)
        self._banner.setVisible(False)
        root.addWidget(self._banner)

        # ---- table / empty
        self._model = ProfilesModel(self)
        self._filter = self._model     # the model filters and sorts itself
        self._view = DataTable(PROFILE_ROW_HEIGHT)
        self._view.select_by_checkbox = True      # a click on the row never ticks it: only the checkbox does
        self._view.setModel(self._model)
        self._delegate = ProfileDelegate(self._view)
        self._delegate.catalog = catalog
        self._configure_view()
        self._empty = EmptyState("layers")
        self._empty.action.clicked.connect(self.new_profile)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        # ---- the drawer a row opens into
        self._drawer = ProfileDrawer(catalog, lambda: {r.name for r in self._model.rows()})
        self._expander = RowExpander(
            self._view, self._drawer, base_height=PROFILE_ROW_HEIGHT,
            key_of=lambda position: getattr(self._model.row_at(position), "id", None),
            row_of=self._model.position_of, drawer_height=self._drawer.preferred_height,
        )
        self._view.expander = self._expander
        self._view.rowClicked.connect(self._expander.toggle)
        self._expander.opened.connect(self._on_drawer_opened)
        self._drawer.closeRequested.connect(self._expander.close)
        self._drawer.saveRequested.connect(self._save_drawer)
        self._drawer.settingsRequested.connect(self.edit_profile)
        self._drawer.heightChanged.connect(self._expander.refit)

        self._bulk = BulkBar(self)
        self._bulk.startRequested.connect(lambda: [self._start(r) for r in self._selected() if not r.running])
        self._bulk.stopRequested.connect(lambda: [self._stop(r) for r in self._selected() if r.running])
        self._bulk.deleteRequested.connect(lambda: self.trash_profiles(self._selected()))
        self._bulk.tagsRequested.connect(lambda button: self.pick_tags(self._selected(), button))
        self._bulk.workspaceRequested.connect(self._bulk_workspace_menu)
        self._bulk.clearRequested.connect(self._view.clearSelection)

        self._search.textChanged.connect(self._on_filter_changed)

        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._search.setFocus)
        # These act on the ticked rows while the *table* has the keyboard: with the cursor in a field of the drawer
        # (or in the search box) Return, Delete and Escape belong to that field.
        table_only = Qt.ShortcutContext.WidgetShortcut
        for key in ("Return", "Enter"):
            QShortcut(QKeySequence(key), self._view, activated=self._start_selected, context=table_only)
        QShortcut(QKeySequence("Delete"), self._view, activated=lambda: self.trash_profiles(self._selected()),
                  context=table_only)
        QShortcut(QKeySequence("F2"), self._view, activated=self._edit_selected, context=table_only)
        QShortcut(QKeySequence("Escape"), self._view, activated=self._escape, context=table_only)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state)
        catalog.changed.connect(self._on_catalog)
        for widget in self._toolbar_widgets:     # nothing to search or filter until the first profile exists
            widget.setEnabled(False)
        self._count.setVisible(False)
        self.reload()
        self._show_empty_state()

    # ------------------------------------------------------------------ view setup
    def _configure_view(self) -> None:
        view = self._view
        header = view.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for column, width in _COLUMN_WIDTHS:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            view.setColumnWidth(column, width)
        view.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        view.setItemDelegate(self._delegate)
        view.widthChanged.connect(self._fit_columns)
        column, descending = self._prefs.get_sort(Preferences.KEY_PROFILES_SORT, (COL_NAME, False))
        if not 0 <= column < self._model.columnCount():
            column, descending = COL_NAME, False
        view.sortByColumn(column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        view.hotspot = lambda index, pos: self._delegate.hotspot(index, pos, view)
        self._delegate.actionClicked.connect(self._on_action_clicked)
        self._delegate.menuClicked.connect(self._on_menu_clicked)
        self._delegate.proxyCheckClicked.connect(self._on_proxy_check)
        self._delegate.proxyInfoClicked.connect(self._on_proxy_info)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._context_menu)
        view.selectionModel().selectionChanged.connect(lambda *_: self._sync_bulk())

    def _fit_columns(self, width: int) -> None:
        """Drop the least important columns when the window is narrow."""
        for column, below in _NARROW:
            self._view.setColumnHidden(column, width < below)

    def _on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        try:
            self._prefs.set_sort(Preferences.KEY_PROFILES_SORT, column, order == Qt.SortOrder.DescendingOrder)
        except Exception:
            pass

    def _escape(self) -> None:
        if self._expander.is_open():
            self._expander.close()
        else:
            self._view.clearSelection()

    # ------------------------------------------------------------------ the drawer
    def _on_drawer_opened(self, key) -> None:
        position = self._model.position_of(key)
        row = self._model.row_at(position)
        if row is not None:
            self._drawer.set_row(row)

    def _warm_drawer(self, profile_id: int) -> None:
        try:
            if self.isVisible() and not self._expander.is_open():
                self._expander.warm_up(profile_id)
        except RuntimeError:                 # the window was closed before this idle call ran
            pass

    def open_drawer(self, profile_id: int) -> None:
        """Open the drawer of a profile (quick search, tests)."""
        self._expander.open(profile_id)

    def _save_drawer(self, row: ProfileRow, changes: dict) -> None:
        self._runner.submit(
            workers.tasks.edit_profile_fields(
                self._container, row.id, name=changes.get("name"), notes=changes.get("notes"),
                tags=changes.get("tags"), start_url=changes.get("start_url"), workspace=changes.get("workspace"),
            ),
            on_result=lambda _p: self._toasts.show_message(tr("toast.updated")),
            on_error=self._fail,
            on_finished=self._after_edit,
        )

    def _after_edit(self) -> None:
        self.reload()
        self._catalog.refresh()

    # ------------------------------------------------------------------ data
    def reload(self) -> None:
        """Re-read the table. A request made while one is in flight runs right after it."""
        if self._dialog_open:
            return
        if self._reloading:
            self._reload_again = True
            return
        self._reloading = True
        self._runner.submit(
            workers.tasks.list_profile_rows(self._container),
            on_result=self._apply_rows,
            on_error=lambda _exc: None,
            on_finished=self._reload_finished,
        )

    def _reload_finished(self) -> None:
        self._reloading = False
        if self._reload_again:
            self._reload_again = False
            self.reload()

    def _apply_rows(self, rows: list[ProfileRow]) -> None:
        running_before = self._model.running_ids()
        self._model.set_rows(rows)
        for profile_id, state in self._settling.items():  # a stale reload must not wipe the busy marker
            self._model.set_busy(profile_id, state)
        total = len(rows)
        if rows and not self._warmed:
            self._warmed = True
            QTimer.singleShot(700, lambda: self._warm_drawer(rows[0].id))
        running = sum(1 for r in rows if r.running)
        for widget in self._toolbar_widgets:
            widget.setEnabled(total > 0)
        self._update_counts()
        self._show_state()
        self._sync_bulk()
        self._sync_spinner()
        self.countsChanged.emit(total)
        self._sync_catalog(rows)
        if self._model.running_ids() != running_before or not self._shown_once:
            self.runningChanged.emit(running)

    def _sync_catalog(self, rows: list[ProfileRow]) -> None:
        """Ask the catalog to recount when what the rows say about tags / workspaces changed (a script did it)."""
        key = (len(rows), tuple(sorted(
            (r.workspace_id or 0, hash(r.tags)) for r in rows)))
        if key != self._catalog_key:
            self._catalog_key = key
            self._catalog.refresh()

    def _on_catalog(self) -> None:
        """Tags / workspaces changed: repaint the chips, and leave a scope whose tag / workspace was deleted."""
        if self._catalog.loaded:
            tag = self._model.tag_filter()
            if tag and self._catalog.tag(tag) is None:
                self.set_tag(None)
            workspace = self._model.workspace_filter()
            if workspace not in (None, NO_WORKSPACE) and self._catalog.workspace(workspace) is None:
                self.set_workspace(None)
        self._sync_scope_pills()
        self._view.viewport().update()

    def _update_counts(self) -> None:
        total, shown = self._model.total(), self._model.rowCount()
        self._count.setText(str(shown) if shown == total else f"{shown} / {total}")
        self._count.setVisible(total > 0)
        n = self._model.active_filters()
        if not self._compact():                 # narrow windows keep the buttons as bare icons (``_apply_compact``)
            self._filter_button.setText(tr("filter.button") + (f" · {n}" if n else ""))
        self._filter_button.set_active(n > 0)

    def _show_state(self) -> None:
        if self._model.total() == 0:
            self._show_empty_state()
        elif self._model.rowCount() == 0:
            self._empty.set_content(tr("empty.filtered"))
            self._stack.setCurrentWidget(self._empty)
        else:
            self._stack.setCurrentWidget(self._view)

    def _show_empty_state(self) -> None:
        self._empty.set_content(
            tr("empty.title"), tr("empty.text"), tr("profiles.new"),
            [tr("empty.step1"), tr("empty.step2"), tr("empty.step3")],
        )
        self._stack.setCurrentWidget(self._empty)

    def _on_filter_changed(self) -> None:
        self._model.set_text(self._search.text())
        self._update_counts()
        if self._model.total():
            self._show_state()

    def _sync_spinner(self) -> None:
        self._view.set_spinning((COL_PLAY, COL_PROXY) if self._model.has_busy() else ())

    # ------------------------------------------------------------------ scope: workspace, tag; filter; sort
    def tag(self) -> str | None:
        return self._model.tag_filter()

    def workspace(self) -> int | None:
        return self._model.workspace_filter()

    def set_tag(self, tag: str | None) -> None:
        if tag == self._model.tag_filter():
            return
        self._model.set_tag(tag)
        self._sync_scope_pills()
        self._update_counts()
        if self._model.total():
            self._show_state()
        self.tagChanged.emit(tag)

    def set_workspace(self, workspace: int | None) -> None:
        """Narrow the list to a workspace (``NO_WORKSPACE``: the profiles in none; ``None``: all of them)."""
        if workspace == self._model.workspace_filter():
            return
        self._model.set_workspace(workspace)
        self._sync_scope_pills()
        self._update_counts()
        if self._model.total():
            self._show_state()
        self.workspaceChanged.emit(workspace)

    def _sync_scope_pills(self) -> None:
        tag = self._model.tag_filter()
        known = self._catalog.tag(tag) if tag else None
        self._tag_pill.set_scope(known.name if known else tag, tag_color(tag) if tag else None)
        workspace = self._model.workspace_filter()
        if workspace is None:
            self._workspace_pill.set_scope(None)
        elif workspace == NO_WORKSPACE:
            self._workspace_pill.set_scope(tr("sidebar.workspaces.none"), current_palette().faint, tile=True)
        else:
            item = self._catalog.workspace(workspace)
            self._workspace_pill.set_scope(item.name if item else "…", slot_color(item.color) if item else None,
                                           tile=True)

    def _filter_state(self) -> FilterState:
        m = self._model
        return FilterState(state=m.state_filter(), platforms=m.platform_filter(), proxy=m.proxy_filter(),
                           cookies=m.cookies_filter(), created=m.created_filter(), tag=m.tag_filter())

    def _open_filter(self) -> None:
        popover = FilterPopover(self.window(), current=self._filter_state(), tags=self._model.tag_counts())
        popover.changed.connect(self._on_filter_popover)
        self._filter_popover = popover
        button = self._filter_button
        popover.popup_at(QRect(button.mapToGlobal(QPoint(0, 0)), button.size()), align="right")

    def _on_filter_popover(self, state: FilterState) -> None:
        m = self._model
        m.set_state(state.state)
        m.set_platforms(state.platforms)
        m.set_proxy(state.proxy)
        m.set_cookies(state.cookies)
        m.set_created(state.created)
        self.set_tag(state.tag)
        self._update_counts()
        if m.total():
            self._show_state()

    def _open_sort(self) -> None:
        header = self._view.horizontalHeader()
        column, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        menu = StyledMenu(self)
        for key, text in _SORTS:
            menu.item(tr(text), lambda c=key: self._sort_by(c), icon="check" if column == key else "blank")
        menu.addSeparator()
        ascending = order == Qt.SortOrder.AscendingOrder
        menu.item(tr("sort.asc"), lambda: self._sort_by(column, Qt.SortOrder.AscendingOrder),
                  icon="check" if ascending else "blank")
        menu.item(tr("sort.desc"), lambda: self._sort_by(column, Qt.SortOrder.DescendingOrder),
                  icon="check" if not ascending else "blank")
        button = self._sort_button
        menu.exec(button.mapToGlobal(QPoint(button.width() - menu.sizeHint().width(), button.height() + 6)))

    def _open_more(self) -> None:
        menu = StyledMenu(self)
        menu.item(tr("menu.more.bulk"), self.bulk_create, icon="plus")
        menu.item(tr("menu.more.import"), self.import_profile, icon="download")
        button = self._more
        menu.exec(button.mapToGlobal(QPoint(button.width() - menu.sizeHint().width(), button.height() + 6)))

    def _sort_by(self, column: int, order: Qt.SortOrder | None = None) -> None:
        header = self._view.horizontalHeader()
        if order is None:
            order = header.sortIndicatorOrder() if header.sortIndicatorSection() == column else Qt.SortOrder.AscendingOrder
        self._view.sortByColumn(column, order)

    def _compact(self) -> bool:
        return self.width() < 1080

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_compact()
        self._bulk.place(self)

    def _apply_compact(self) -> None:
        """Narrow windows keep the filter and sort buttons as bare icons."""
        compact = self._compact()
        for button, key in ((self._filter_button, "filter.button"), (self._sort_button, "sort.button")):
            button.setText("" if compact else tr(key))
            button.setToolTip(tr(key) if compact else "")
        self._update_counts()

    # ------------------------------------------------------------------ polling
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()
        if self._shown_once:
            self.reload()
        self._shown_once = True

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def focus_primary(self) -> None:
        """Where the keyboard starts: the table (or the page itself while it is empty), never the search box."""
        (self._view if self._stack.currentWidget() is self._view else self).setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_app_state(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self.isVisible():
            self.reload()  # picks up anything the CLI or the OS changed while we were in the background

    def _tick(self) -> None:
        self._ticks += 1
        if self._ticks % _CLOCK_EVERY == 0:
            self._model.refresh_column(COL_NAME)
            self._model.refresh_column(COL_LAST)
        window = self.window()
        if self._polling or self._reloading or self._dialog_open or not window.isActiveWindow():
            return
        # Nothing changes by itself unless something is running (or crashes): skip the
        # database entirely while every profile is stopped, otherwise ask only for the pids.
        if not self._model.running_ids():
            return
        self._polling = True
        self._runner.submit(
            workers.tasks.running_ids(self._container),
            on_result=self._on_polled,
            on_error=lambda _exc: None,
            on_finished=lambda: setattr(self, "_polling", False),
        )

    def _on_polled(self, running: frozenset) -> None:
        if running != self._model.running_ids():
            self.reload()

    # ------------------------------------------------------------------ selection
    def _selected(self) -> list[ProfileRow]:
        rows: list[ProfileRow] = []
        for index in self._view.selectionModel().selectedRows():
            row = index.data(ROW_ROLE)
            if row is not None:
                rows.append(row)
        return rows

    def _sync_bulk(self) -> None:
        count = len(self._view.selectionModel().selectedRows())
        self._bulk.set_count(count)
        self._bulk.setVisible(count > 1)
        if count > 1:
            self._bulk.place(self)
        self._view.viewport().update()    # avatars turn into checkboxes while anything is selected

    def selected_rows(self) -> list[ProfileRow]:
        return self._selected()

    # ------------------------------------------------------------------ actions
    def _on_action_clicked(self, index: QModelIndex) -> None:
        row: ProfileRow | None = index.data(ROW_ROLE)
        if row is not None:
            (self._stop if row.running else self._start)(row)

    def toggle_profile(self, row: ProfileRow) -> None:
        """Start the profile, or stop it when it runs (quick search, menus)."""
        (self._stop if row.running else self._start)(row)

    def _start_selected(self) -> None:
        for row in self._selected():
            if not row.running:
                self._start(row)

    def _edit_selected(self) -> None:
        rows = self._selected()
        if rows:
            self.edit_profile(rows[0])

    def _run_lifecycle(self, row: ProfileRow, busy: str, task, toast_key: str) -> None:
        if self._model.busy(row.id):
            return
        self._model.set_busy(row.id, busy)
        self._sync_spinner()
        self._runner.submit(
            task,
            on_result=lambda _p, name=row.name: self._toasts.show_message(tr(toast_key, name=name)),
            on_error=self._fail,
            on_finished=lambda rid=row.id: self._done(rid),
        )

    def _start(self, row: ProfileRow) -> None:
        self._run_lifecycle(row, "starting", workers.tasks.start_profile(self._container, row.id), "toast.started")

    def _stop(self, row: ProfileRow) -> None:
        self._run_lifecycle(row, "stopping", workers.tasks.stop_profile(self._container, row.id), "toast.stopped")

    def _restart(self, row: ProfileRow) -> None:
        self._run_lifecycle(row, "starting", workers.tasks.restart_profile(self._container, row.id), "toast.started")

    def _done(self, profile_id: int) -> None:
        self._settling.pop(profile_id, None)
        self._model.set_busy(profile_id, None)
        self._sync_spinner()
        self.reload()

    def _fail(self, exc: object) -> None:
        if isinstance(exc, ChromiumNotFoundError):
            self._banner.setVisible(True)
        self._toasts.show_message(
            friendly_error_text(exc), kind="error",
            action=(tr("common.details"), lambda e=exc: show_error(self.window(), e)),
        )

    # ---- proxy buttons ---------------------------------------------------
    def _on_proxy_check(self, index: QModelIndex) -> None:
        row: ProfileRow | None = index.data(ROW_ROLE)
        if row is not None:
            self.check_proxy(row)

    def check_proxy(self, row: ProfileRow) -> None:
        """Re-measure the profile's proxy (its refresh button spins meanwhile)."""
        if row.proxy_id is None or self._model.checking(row.id):
            return
        self._model.set_checking(row.id, True)
        self._sync_spinner()

        def done(pid: int = row.id) -> None:
            self._model.set_checking(pid, False)
            self._sync_spinner()
            self.reload()

        self._runner.submit(
            workers.tasks.check_proxies(self._container, [row.proxy_id]),
            on_error=self._fail,
            on_finished=done,
        )

    def _on_proxy_info(self, index: QModelIndex, anchor: QRect) -> None:
        row: ProfileRow | None = index.data(ROW_ROLE)
        if row is None:
            return
        popover = ProxyInfoPopover(row, self.window())
        popover.checkRequested.connect(lambda r=row: self.check_proxy(r))
        self._info_popover = popover
        popover.popup_at(anchor, align="left")

    # ---- dialogs ---------------------------------------------------------
    def new_profile(self) -> None:
        self._runner.submit(
            workers.tasks.load_dialog_data(self._container),
            on_result=lambda data: self._show_dialog(None, data),
            on_error=self._fail,
        )

    def edit_profile(self, row: ProfileRow) -> None:
        self._runner.submit(
            workers.tasks.load_dialog_data(self._container, row.id),
            on_result=lambda data, r=row: self._show_dialog(r, data),
            on_error=self._fail,
        )

    def _show_dialog(self, row: ProfileRow | None, data: dict) -> None:
        self._dialog_open = True
        try:
            workspace = self._model.workspace_filter()
            dialog = ProfileDialog(
                self._container, self._runner, profile=row, proxies=data["proxies"],
                existing_names=data["names"], configuration=data["configuration"],
                catalog=self._catalog,
                default_workspace=workspace if workspace not in (None, NO_WORKSPACE) else None,
                parent=self.window(),
            )
            accepted = dialog.exec() == dialog.DialogCode.Accepted
        finally:
            self._dialog_open = False
        if not accepted:
            self.reload()                    # whatever was held back while the dialog was open
            return
        spec = dialog.spec()
        if row is None:
            self._create(spec, start=dialog.start_after)
        else:
            self._runner.submit(
                workers.tasks.update_profile(self._container, row.id, spec, row),
                on_result=lambda _p: self._toasts.show_message(tr("toast.updated")),
                on_error=self._fail,
                on_finished=self._after_edit,
            )

    def _create(self, spec, *, start: bool) -> None:
        """The row appears at once; whatever needs the network finishes behind it."""
        self._runner.submit(
            workers.tasks.create_profile(self._container, spec),
            on_result=lambda profile: self._created(profile, spec, start),
            on_error=self._fail,
            on_finished=self._after_edit,
        )

    def _created(self, profile, spec, start: bool) -> None:
        self._toasts.show_message(tr("toast.created", name=profile.name))
        if not workers.tasks.needs_settling(spec, start=start):
            return
        state = "starting" if start else "preparing"
        self._settling[profile.id] = state
        self._model.set_busy(profile.id, state)
        self._sync_spinner()
        self._runner.submit(
            workers.tasks.settle_profile(self._container, profile.id, start=start),
            on_result=(lambda _p, name=profile.name: self._toasts.show_message(tr("toast.started", name=name)))
            if start else None,
            on_error=self._fail,
            on_finished=lambda pid=profile.id: self._done(pid),
        )

    # ---- several at once, to and from a file --------------------------------
    def bulk_create(self) -> None:
        workspace = self._model.workspace_filter()
        self._dialog_open = True
        try:
            dialog = BulkDialog(
                {r.name for r in self._model.rows()}, self._catalog,
                default_workspace=workspace if workspace not in (None, NO_WORKSPACE) else None,
                parent=self.window(),
            )
            accepted = dialog.exec() == dialog.DialogCode.Accepted
        finally:
            self._dialog_open = False
        if not accepted:
            self.reload()
            return
        request = dialog.request()
        self._runner.submit(
            workers.tasks.bulk_create(self._container, request),
            on_result=lambda result, req=request: self._bulk_created(result, req),
            on_error=self._fail,
            on_finished=self._after_edit,
        )

    def _bulk_created(self, result, request) -> None:
        if result.failed:
            shown = "; ".join(result.failed[:2]) + ("…" if len(result.failed) > 2 else "")
            self._toasts.show_message(
                tr("toast.bulk.partial", n=result.created, total=request.count, failed=shown), kind="error")
        else:
            self._toasts.show_message(tr("toast.bulk.created", n=result.created))
        ids = list(result.profile_ids)
        if not ids or not (request.geo_auto or request.proxy_text.strip() or request.proxy_ids):
            return                                    # nothing that needs the network: they are ready
        for profile_id in ids:                        # the rows show "Preparing…" while the proxies are measured together
            self._settling[profile_id] = "preparing"
            self._model.set_busy(profile_id, "preparing")
        self._sync_spinner()
        self._runner.submit(
            workers.tasks.bulk_settle(self._container, ids),
            on_error=self._fail,
            on_finished=lambda pids=ids: self._bulk_ready(pids),
        )

    def _bulk_ready(self, profile_ids: list[int]) -> None:
        for profile_id in profile_ids:
            self._settling.pop(profile_id, None)
            self._model.set_busy(profile_id, None)
        self._sync_spinner()
        self.reload()

    def import_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window(), tr("import.dialog"), "", tr("import.filter"))
        if not path:
            return
        self._runner.submit(
            workers.tasks.import_profile(self._container, Path(path)),
            on_result=lambda profile: self._toasts.show_message(tr("toast.imported", name=profile.name)),
            on_error=self._fail,
            on_finished=self._after_edit,
        )

    def export_profile(self, row: ProfileRow) -> None:
        dialog = ExportDialog(row.name, row.proxy_id is not None, self.window())
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        suggested = str(Path.home() / f"{safe_file_name(row.name)}.zip")
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("export.title"), suggested, tr("import.filter"))
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        self._runner.submit(
            workers.tasks.export_profile(self._container, row.id, Path(path), dialog.include_proxy),
            on_result=lambda out: self._toasts.show_message(tr("toast.exported", path=str(out))),
            on_error=self._fail,
        )

    def duplicate_profile(self, row: ProfileRow) -> None:
        self._runner.submit(
            workers.tasks.duplicate_profile(self._container, row.id),
            on_result=lambda p: self._toasts.show_message(tr("toast.duplicated", name=p.name)),
            on_error=self._fail,
            on_finished=self._after_edit,
        )

    def trash_profiles(self, rows: list[ProfileRow]) -> None:
        """Move profiles to the trash. Nothing is lost, so there is nothing to confirm: a toast offers "Undo"."""
        if not rows:
            return
        ids = [r.id for r in rows]
        names = ", ".join(r.name for r in rows[:2]) + ("…" if len(rows) > 2 else "")
        self._runner.submit(
            workers.tasks.trash_profiles(self._container, ids),
            on_result=lambda moved, label_=names: self._trashed(moved, label_),
            on_error=self._fail,
            on_finished=self._after_trash,
        )

    def _trashed(self, moved: list[int], names: str) -> None:
        text = tr("toast.trashed", name=names) if len(moved) == 1 else tr("toast.trashed.many", n=len(moved))
        self._toasts.show_message(text, action=(tr("toast.undo"), lambda ids=list(moved): self.restore_profiles(ids)),
                                  timeout_ms=7000)

    def _after_trash(self) -> None:
        self.reload()
        self._catalog.refresh()
        self.trashChanged.emit()

    def restore_profiles(self, ids: list[int]) -> None:
        self._runner.submit(
            workers.tasks.restore_profiles(self._container, ids),
            on_result=lambda names: self._toasts.show_message(tr("toast.restored", name=", ".join(names[:2]))),
            on_error=self._fail,
            on_finished=self._after_trash,
        )

    def open_check(self, row: ProfileRow, url: str) -> None:
        if not row.running:
            self._model.set_busy(row.id, "starting")
            self._sync_spinner()
        self._runner.submit(
            workers.tasks.open_url(self._container, row.id, url),
            on_error=self._fail,
            on_finished=lambda rid=row.id: self._done(rid),
        )

    def export_cookies(self, row: ProfileRow) -> None:
        self._runner.submit(
            workers.tasks.export_cookies(self._container, row.id),
            on_result=lambda path: self._toasts.show_message(tr("toast.cookies.exported", path=str(path))),
            on_error=self._fail,
        )

    def import_cookies(self, row: ProfileRow) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window(), tr("menu.cookies.import"))
        if not path:
            return
        self._runner.submit(
            workers.tasks.import_cookies(self._container, row.id, Path(path)),
            on_result=lambda _r: self._toasts.show_message(tr("toast.cookies.imported")),
            on_error=self._fail,
            on_finished=self.reload,
        )

    def open_folder(self, row: ProfileRow) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(row.profile_path))

    # ---- tags and workspaces of several profiles ----------------------------
    def pick_tags(self, rows: list[ProfileRow], anchor: QWidget | QRect | QPoint) -> None:
        """A list of every tag with ticks: ticking adds the tag to ``rows``, unticking removes it."""
        if not rows:
            return
        picker = TagPicker(self._catalog, tag_states(rows), self.window())
        ids = [r.id for r in rows]

        def toggled(name: str, add: bool) -> None:
            self._catalog.assign_tags(ids, [name] if add else [], [] if add else [name], on_error=self._fail)

        picker.toggled.connect(toggled)
        self._picker = picker
        if isinstance(anchor, QWidget):
            rect = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        elif isinstance(anchor, QPoint):
            rect = QRect(anchor, anchor)
        else:
            rect = anchor
        picker.popup_at(rect, align="left")

    def move_to_workspace(self, rows: list[ProfileRow], workspace_id: int | None) -> None:
        if not rows:
            return
        item = self._catalog.workspace(workspace_id)
        name = item.name if item is not None else None
        self._catalog.move_profiles(
            [r.id for r in rows], workspace_id,
            on_result=lambda _n: self._toasts.show_message(
                tr("toast.moved", n=len(rows), name=name) if name else tr("toast.unmoved", n=len(rows))),
            on_error=self._fail,
        )

    def _workspace_items(self, menu: StyledMenu, rows: list[ProfileRow]) -> None:
        shared = {r.workspace_id for r in rows}
        current = next(iter(shared)) if len(shared) == 1 else -2
        menu.item(tr("workspace.none"), lambda: self.move_to_workspace(rows, None),
                  qicon=workspace_icon(None), enabled=current is not None)
        for item in self._catalog.workspaces:
            menu.item(item.name, lambda w=item.id: self.move_to_workspace(rows, w),
                      qicon=workspace_icon(item.color, item.name), enabled=current != item.id)

    def _bulk_workspace_menu(self, button: QWidget) -> None:
        rows = self._selected()
        if not rows:
            return
        menu = StyledMenu(self)
        self._workspace_items(menu, rows)
        menu.exec(button.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 6)))

    # ------------------------------------------------------------------ context menu
    def _menu_rows(self, index: QModelIndex) -> list[ProfileRow]:
        """What a menu opened on ``index`` acts on: the ticked rows when it is one of them, else just that row.

        Opening a menu must not tick anything: only the checkbox selects.
        """
        if index.isValid() and not self._view.selectionModel().isSelected(index):
            row = index.data(ROW_ROLE)
            return [row] if row is not None else []
        return self._selected()

    def _on_menu_clicked(self, index: QModelIndex, global_pos: QPoint) -> None:
        rows = self._menu_rows(index)
        if rows:
            self.build_menu(rows, global_pos).exec(global_pos)

    def _context_menu(self, position) -> None:
        rows = self._menu_rows(self._view.indexAt(position))
        if rows:
            at = self._view.viewport().mapToGlobal(position)
            self.build_menu(rows, at).exec(at)

    def build_menu(self, rows: list[ProfileRow], at: QPoint | None = None) -> StyledMenu:
        menu = StyledMenu(self)
        anchor = at or QCursor.pos()
        if len(rows) > 1:
            menu.caption(tr("menu.selected", n=len(rows)))
            menu.addSeparator()
            menu.item(tr("menu.start"), lambda: [self._start(r) for r in rows if not r.running], icon="play", accent=True)
            menu.item(tr("menu.stop"), lambda: [self._stop(r) for r in rows if r.running], icon="stop")
            menu.addSeparator()
            menu.item(tr("menu.tags"), lambda: self.pick_tags(rows, anchor), icon="tag")
            self._workspace_items(menu.submenu(tr("menu.workspace"), "briefcase"), rows)
            menu.addSeparator()
            menu.item(tr("menu.trash"), lambda: self.trash_profiles(rows), icon="trash", danger=True)
            return menu
        row = rows[0]
        if row.running:
            menu.item(tr("menu.stop"), lambda: self._stop(row), icon="stop")
            menu.item(tr("menu.restart"), lambda: self._restart(row), icon="refresh")
        else:
            menu.item(tr("menu.start"), lambda: self._start(row), icon="play", accent=True)
        menu.addSeparator()
        check = menu.submenu(tr("menu.check"), "shield-check")
        for key, url in CHECK_SITES:
            check.item(f"{tr(f'check.site.{key}')} — {tr(f'check.desc.{key}')}", lambda u=url: self.open_check(row, u))
        menu.item(tr("menu.edit"), lambda: self.edit_profile(row), icon="edit")
        menu.item(tr("menu.duplicate"), lambda: self.duplicate_profile(row), icon="copy")
        self._workspace_items(menu.submenu(tr("menu.workspace"), "briefcase"), rows)
        cookies = menu.submenu(tr("menu.cookies"), "cookie")
        cookies.item(tr("menu.cookies.export"), lambda: self.export_cookies(row), icon="upload")
        cookies.item(tr("menu.cookies.import"), lambda: self.import_cookies(row), icon="download")
        menu.item(tr("menu.folder"), lambda: self.open_folder(row), icon="folder")
        menu.item(tr("menu.export"), lambda: self.export_profile(row), icon="upload", enabled=not row.running)
        menu.addSeparator()
        menu.item(tr("menu.trash"), lambda: self.trash_profiles([row]), icon="trash", danger=True)
        return menu

    # ------------------------------------------------------------------ browser banner
    def set_browser_found(self, found: bool) -> None:
        self._banner.setVisible(not found)

    def _choose_browser(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window(), tr("dlg.choose.browser"))
        if path:
            self._container.set_browser_path(path)
            self.browserChanged.emit()

    # ------------------------------------------------------------------ i18n
    def retranslate(self) -> None:
        self._title.setText(tr("profiles.title"))
        self._new.setText(tr("profiles.new"))
        self._search.setPlaceholderText(tr("profiles.search"))
        self._bulk.retranslate()
        self._drawer.retranslate()
        self._banner.set_content(tr("banner.nobrowser"), tr("banner.download"))
        self._model.retranslate()
        self._sync_scope_pills()
        self._apply_compact()
        if self._model.total() == 0:
            self._show_empty_state()
        else:
            self._show_state()
        self._sync_bulk()

    def shutdown(self) -> None:
        self._timer.stop()
        self._expander.shutdown()
