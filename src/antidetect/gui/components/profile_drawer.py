"""The drawer that opens under a profile row: the fields people change most, and a few facts about the profile.

Editable here: name, workspace, tags, start page, notes (saved with one button that appears once something changed).
Read-only: the screen, graphics, hardware and time zone of the fingerprint, and the dates. Nothing is repeated
from the row itself (system, proxy) and the row's menu already has duplicate / cookies / folder / trash.
Everything rarer (fingerprint, proxy, regenerate) is behind "All settings…".
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui.catalog import Catalog
from antidetect.gui.components.basics import Button, divider, label, repolish
from antidetect.gui.components.fields import Select
from antidetect.gui.components.tags import TagField, workspace_icon
from antidetect.gui.models.profiles import absolute_label, count_text
from antidetect.gui.models.rows import ProfileRow
from antidetect.gui.theme import current_palette
from antidetect.i18n import is_ru, tr

MARGIN_X = 22
NOTES_HEIGHT = 56
NARROW = 860           # below this width the form stacks into one column
NO_WORKSPACE = None


def _caption(text: str) -> QLabel:
    return label(text.upper(), "section")


class _Elided(QLabel):
    """A label that cuts its text with an ellipsis instead of forcing the column wider."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


class _Facts(QFrame):
    """A tinted panel of read-only ``caption  value`` lines in one aligned grid; ``divider`` splits it in groups."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "tile")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(16, 12, 16, 12)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(7)
        self._grid.setColumnStretch(1, 1)
        self._values: dict[str, QLabel] = {}
        self._captions: dict[str, QLabel] = {}
        self._rows = 0

    def add(self, key: str, caption: str) -> QLabel:
        name = label(caption, "small")
        value = _Elided("—")
        self._grid.addWidget(name, self._rows, 0, Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(value, self._rows, 1, Qt.AlignmentFlag.AlignVCenter)
        self._values[key], self._captions[key] = value, name
        self._rows += 1
        return value

    def divider(self) -> None:
        self._grid.addWidget(divider(), self._rows, 0, 1, 2)
        self._rows += 1

    def set(self, key: str, text: str, *, show: bool = True) -> None:
        self._values[key].setText(text or "—")
        self._values[key].setVisible(show)
        self._captions[key].setVisible(show)

    def retranslate(self, captions: dict[str, str]) -> None:
        for key, text in captions.items():
            self._captions[key].setText(text)


def _cores_text(n: int) -> str:
    """"8 cores" / "8 ядер" (Russian has three forms: 1 ядро, 2-4 ядра, 5+ ядер)."""
    if not is_ru():
        return tr("drawer.cores", n=n)
    word = "ядер" if 11 <= n % 100 <= 14 else {1: "ядро", 2: "ядра", 3: "ядра", 4: "ядра"}.get(n % 10, "ядер")
    return f"{n} {word}"


class ProfileDrawer(QFrame):
    saveRequested = Signal(object, object)  # ProfileRow, {field: value} of what changed
    settingsRequested = Signal(object)      # ProfileRow
    closeRequested = Signal()
    heightChanged = Signal()                # the content needs another height (a tag wrapped onto a new line, …)

    def __init__(self, catalog: Catalog, taken_names: Callable[[], set[str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProfileDrawer")
        self._catalog = catalog
        self._taken = taken_names
        self._row: ProfileRow | None = None
        self._baseline: dict = {}
        self._building = False

        root = QVBoxLayout(self)
        root.setContentsMargins(MARGIN_X, 18, MARGIN_X, 16)
        root.setSpacing(14)
        columns = QHBoxLayout()
        columns.setSpacing(30)
        root.addLayout(columns, 1)

        # ------------------------------------------------------------ editable side
        left = QVBoxLayout()
        left.setSpacing(10)
        self._cap_basic = _caption(tr("drawer.basic"))
        left.addWidget(self._cap_basic)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._l_name = label(tr("field.name"), "field")
        self._l_workspace = label(tr("drawer.workspace"), "field")
        self._name = QLineEdit()
        self._name.setMaxLength(200)
        self._workspace = Select()
        self._workspace.fit_to_width(18)
        self._l_tags = label(tr("field.tags"), "field")
        self._l_url = label(tr("field.starturl"), "field")
        self._tags = TagField(catalog)
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://")
        self._l_notes = label(tr("field.notes"), "field")
        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(NOTES_HEIGHT)
        self._notes.setPlaceholderText(tr("drawer.notes.hint"))
        self._grid = grid
        self._narrow = False
        self._arrange_form(False)
        left.addLayout(grid)
        left.addStretch(1)
        columns.addLayout(left, 11)

        # ------------------------------------------------------------ information side
        right = QVBoxLayout()
        right.setSpacing(10)
        self._cap_info = _caption(tr("drawer.info"))
        right.addWidget(self._cap_info)
        self._facts = facts = _Facts()
        facts.add("screen", tr("drawer.screen"))
        facts.add("gpu", tr("drawer.gpu"))
        facts.add("hardware", tr("drawer.hardware"))
        facts.add("timezone", tr("drawer.timezone"))
        facts.divider()
        facts.add("created", tr("drawer.created"))
        facts.add("started", tr("drawer.started"))
        facts.add("cookies", tr("drawer.cookies"))
        right.addWidget(facts)
        right.addStretch(1)
        columns.addLayout(right, 9)

        # ------------------------------------------------------------ actions
        # "All settings" is anchored at the left; what saves the form shows up on the right only once there is
        # something to save, so the bar never offers a button that cannot be pressed.
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._settings = Button(tr("drawer.settings"), "soft", icon="sliders", size="sm")
        bar.addWidget(self._settings)
        bar.addStretch(1)
        self._hint = label("", "small")
        self._hint.setVisible(False)
        bar.addWidget(self._hint)
        bar.addSpacing(4)
        self._revert = Button(tr("drawer.revert"), "ghost", size="sm")
        self._save = Button(tr("btn.save"), "primary", size="sm")
        self._revert.setVisible(False)
        self._save.setVisible(False)
        for button in (self._revert, self._save):
            bar.addWidget(button)
        root.addLayout(bar)

        self._settings.clicked.connect(lambda: self._emit(self.settingsRequested))
        self._save.clicked.connect(self._save_clicked)
        self._revert.clicked.connect(self._revert_clicked)
        for edit in (self._name, self._url):
            edit.textChanged.connect(self._edited)
        self._notes.textChanged.connect(self._edited)
        self._tags.changed.connect(self._edited)
        self._tags.changed.connect(self.heightChanged)         # chips may wrap onto another line (or back)
        self._workspace.currentIndexChanged.connect(self._edited)
        self._name.returnPressed.connect(self._save_clicked)
        self._url.returnPressed.connect(self._save_clicked)
        QShortcut(QKeySequence("Escape"), self, activated=self.closeRequested.emit,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._save_clicked,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        catalog.changed.connect(self._fill_workspaces)
        self._fill_workspaces()

    # -------------------------------------------------------------------- size
    def _arrange_form(self, narrow: bool) -> None:
        """Name and workspace side by side, then one field per line; one column when the window is narrow."""
        grid = self._grid
        for widget in (self._l_name, self._l_workspace, self._name, self._workspace, self._l_tags, self._l_url,
                       self._tags, self._url, self._l_notes, self._notes):
            grid.removeWidget(widget)
        top = Qt.AlignmentFlag.AlignTop
        if narrow:
            order = (self._l_name, self._name, self._l_workspace, self._workspace, self._l_tags, self._tags,
                     self._l_url, self._url, self._l_notes, self._notes)
            for row, widget in enumerate(order):
                grid.addWidget(widget, row, 0, top if widget is self._tags else Qt.AlignmentFlag(0))
            grid.setColumnStretch(1, 0)
        else:
            grid.addWidget(self._l_name, 0, 0)
            grid.addWidget(self._l_workspace, 0, 1)
            grid.addWidget(self._name, 1, 0)
            grid.addWidget(self._workspace, 1, 1)
            grid.addWidget(self._l_tags, 2, 0, 1, 2)
            grid.addWidget(self._tags, 3, 0, 1, 2, top)
            grid.addWidget(self._l_url, 4, 0, 1, 2)
            grid.addWidget(self._url, 5, 0, 1, 2)
            grid.addWidget(self._l_notes, 6, 0, 1, 2)
            grid.addWidget(self._notes, 7, 0, 1, 2)
            grid.setColumnStretch(1, 1)
        self._narrow = narrow

    def preferred_height(self, width: int) -> int:
        """The drawer's height at ``width`` (the form stacks when narrow; tag chips may wrap onto another line)."""
        narrow = width < NARROW
        if narrow != self._narrow:
            self._arrange_form(narrow)
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        if layout.hasHeightForWidth():
            return max(layout.heightForWidth(width), layout.minimumSize().height())
        return layout.sizeHint().height()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(current_palette().border)
        painter.drawLine(MARGIN_X - 4, 0, self.width() - MARGIN_X + 4, 0)

    # -------------------------------------------------------------------- data
    def row(self) -> ProfileRow | None:
        return self._row

    def is_dirty(self) -> bool:
        return self._row is not None and self._collect() != self._baseline

    def set_row(self, row: ProfileRow) -> None:
        """Show ``row``. Typing in progress survives a refresh of the same profile: only an untouched drawer is overwritten."""
        same = self._row is not None and self._row.id == row.id
        keep = same and self.is_dirty()
        self._row = row
        self._baseline = self._baseline_of(row)
        self._building = True
        try:
            if not keep:                              # (kept edits stay; "dirty" is now measured against the fresh row)
                self._load(row)
            self._fill_facts(row)
        finally:
            self._building = False
        self._sync_state()

    def _load(self, row: ProfileRow) -> None:
        self._name.setText(row.name)
        self._url.setText(row.start_url or "")
        self._notes.setPlainText(row.notes)
        self._tags.set_tags(list(row.tags))
        self._select_workspace(row.workspace_id)

    @staticmethod
    def _baseline_of(row: ProfileRow) -> dict:
        return {"name": row.name, "notes": row.notes, "tags": list(row.tags), "start_url": row.start_url or "",
                "workspace": row.workspace_id}

    def _collect(self) -> dict:
        return {"name": self._name.text().strip(), "notes": self._notes.toPlainText().strip(),
                "tags": self._tags.tags(), "start_url": self._url.text().strip(),
                "workspace": self._workspace.currentData()}

    def _fill_facts(self, row: ProfileRow) -> None:
        facts = self._facts
        facts.set("screen", row.screen or "")
        facts.set("gpu", row.gpu or "")
        facts.set("hardware", " · ".join(x for x in (
            _cores_text(row.cores) if row.cores else "",
            tr("drawer.memory", n=row.memory_gb) if row.memory_gb else "") if x))
        facts.set("timezone", " · ".join(x for x in (row.timezone, row.locale) if x))
        facts.set("created", absolute_label(row.created_at))
        facts.set("started", absolute_label(row.last_started_at) if row.last_started_at else tr("common.never"))
        facts.set("cookies", count_text(row.cookie_count))

    # ----------------------------------------------------------------- workspaces
    def _fill_workspaces(self) -> None:
        current = self._workspace.currentData()
        self._workspace.blockSignals(True)
        self._workspace.clear()
        self._workspace.addItem(workspace_icon(None), tr("workspace.none"), None)
        for item in self._catalog.workspaces:
            self._workspace.addItem(workspace_icon(item.color, item.name), item.name, item.id)
        wanted = current if current is not None else (self._row.workspace_id if self._row else None)
        self._select_workspace(wanted)
        self._workspace.blockSignals(False)

    def _select_workspace(self, workspace_id: int | None) -> None:
        self._workspace.blockSignals(True)
        if not self._workspace.select_data(workspace_id):
            self._workspace.setCurrentIndex(0)
        self._workspace.blockSignals(False)

    # ---------------------------------------------------------------- state
    def _edited(self, *_args) -> None:
        if not self._building:
            self._sync_state()

    def _error(self) -> str:
        name = self._name.text().strip()
        if not name:
            return tr("err.name.empty")
        if self._row is not None and name != self._row.name and name.casefold() in {
                n.casefold() for n in self._taken()}:
            return tr("err.name.exists")
        return ""

    def _sync_state(self) -> None:
        dirty = self.is_dirty()
        error = self._error()
        self._name.setProperty("invalid", bool(error))
        repolish(self._name)
        self._hint.setText(error if error else tr("drawer.unsaved") if dirty else "")
        self._hint.setProperty("role", "danger" if error else "small")
        repolish(self._hint)
        self._hint.setVisible(bool(error) or dirty)
        self._revert.setVisible(dirty)
        self._save.setVisible(dirty)
        self._save.setEnabled(dirty and not error)

    def _save_clicked(self) -> None:
        if self._row is None or not self.is_dirty() or self._error():
            return
        now, before = self._collect(), self._baseline
        changes = {key: value for key, value in now.items() if value != before[key]}
        if "workspace" in changes:
            changes["workspace"] = (changes["workspace"],)           # (None,) = "take it out of its workspace"
        self.saveRequested.emit(self._row, changes)

    def _revert_clicked(self) -> None:
        if self._row is not None:
            self._building = True
            try:
                self._load(self._row)
            finally:
                self._building = False
            self._sync_state()
            self.heightChanged.emit()

    def _emit(self, signal) -> None:
        if self._row is not None:
            signal.emit(self._row)

    def focus_name(self) -> None:
        self._name.setFocus()
        self._name.selectAll()

    # ------------------------------------------------------------------- i18n
    def retranslate(self) -> None:
        self._cap_basic.setText(tr("drawer.basic").upper())
        self._cap_info.setText(tr("drawer.info").upper())
        self._l_name.setText(tr("field.name"))
        self._l_workspace.setText(tr("drawer.workspace"))
        self._l_tags.setText(tr("field.tags"))
        self._l_url.setText(tr("field.starturl"))
        self._l_notes.setText(tr("field.notes"))
        self._notes.setPlaceholderText(tr("drawer.notes.hint"))
        self._tags.retranslate()
        self._facts.retranslate({"screen": tr("drawer.screen"), "gpu": tr("drawer.gpu"),
                                 "hardware": tr("drawer.hardware"), "timezone": tr("drawer.timezone"),
                                 "created": tr("drawer.created"), "started": tr("drawer.started"),
                                 "cookies": tr("drawer.cookies")})
        for button, key in ((self._settings, "drawer.settings"), (self._revert, "drawer.revert"),
                            (self._save, "btn.save")):
            button.setText(tr(key))
        self._fill_workspaces()
        if self._row is not None:
            self._fill_facts(self._row)
        self._sync_state()
