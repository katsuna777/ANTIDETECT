"""API: one switch, the address, a short list of keys, and the instruction one click away."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QRectF, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIntValidator, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from antidetect.api import ApiKey, ApiKeyError, ApiSettings
from antidetect.api.settings import MAX_KEY_NAME, parse_port
from antidetect.gui.components import (
    BaseDialog,
    Button,
    IconButton,
    IconLabel,
    SettingGroup,
    StyledMenu,
    Switch,
    confirm,
    label,
    set_role,
)
from antidetect.gui.metrics import CONTENT_MAX_WIDTH, PAGE_MARGINS
from antidetect.gui.models.profiles import date_label, relative_label
from antidetect.gui.pages.api_docs import ApiDocsView
from antidetect.gui.theme import current_palette
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.api import ApiManager
    from antidetect.container import Container
    from antidetect.gui.components import ToastHost

_TICK_MS = 2000


def _utc(moment: str) -> datetime | None:
    """A stored ISO time as the naive-UTC datetime the table helpers expect."""
    try:
        parsed = datetime.fromisoformat(moment)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


class KeyNameDialog(BaseDialog):
    """Asks for a key's name. ``submit`` does the work and answers with an error text, or ``None`` when done."""

    def __init__(self, parent: QWidget | None, title: str, confirm_text: str, submit: Callable[[str], str | None],
                 initial: str = "") -> None:
        super().__init__(title, tr("api.key.dlg.hint"), parent, width=440)
        self._submit = submit
        self._edit = QLineEdit(initial)
        self._edit.setMaxLength(MAX_KEY_NAME)
        self._edit.setPlaceholderText(tr("api.key.dlg.placeholder"))
        self._edit.selectAll()
        self.body.addWidget(self._edit)
        self._error = label("", "danger", wrap=True)
        self._error.setVisible(False)
        self.body.addWidget(self._error)
        self.add_footer_button(tr("common.cancel"), None, self.reject)
        self.ok = self.add_footer_button(confirm_text, "primary", self._accept)
        self.ok.setDefault(True)
        self._edit.textChanged.connect(self._changed)
        self._edit.returnPressed.connect(self._accept)
        self._changed()

    def _changed(self) -> None:
        self._error.setVisible(False)
        self.ok.setEnabled(bool(self._edit.text().strip()))

    def _accept(self) -> None:
        if not self.ok.isEnabled():
            return
        error = self._submit(self._edit.text())
        if error is None:
            self.accept()
        else:
            self._error.setText(error)
            self._error.setVisible(True)

    def set_name(self, text: str) -> None:
        self._edit.setText(text)


class _Dot(QWidget):
    """The status light: green with a soft halo when the API runs, red when it could not start, grey when off."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(16, 16)
        self._state = "off"

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        color = QColor({"on": pal.success, "error": pal.danger}.get(self._state, pal.faint))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self._state != "off":
            halo = QColor(color)
            halo.setAlpha(46)
            painter.setBrush(halo)
            painter.drawEllipse(QRectF(0, 0, 16, 16))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(3.5, 3.5, 9, 9))


class StatusCard(QFrame):
    """``● http://127.0.0.1:[47831] ⧉                              Running  (switch)`` — the whole connection in one line."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "card")
        self.setMinimumHeight(76)
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 14, 22, 14)
        row.setSpacing(12)
        self.dot = _Dot()
        self.prefix = label("http://127.0.0.1:", "address")
        self.port = QLineEdit()
        self.port.setProperty("role", "port")
        self.port.setValidator(QIntValidator(0, 99999, self))
        self.port.setMaxLength(5)
        self.port.setFixedWidth(88)
        self.port.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.copy = IconButton("copy", "")
        self.state = label("", "small")
        self.switch = Switch(False)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.prefix, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.port, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.copy, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(4)
        row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def show_state(self, text: str, role: str, dot: str) -> None:
        self.state.setText(text)
        set_role(self.state, role)
        self.dot.set_state(dot)


