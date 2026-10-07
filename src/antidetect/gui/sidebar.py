"""Left navigation: brand and quick search, sections with counters, workspaces, tags, browser status, theme switch."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from antidetect.gui.catalog import TagItem, WorkspaceItem
from antidetect.gui.components import IconButton, IconLabel, label
from antidetect.gui.metrics import HEADER_HEIGHT, PAGE_MARGINS, SHEET_BORDER
from antidetect.gui.models.rows import NO_WORKSPACE
from antidetect.gui.resources import APP_MARK_PATH
from antidetect.gui.sidebar_rows import (
    ActionRow,
    MoreButton,
    NavButton,
    SearchPill,
    SectionHeader,
    TagRow,
    WorkspaceRow,
)
from antidetect.i18n import tr

SECTION_PROFILES = "profiles"
SECTION_PROXIES = "proxies"
SECTION_ACTIVITY = "activity"
SECTION_API = "api"
SECTION_TRASH = "trash"
SECTION_SETTINGS = "settings"

#: (key, translation key, icon). Check and Logs live inside Settings now.
NAV_SECTIONS = (
    (SECTION_PROFILES, "nav.profiles", "layers"),
    (SECTION_PROXIES, "nav.proxies", "globe"),
    (SECTION_ACTIVITY, "nav.activity", "activity"),
    (SECTION_API, "nav.api", "terminal"),
    (SECTION_TRASH, "nav.trash", "trash"),
    (SECTION_SETTINGS, "nav.settings", "sliders"),
)
SECTIONS = tuple(key for key, _, _ in NAV_SECTIONS)

SIDEBAR_WIDTH = 228
MAX_TAGS = 8


class Sidebar(QWidget):
    sectionRequested = Signal(str)
    themeToggleRequested = Signal()
    searchRequested = Signal()
    tagRequested = Signal(object)            # a tag name, or None for "all profiles"
    tagsFolded = Signal(bool)                # the Tags section was folded (True) / opened
    workspaceRequested = Signal(object)      # a workspace id, NO_WORKSPACE, or None for "all profiles"
    workspacesFolded = Signal(bool)
    newWorkspaceRequested = Signal()
    newTagRequested = Signal()
    manageTagsRequested = Signal()
    workspaceMenuRequested = Signal(int, object)     # workspace id, global position
    tagMenuRequested = Signal(str, object)           # tag name, global position

    def __init__(self, parent: QWidget | None = None, *, top_inset: int = 0) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._top_inset = top_inset
        layout = QVBoxLayout(self)
        # The brand row is as tall as a page's title row and starts at the same distance from the top of
        # the sheet, so "Antidetect" sits level with the title of whichever page is open. (On macOS Qt
        # already keeps the window's content below the title bar, where the traffic lights are.)
        layout.setContentsMargins(12, PAGE_MARGINS[1] + SHEET_BORDER, 12, 12)
        layout.setSpacing(2)

        brand_row = QWidget()
        brand_row.setFixedHeight(HEADER_HEIGHT)
        brand = QHBoxLayout(brand_row)
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(9)
        mark = QLabel()
        pixmap = QPixmap(str(APP_MARK_PATH))
        if not pixmap.isNull():
            mark.setPixmap(pixmap)
            mark.setFixedSize(26, 26)
            mark.setScaledContents(True)
        name = QLabel(tr("app.title"))
        name.setObjectName("Brand")
        self._search = SearchPill()
        self._search.clicked.connect(self.searchRequested)
        brand.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
        brand.addWidget(name, 0, Qt.AlignmentFlag.AlignVCenter)
        brand.addStretch(1)
        brand.addWidget(self._search, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(brand_row)
        layout.addSpacing(14)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, NavButton] = {}
        self._labels = {key: text_key for key, text_key, _ in NAV_SECTIONS}
        for key, text_key, icon_name in NAV_SECTIONS:
            self._add_button(layout, key, text_key, icon_name)

        # ---- workspaces and tags: they scroll when the window is short, the navigation above and the footer stay
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lists = QWidget()
        lists_layout = QVBoxLayout(lists)
        lists_layout.setContentsMargins(0, 14, 0, 4)
        lists_layout.setSpacing(2)
        self._scroll.setWidget(lists)
        layout.addWidget(self._scroll, 1)

        self._ws_header = SectionHeader(tr("sidebar.workspaces"), action=True)
        self._ws_header.clicked.connect(self._toggle_workspaces)
        self._ws_header.actionClicked.connect(self.newWorkspaceRequested)
        lists_layout.addWidget(self._ws_header)
        self._ws_box = QWidget()
        self._ws_layout = QVBoxLayout(self._ws_box)
        self._ws_layout.setContentsMargins(0, 0, 0, 0)
        self._ws_layout.setSpacing(1)
        lists_layout.addWidget(self._ws_box)
        self._ws_group = QButtonGroup(self)
        self._ws_group.setExclusive(False)
        self._ws_rows: dict[int, WorkspaceRow] = {}
        self._workspaces: list[WorkspaceItem] = []
        self._unassigned = 0
        self._active_workspace: int | None = None
        self._ws_folded = False

        lists_layout.addSpacing(10)
        self._tags_header = SectionHeader(tr("sidebar.tags"), action=True)
        self._tags_header.clicked.connect(self._toggle_tags)
        self._tags_header.actionClicked.connect(self.newTagRequested)
        lists_layout.addWidget(self._tags_header)
        self._tag_box = QWidget()
        self._tag_layout = QVBoxLayout(self._tag_box)
        self._tag_layout.setContentsMargins(0, 0, 0, 0)
        self._tag_layout.setSpacing(1)
        lists_layout.addWidget(self._tag_box)
        lists_layout.addStretch(1)
        self._tag_group = QButtonGroup(self)
        self._tag_group.setExclusive(False)
        self._tag_rows: dict[str, TagRow] = {}
        self._tags: list[TagItem] = []
        self._active_tag: str | None = None
        self._more = False
        self._folded = False
        self._rebuild_workspaces()
        self._rebuild_tags()

        footer = QHBoxLayout()
        footer.setContentsMargins(8, 4, 0, 0)
        footer.setSpacing(8)
        self._browser_icon = IconLabel("check-circle", "success", 16)
        self._browser_text = label("", "small")
        self._theme_button = IconButton("moon", "", size=18)
        self._theme_button.clicked.connect(self.themeToggleRequested)
        footer.addWidget(self._browser_icon)
        footer.addWidget(self._browser_text, 1)
        footer.addWidget(self._theme_button)
        layout.addLayout(footer)

    def _add_button(self, layout: QVBoxLayout, key: str, text_key: str, icon_name: str) -> None:
        button = NavButton(tr(text_key), icon_name)
        button.clicked.connect(lambda _=False, k=key: self.sectionRequested.emit(k))
        self._group.addButton(button)
        self._buttons[key] = button
        layout.addWidget(button)

    # ------------------------------------------------------------ window dragging
    def drag_height(self) -> int:
        return PAGE_MARGINS[1] + SHEET_BORDER + HEADER_HEIGHT + 8

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._top_inset and event.button() == Qt.MouseButton.LeftButton and event.position().y() < self.drag_height():
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._top_inset and event.position().y() < self.drag_height():
            window = self.window()
            window.showNormal() if window.isMaximized() else window.showMaximized()
            return
        super().mouseDoubleClickEvent(event)

    def label_key(self, key: str) -> str:
        return self._labels[key]

    # ---------------------------------------------------------------- state
    def select(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def set_count(self, key: str, count: int | None) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.set_count("" if not count else str(count))

    def set_running(self, key: str, count: int) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.set_running(count)

    def set_badge(self, key: str, count: int) -> None:
        """A filled chip with a number ("99+" past 99); 0 removes it."""
        button = self._buttons.get(key)
        if button is not None:
            button.set_badge("" if count <= 0 else "99+" if count > 99 else str(count))

    # ------------------------------------------------------------ workspaces
    def set_workspaces(self, items: list[WorkspaceItem], unassigned: int) -> None:
        if items == self._workspaces and unassigned == self._unassigned:
            return
        self._workspaces, self._unassigned = list(items), unassigned
        self._rebuild_workspaces()

    def set_active_workspace(self, workspace: int | None) -> None:
        self._active_workspace = workspace
        for workspace_id, row in self._ws_rows.items():
            row.setChecked(workspace is not None and workspace_id == workspace)

    def fold_workspaces(self, folded: bool) -> None:
        self._ws_folded = folded
        self._ws_header.expanded = not folded
        self._ws_header.update()
        self._ws_box.setVisible(not folded)

    def _toggle_workspaces(self) -> None:
        self.fold_workspaces(not self._ws_folded)
        self.workspacesFolded.emit(self._ws_folded)

    def _rebuild_workspaces(self) -> None:
        _clear(self._ws_layout, self._ws_group)
        self._ws_rows.clear()
        for item in self._workspaces:
            row = WorkspaceRow(item.id, item.name, item.color, item.count)
            self._add_workspace_row(row, item.id)
        if self._workspaces and self._unassigned:
            row = WorkspaceRow(NO_WORKSPACE, tr("sidebar.workspaces.none"), None, self._unassigned)
            self._add_workspace_row(row, NO_WORKSPACE)
        if not self._workspaces:
            add = ActionRow(tr("sidebar.workspaces.create"), "plus")
            add.clicked.connect(self.newWorkspaceRequested)
            self._ws_layout.addWidget(add)
        self.set_active_workspace(self._active_workspace)
        self._ws_box.setVisible(not self._ws_folded)

    def _add_workspace_row(self, row: WorkspaceRow, workspace_id: int) -> None:
        row.clicked.connect(lambda _=False, w=workspace_id: self._workspace_clicked(w))
        if workspace_id != NO_WORKSPACE:
            row.customContextMenuRequested.connect(
                lambda pos, r=row, w=workspace_id: self.workspaceMenuRequested.emit(w, r.mapToGlobal(pos)))
        self._ws_group.addButton(row)
        self._ws_rows[workspace_id] = row
        self._ws_layout.addWidget(row)

    def _workspace_clicked(self, workspace_id: int) -> None:
        self.workspaceRequested.emit(None if workspace_id == self._active_workspace else workspace_id)

    # ---------------------------------------------------------------- tags
    def set_tags(self, items: list[TagItem]) -> None:
        if items == self._tags:
            return
        self._tags = list(items)
        self._rebuild_tags()

    def set_active_tag(self, tag: str | None) -> None:
        self._active_tag = tag
        for name, row in self._tag_rows.items():
            row.setChecked(tag is not None and name.casefold() == tag.casefold())
        if tag is not None and tag.casefold() not in {t.casefold() for t in self._tag_rows}:
            self._more = True            # the active tag hides behind "more": open the list
            self._rebuild_tags()

    def fold_tags(self, folded: bool) -> None:
        self._folded = folded
        self._tags_header.expanded = not folded
        self._tags_header.update()
        self._tag_box.setVisible(not folded)

    def _toggle_tags(self) -> None:
        self.fold_tags(not self._folded)
        self.tagsFolded.emit(self._folded)

    def _rebuild_tags(self) -> None:
        _clear(self._tag_layout, self._tag_group)
        self._tag_rows.clear()
        ordered = sorted(self._tags, key=lambda t: (-t.count, t.name.casefold()))
        limit = len(ordered) if self._more else MAX_TAGS
        for item in ordered[:limit]:
            row = TagRow(item.name, item.count)
            row.setChecked(self._active_tag is not None and item.name.casefold() == self._active_tag.casefold())
            row.clicked.connect(lambda _=False, t=item.name: self._tag_clicked(t))
            row.customContextMenuRequested.connect(
                lambda pos, r=row, t=item.name: self.tagMenuRequested.emit(t, r.mapToGlobal(pos)))
            self._tag_group.addButton(row)
            self._tag_rows[item.name] = row
            self._tag_layout.addWidget(row)
        hidden = len(ordered) - limit
        if hidden > 0:
            more = MoreButton(tr("sidebar.tags.more", n=hidden))
            more.clicked.connect(self._show_more)
            self._tag_layout.addWidget(more)
        elif self._more and len(ordered) > MAX_TAGS:
            less = MoreButton(tr("sidebar.tags.less"))
            less.clicked.connect(self._show_less)
            self._tag_layout.addWidget(less)
        manage = ActionRow(tr("sidebar.tags.manage" if self._tags else "sidebar.tags.create"),
                           "tag" if self._tags else "plus")
        manage.clicked.connect(self.manageTagsRequested if self._tags else self.newTagRequested)
        self._tag_layout.addWidget(manage)
        self._tag_box.setVisible(not self._folded)

    def _show_more(self) -> None:
        self._more = True
        self._rebuild_tags()

    def _show_less(self) -> None:
        self._more = False
        self._rebuild_tags()

    def _tag_clicked(self, tag: str) -> None:
        self.tagRequested.emit(None if self._active_tag and tag.casefold() == self._active_tag.casefold() else tag)

    # ---------------------------------------------------------------- footer
    def set_browser(self, version: str | None, found: bool) -> None:
        if found:
            self._browser_icon.set_icon("check-circle", "success")
            self._browser_text.setText(tr("sidebar.browser", version=(version or "").split(".")[0] or "—"))
        else:
            self._browser_icon.set_icon("alert", "warning")
            self._browser_text.setText(tr("sidebar.browser.missing"))

    def set_theme_state(self, resolved_theme: str) -> None:
        dark = resolved_theme == "dark"
        self._theme_button.set_icon_name("sun" if dark else "moon")
        self._theme_button.setToolTip(tr("sidebar.theme.light" if dark else "sidebar.theme.dark"))

    def retranslate(self, resolved_theme: str = "light") -> None:
        for key, button in self._buttons.items():
            button.setText(tr(self._labels[key]))
            button.update()
        self._ws_header.setText(tr("sidebar.workspaces"))
        self._tags_header.setText(tr("sidebar.tags"))
        self._rebuild_workspaces()
        self._rebuild_tags()
        self._search.setToolTip(tr("search.tip"))
        self.set_theme_state(resolved_theme)


def _clear(layout: QVBoxLayout, group: QButtonGroup) -> None:
    """Drop every row of a list (hidden first: a deferred delete would leave it painted for a moment)."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            if isinstance(widget, QAbstractButton):
                group.removeButton(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