class KeyRow(QWidget):
    """One access key: its name and the key (hidden until asked), when it was last used, and three buttons."""

    copyRequested = Signal(str)
    menuRequested = Signal(str, object)

    def __init__(self, key: ApiKey) -> None:
        super().__init__()
        self.key = key
        self._shown = False
        self.setMinimumHeight(68)
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 12, 14, 12)
        row.setSpacing(14)
        tile = QFrame()
        tile.setProperty("role", "tile")
        tile.setFixedSize(40, 40)
        QVBoxLayout(tile).setContentsMargins(0, 0, 0, 0)
        tile.layout().addWidget(IconLabel("key", "muted", 18), 0, Qt.AlignmentFlag.AlignCenter)
        row.addWidget(tile, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self._name = label("", "h3")
        self._secret = label("", "mono")
        self._secret.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        texts.addStretch(1)
        texts.addWidget(self._name)
        texts.addWidget(self._secret)
        texts.addStretch(1)
        row.addLayout(texts, 1)
        self._last = label("", "small")
        row.addWidget(self._last, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)
        self._toggle = IconButton("eye", "")
        self._toggle.clicked.connect(self.toggle_secret)
        self._copy = IconButton("copy", "")
        self._copy.clicked.connect(lambda: self.copyRequested.emit(self.key.id))
        self._more = IconButton("more", "")
        self._more.clicked.connect(lambda: self.menuRequested.emit(self.key.id, self._more.mapToGlobal(self._more.rect().bottomLeft())))
        for button in (self._toggle, self._copy, self._more):
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_key(key)
        self.set_usage(0, None)
        self.retranslate()

    @property
    def secret_shown(self) -> bool:
        return self._shown

    def set_key(self, key: ApiKey) -> None:
        self.key = key
        self._name.setText(key.name)
        self._secret.setText(key.token if self._shown else key.masked())

    def toggle_secret(self) -> None:
        self._shown = not self._shown
        self._secret.setText(self.key.token if self._shown else self.key.masked())
        self._toggle.set_icon_name("eye-off" if self._shown else "eye")
        self._toggle.setToolTip(tr("api.key.hide" if self._shown else "api.key.show"))

    def set_usage(self, requests: int, last_used: float | None) -> None:
        """Just when it was last used; the rest (created, how many requests) is in the tooltip."""
        if last_used is None:
            self._last.setText(tr("api.key.unused"))
        else:
            self._last.setText(relative_label(datetime.fromtimestamp(last_used, timezone.utc).replace(tzinfo=None)))
        self.setToolTip(tr("api.key.tip", date=date_label(_utc(self.key.created_at)), n=requests))

    def retranslate(self) -> None:
        self._toggle.setToolTip(tr("api.key.hide" if self._shown else "api.key.show"))
        self._copy.setToolTip(tr("api.key.copy"))
        self._more.setToolTip(tr("api.key.more"))


class ApiPage(QWidget):
    countChanged = Signal(int)       # how many keys there are (sidebar counter)

    def __init__(self, container: "Container", toasts: "ToastHost", api: "Callable[[], ApiManager]",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._toasts = toasts
        self._api = api
        self._settings = ApiSettings(container.settings)
        self._error: str | None = None             # shown instead of the state until the next change
        self._rows: dict[str, KeyRow] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)
        self._main = QWidget()
        self._docs = ApiDocsView()
        self._docs.backRequested.connect(self.show_main)
        self._stack.addWidget(self._main)
        self._stack.addWidget(self._docs)

        root = QVBoxLayout(self._main)
        root.setContentsMargins(PAGE_MARGINS[0], PAGE_MARGINS[1], PAGE_MARGINS[2], 0)
        root.setSpacing(18)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._title = label(tr("api.title"), "page-title")
        bar.addWidget(self._title)
        bar.addStretch(1)
        self._instruction = Button(tr("api.instruction"), "soft", icon="book-open")
        self._instruction.clicked.connect(self.open_docs)
        self._new_key = Button(tr("api.keys.new"), "primary", icon="plus")
        self._new_key.clicked.connect(self.new_key)
        bar.addWidget(self._instruction)
        bar.addWidget(self._new_key)
        root.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, 1)
        body = QWidget()
        scroll.setWidget(body)
        holder = QHBoxLayout(body)
        holder.setContentsMargins(0, 0, 0, 24)
        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        holder.addWidget(column, 1)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(22)

        self._card = StatusCard()
        self._card.switch.setChecked(self._settings.enabled)
        self._card.port.setText(str(self._settings.port))
        col.addWidget(self._card)
        self._g_keys = SettingGroup(tr("api.keys"))
        col.addWidget(self._g_keys)
        col.addStretch(1)

        self._rebuild_keys()
        self._refresh_status()
        self._retip()
        # connected only now: setting the initial state above must not fire the handlers
        self._card.switch.toggled.connect(self._toggle_api)
        self._card.port.editingFinished.connect(self._apply_port)
        self._card.copy.clicked.connect(self._copy_url)

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ navigation
    def show_main(self) -> None:
        self._stack.setCurrentWidget(self._main)

    def open_docs(self) -> None:
        # Built when opened (a few hundred widgets, ~0.1 s) and let go of on a theme / language change,
        # so it never slows down anything else.
        self._stack.setCurrentWidget(self._docs)
        self._docs.show_docs(self._settings.url, self._settings.token, running=self.is_running())

    def docs_open(self) -> bool:
        return self._stack.currentWidget() is self._docs

    def is_running(self) -> bool:
        return self._settings.enabled and self._api().running

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.docs_open():
            # The instruction is let go of when the theme or language changes while it is out of sight:
            # coming back to this page lands on it, so it has to be built again (a no-op when it is current).
            self.open_docs()
        self._timer.start()
        self._tick()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------------ state
    def refresh(self) -> None:
        """Show the real state again (the window calls this when the API failed to start on launch)."""
        with QSignalBlocker(self._card.switch):
            self._card.switch.setChecked(self._settings.enabled)
        self._error = None
        self._card.port.setText(str(self._settings.port))
        self._refresh_status()

    def _refresh_status(self) -> None:
        text, role, dot = tr("api.state.off"), "small", "off"
        if self._settings.enabled:
            manager = self._api()
            if manager.running:
                text, role, dot = tr("api.state.on"), "success", "on"
            elif manager.error is not None:
                text, role, dot = self._error_text(manager.error), "danger", "error"
        if self._error is not None:
            text, role, dot = self._error, "danger", "error"
        self._card.show_state(text, role, dot)

    @staticmethod
    def _error_text(error) -> str:
        if getattr(error, "busy", False):
            return tr("api.error.busy", port=error.port)
        return tr("api.error.other", error=str(error))

    def _retip(self) -> None:
        self._card.switch.setToolTip(tr("api.enable.tip"))
        self._card.port.setToolTip(tr("api.port.tip"))
        self._card.copy.setToolTip(tr("api.address.copy"))

    def _toggle_api(self, enabled: bool) -> None:
        from antidetect.api.manager import ApiStartError

        self._error = None
        try:
            self._api().set_enabled(enabled)
        except ApiStartError as exc:
            with QSignalBlocker(self._card.switch):
                self._card.switch.setChecked(False)
            self._error = self._error_text(exc)
        self._refresh_status()

    def _apply_port(self) -> None:
        from antidetect.api.manager import ApiStartError

        self._error = None
        wanted = self._card.port.text().strip()
        try:
            if parse_port(wanted) != self._settings.port:
                self._api().set_port(wanted)
        except ValueError:
            self._error = tr("api.port.invalid")
            self._card.port.setText(str(self._settings.port))
        except ApiStartError as exc:
            self._error = self._error_text(exc)
            self._card.port.setText(str(self._settings.port))
        self._refresh_status()

    def _copy_url(self) -> None:
        QGuiApplication.clipboard().setText(self._settings.url)
        self._toasts.show_message(tr("api.address.copied"))

    # ------------------------------------------------------------------ keys
    def _usage(self, key_id: str):
        if self._settings.enabled:
            usage = self._api().usage(key_id)
            return usage.requests, usage.last_used
        return 0, None

    def _rebuild_keys(self) -> None:
        shown = {key_id for key_id, row in self._rows.items() if row.secret_shown}
        self._g_keys.clear()
        self._rows = {}
        keys = self._settings.keys()
        for key in keys:
            row = KeyRow(key)
            if key.id in shown:
                row.toggle_secret()
            row.set_usage(*self._usage(key.id))
            row.copyRequested.connect(self._copy_key)
            row.menuRequested.connect(self._key_menu)
            self._rows[key.id] = row
            self._g_keys.add(row)
        self.countChanged.emit(len(keys))

    def _tick(self) -> None:
        for key_id, row in self._rows.items():
            row.set_usage(*self._usage(key_id))

    def key_rows(self) -> list[KeyRow]:
        return list(self._rows.values())

    def _copy_key(self, key_id: str) -> None:
        QGuiApplication.clipboard().setText(self._settings.get_key(key_id).token)
        self._toasts.show_message(tr("api.key.copied"))

    def _key_menu(self, key_id: str, global_pos) -> None:
        menu = StyledMenu(self)
        menu.item(tr("api.key.rename"), lambda: self.rename_key(key_id), icon="edit")
        menu.item(tr("api.key.regenerate"), lambda: self.regenerate_key(key_id), icon="refresh")
        if len(self._settings.keys()) > 1:
            menu.addSeparator()
            menu.item(tr("api.key.delete"), lambda: self.delete_key(key_id), icon="trash", danger=True)
        menu.exec(global_pos)

    @staticmethod
    def _name_error(exc: ApiKeyError) -> str:
        return tr({"empty": "api.key.err.empty", "long": "api.key.err.long"}.get(exc.reason, "api.key.err.duplicate"))

    def new_key(self) -> None:
        def submit(name: str) -> str | None:
            try:
                key = self._api().add_key(name)
            except ApiKeyError as exc:
                return self._name_error(exc)
            created.append(key)
            return None

        created: list[ApiKey] = []
        if KeyNameDialog(self.window(), tr("api.key.dlg.new"), tr("api.key.dlg.create"), submit).exec() and created:
            self._rebuild_keys()
            key = created[0]
            self._toasts.show_message(tr("api.key.toast.created", name=key.name),
                                      action=(tr("common.copy"), lambda: QGuiApplication.clipboard().setText(key.token)))

    def rename_key(self, key_id: str) -> None:
        def submit(name: str) -> str | None:
            try:
                self._api().rename_key(key_id, name)
            except ApiKeyError as exc:
                return self._name_error(exc)
            return None

        if KeyNameDialog(self.window(), tr("api.key.dlg.rename"), tr("api.key.dlg.save"), submit,
                         self._settings.get_key(key_id).name).exec():
            self._rebuild_keys()

    def regenerate_key(self, key_id: str) -> None:
        key = self._settings.get_key(key_id)
        if confirm(self.window(), tr("api.key.regen.title", name=key.name), tr("api.key.regen.text"),
                   tr("api.key.regen.button"), danger=True):
            self._api().regenerate_key(key_id)
            self._rebuild_keys()

    def delete_key(self, key_id: str) -> None:
        key = self._settings.get_key(key_id)
        if confirm(self.window(), tr("api.key.del.title", name=key.name), tr("api.key.del.text"),
                   tr("common.delete"), danger=True):
            try:
                self._api().delete_key(key_id)
            except ApiKeyError:
                return
            self._rebuild_keys()

    # ------------------------------------------------------------------ i18n
    def retranslate(self) -> None:
        self._title.setText(tr("api.title"))
        self._instruction.setText(tr("api.instruction"))
        self._new_key.setText(tr("api.keys.new"))
        self._g_keys.set_title(tr("api.keys"))
        self._retip()
        self._error = None
        self._refresh_status()
        self._rebuild_keys()
        self._docs.retranslate()
