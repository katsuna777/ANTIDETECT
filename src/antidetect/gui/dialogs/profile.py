"""Create / edit a profile: one tabbed dialog — General, Proxy, Fingerprint (edit), Notes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from antidetect.application.fingerprint import data as fd
from antidetect.application.fingerprint import privacy
from antidetect.application.fingerprint.generator import COUNTRY_DEFAULTS, SUPPORTED_LANGUAGES
from antidetect.gui import workers
from antidetect.gui.components import (
    AvatarBadge,
    BaseDialog,
    Button,
    Callout,
    Cards,
    FreeProxyNotice,
    Segmented,
    Select,
    Switch,
    TabView,
    divider,
    label,
    repolish,
    set_role,
)
from antidetect.gui.catalog import Catalog
from antidetect.gui.components.tags import TagField, workspace_icon
from antidetect.gui.countries import country_name, known_codes
from antidetect.gui.models import ProfileRow, ProxyRow
from antidetect.gui.models.profiles import OS_NAMES
from antidetect.gui.models.specs import ProfileSpec
from antidetect.gui.theme import flags
from antidetect.i18n import tr
from antidetect.infrastructure.proxy.proxy_parser import parse_line

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.workers import TaskRunner

_OS_ORDER = ("windows", "macos", "linux")
_OS_LABEL = {"windows": "os.windows", "macos": "os.macos", "linux": "os.linux"}
_OS_GLYPH = {"windows": "layout-grid", "macos": "command", "linux": "terminal"}
BODY_HEIGHT = 456            # every tab is this tall, so the dialog never jumps while you move between them
_PROTOCOLS = ("HTTP", "SOCKS5", "HTTPS")
_CORES = {
    "windows": (4, 6, 8, 12, 16, 20),
    "macos": (8, 10, 11, 12),
    "linux": (4, 8, 12, 16),
}
_MEMORY = (4, 8, 16, 24, 32)
_PROXY_NONE, _PROXY_NEW = "none", "new"
TAB_GENERAL, TAB_PROXY, TAB_FINGERPRINT, TAB_NOTES = "general", "proxy", "fingerprint", "notes"


def next_profile_name(existing: set[str]) -> str:
    index = 1
    while tr("profile.default", n=index) in existing:
        index += 1
    return tr("profile.default", n=index)


def _page() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    col = QVBoxLayout(widget)
    col.setContentsMargins(0, 20, 0, 4)
    col.setSpacing(6)
    return widget, col


def _scrolling(page: QWidget) -> QScrollArea:
    """A tab's page that scrolls instead of squeezing its fields into each other when the window is short."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area


def _field(col: QVBoxLayout, caption: str, widget: QWidget, *, gap: int = 14) -> None:
    col.addSpacing(gap)
    col.addWidget(label(caption, "field"))
    col.addSpacing(2)
    col.addWidget(widget)


def _gap(col: QVBoxLayout, height: int) -> QWidget:
    """An invisible spacer that can be hidden with the widget it separates (a hidden widget keeps its layout spacing)."""
    spacer = QWidget()
    spacer.setFixedHeight(height)
    spacer.setVisible(False)
    col.addWidget(spacer)
    return spacer


def _captioned(caption: str, widget: QWidget) -> QVBoxLayout:
    """A label over a control (for the cells of a grid)."""
    cell = QVBoxLayout()
    cell.setSpacing(4)
    cell.addWidget(label(caption, "field"))
    cell.addWidget(widget)
    return cell


class ProfileDialog(BaseDialog):
    """``start_after`` tells the caller to start the profile right away."""

    def __init__(
        self,
        container: "Container",
        runner: "TaskRunner",
        *,
        profile: ProfileRow | None,
        proxies: list[ProxyRow],
        existing_names: set[str],
        configuration=None,
        catalog: Catalog,
        default_workspace: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        self._badge = AvatarBadge(profile.name if profile else next_profile_name(set(existing_names)), 44)
        if profile is not None:
            subtitle = " · ".join(x for x in (OS_NAMES.get(profile.platform or ""), profile.browser) if x)
        else:
            subtitle = tr("dlg.new.subtitle")
        super().__init__(tr("dlg.edit.title") if profile else tr("dlg.new.title"), subtitle, parent=parent, width=660,
                         lead=self._badge)
        self._container = container
        self._catalog = catalog
        self._default_workspace = default_workspace
        self._runner = runner
        self._profile = profile
        self._config = configuration
        self._taken = set(existing_names)
        self._existing = {n.casefold() for n in existing_names if profile is None or n != profile.name}
        self._host = fd.host_platform()
        self._platform = profile.platform if profile and profile.platform else self._host
        self._regenerate = False
        self._checked_proxy_id: int | None = None
        self.start_after = False
        self._fp_widgets: dict[str, Select] = {}
        self._theme: Select | None = None               # on the fingerprint tab, which exists only when editing
        self._noise_canvas: Switch | None = None
        self._noise_audio: Switch | None = None

        self._tabs = TabView()
        self._tabs.setFixedHeight(BODY_HEIGHT)
        self.body.addWidget(self._tabs)
        self._tabs.add_tab(TAB_GENERAL, tr("tab.general"), _scrolling(self._build_general(profile)), "user")
        self._tabs.add_tab(TAB_PROXY, tr("tab.proxy"), _scrolling(self._build_proxy(profile, proxies)), "globe")
        if profile is not None:
            self._tabs.add_tab(TAB_FINGERPRINT, tr("tab.fingerprint"), _scrolling(self._build_fingerprint(profile)),
                               "fingerprint")
        self._tabs.add_tab(TAB_NOTES, tr("tab.notes"), _scrolling(self._build_notes(profile)), "note")

        self.add_footer_button(tr("common.cancel"), None, self.reject)
        if profile is None:
            self._create = self.add_footer_button(tr("btn.create"), None, lambda: self._finish(False))
            self._create_start = self.add_footer_button(tr("btn.create_start"), "primary", lambda: self._finish(True))
            self._create_start.set_icon_name("play")
            self._create_start.setDefault(True)
            self._primary = [self._create, self._create_start]
        else:
            self._save = self.add_footer_button(tr("btn.save"), "primary", lambda: self._finish(False))
            self._save.setDefault(True)
            self._primary = [self._save]

        self._on_os(self._platform, initial=True)
        self._on_geo(self._geo.isChecked())
        self._validate()

    # ------------------------------------------------------------------ tabs
    def _build_general(self, profile: ProfileRow | None) -> QWidget:
        page, col = _page()
        self._name = QLineEdit(profile.name if profile else next_profile_name(self._taken))
        self._name.textChanged.connect(self._validate)
        self._name.textChanged.connect(self._badge.set_name)
        _field(col, tr("field.name"), self._name, gap=0)
        self._name_error = label("", "danger")
        self._name_error.setVisible(False)
        col.addWidget(self._name_error)

        self._os = Cards([(key, tr(_OS_LABEL[key]), _OS_GLYPH[key]) for key in _OS_ORDER], self._platform)
        self._os_buttons = self._os.buttons()
        for key, btn in self._os_buttons.items():
            btn.clicked.connect(lambda _=False, k=key: self._on_os(k))
        col.addSpacing(16)
        col.addWidget(label(tr("field.os"), "field"))
        col.addSpacing(2)
        col.addWidget(self._os)
        self._os_hint = Callout("accent", "info")
        col.addSpacing(8)
        col.addWidget(self._os_hint)

        self._start_url = QLineEdit(profile.start_url or "" if profile else "")
        self._start_url.setPlaceholderText("https://")
        self._workspace = None
        if self._catalog.workspaces or (profile and profile.workspace_id is not None):
            self._workspace = Select()
            self._workspace.fit_to_width(16)
            self._workspace.addItem(workspace_icon(None), tr("workspace.none"), None)
            for item in self._catalog.workspaces:
                self._workspace.addItem(workspace_icon(item.color, item.name), item.name, item.id)
            wanted = profile.workspace_id if profile else self._default_workspace
            if not self._workspace.select_data(wanted):
                self._workspace.setCurrentIndex(0)
        col.addSpacing(16)
        if self._workspace is not None:           # the start page and the workspace share a line
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addLayout(_captioned(tr("field.starturl"), self._start_url), 3)
            row.addLayout(_captioned(tr("drawer.workspace"), self._workspace), 2)
            col.addLayout(row)
        else:
            col.addLayout(_captioned(tr("field.starturl"), self._start_url))
        col.addStretch(1)
        return page

    def _build_proxy(self, profile: ProfileRow | None, proxies: list[ProxyRow]) -> QWidget:
        page, col = _page()
        self._proxy_combo = Select()
        self._proxy_combo.fit_to_width(36)             # a pool of free proxies can be thousands long: never measure them all
        self._proxy_combo.addItem(tr("proxy.mode.none"), _PROXY_NONE)
        self._proxy_combo.addItem(tr("proxy.mode.new"), _PROXY_NEW)
        self._free_proxy_ids = {row.id for row in proxies if not row.is_manual}
        for row in proxies:
            key = "proxy.saved.label" if row.is_manual else "proxy.saved.free"
            text = tr(key, address=row.address, country=country_name(row.country_code, row.country))
            self._proxy_combo.addItem(flags.icon(row.country_code), text, row.id)
        _field(col, tr("field.proxy"), self._proxy_combo, gap=0)
        self._free_notice = FreeProxyNotice()
        self._free_notice.setVisible(False)
        self._free_gap = _gap(col, 10)                 # a gap that exists only while the thing after it is shown
        col.addWidget(self._free_notice)

        # a proxy typed in right here: a tinted panel under the selector, only while "add a new proxy" is chosen
        self._proxy_new = QFrame()
        self._proxy_new.setProperty("role", "tile")
        new_col = QVBoxLayout(self._proxy_new)
        new_col.setContentsMargins(14, 14, 14, 14)
        new_col.setSpacing(10)
        self._proxy_text = QPlainTextEdit()
        self._proxy_text.setPlaceholderText(tr("proxy.paste.placeholder"))
        self._proxy_text.setFixedHeight(72)
        self._proxy_text.textChanged.connect(self._on_proxy_text)
        new_col.addWidget(self._proxy_text)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(label(tr("proxy.type"), "field"))
        self._protocol = Segmented([(name, name) for name in _PROTOCOLS])
        row.addWidget(self._protocol)
        row.addStretch(1)
        self._check_btn = Button(tr("proxy.check"), None, icon="refresh")
        self._check_btn.clicked.connect(self._check_proxy)
        row.addWidget(self._check_btn)
        new_col.addLayout(row)
        self._proxy_hint = label(tr("proxy.paste.hint"), "small", wrap=True)
        new_col.addWidget(self._proxy_hint)
        self._proxy_result = label("", "small", wrap=True)
        self._proxy_result.setVisible(False)             # an empty line would only add to the panel's bottom margin
        new_col.addWidget(self._proxy_result)
        self._new_gap = _gap(col, 10)
        col.addWidget(self._proxy_new)
        self._proxy_new.setVisible(False)
        if profile is not None and profile.proxy_id is not None:
            if self._proxy_combo.findData(profile.proxy_id) < 0:      # not in the list (e.g. it stopped working): keep it
                self._proxy_combo.addItem(flags.icon(profile.proxy_country_code), profile.proxy_endpoint or "—",
                                          profile.proxy_id)
            self._proxy_combo.select_data(profile.proxy_id)  # before connecting: the dialog is still being built
        self._sync_free_notice()
        self._proxy_combo.currentIndexChanged.connect(self._on_proxy_mode)

        col.addSpacing(20)
        geo_row = QFrame()
        geo_row.setProperty("role", "tile")
        geo_layout = QHBoxLayout(geo_row)
        geo_layout.setContentsMargins(16, 14, 16, 14)
        geo_layout.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        texts.addWidget(label(tr("field.geo"), "h3"))
        texts.addWidget(label(tr("geo.hint"), "small", wrap=True))
        geo_layout.addLayout(texts, 1)
        self._geo = Switch(profile.geo_auto if profile else True)
        self._geo.toggled.connect(self._on_geo)
        geo_layout.addWidget(self._geo, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addWidget(geo_row)

        col.addSpacing(10)
        stored = privacy.resolve(self._config.privacy_settings if self._config is not None else None)
        rtc_row = QFrame()
        rtc_row.setProperty("role", "tile")
        rtc_layout = QHBoxLayout(rtc_row)
        rtc_layout.setContentsMargins(16, 14, 16, 14)
        rtc_layout.setSpacing(16)
        rtc_texts = QVBoxLayout()
        rtc_texts.setSpacing(3)
        rtc_texts.addWidget(label(tr("field.webrtc"), "h3"))
        self._webrtc_hint = label("", "small", wrap=True)
        rtc_texts.addWidget(self._webrtc_hint)
        rtc_layout.addLayout(rtc_texts, 1)
        self._webrtc = Select()
        for mode in privacy.WEBRTC_MODES:
            self._webrtc.addItem(tr(f"webrtc.{mode}"), mode)
        self._webrtc.fit_to_width(16)
        self._webrtc.select_data(stored["webrtc"])
        self._webrtc.currentIndexChanged.connect(self._sync_webrtc_hint)
        self._sync_webrtc_hint()
        rtc_layout.addWidget(self._webrtc, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addWidget(rtc_row)
        col.addStretch(1)
        return page

    def _sync_webrtc_hint(self) -> None:
        self._webrtc_hint.setText(tr(f"webrtc.hint.{self._webrtc.currentData()}"))

    def _build_fingerprint(self, profile: ProfileRow) -> QWidget:
        page, col = _page()
        summary = QFrame()
        summary.setProperty("role", "tile")
        grid = QGridLayout(summary)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(8)
        facts = (
            (tr("fp.summary.os"), tr(_OS_LABEL.get(profile.platform or "", "os.windows"))),
            (tr("fp.summary.browser"), profile.browser or "—"),
            (tr("fp.summary.screen"), profile.screen or "—"),
            (tr("fp.summary.gpu"), profile.gpu or "—"),
        )
        for position, (caption, value) in enumerate(facts):       # two columns of "caption  value"
            line, side = divmod(position, 2)
            grid.addWidget(label(caption, "small"), line, side * 2, Qt.AlignmentFlag.AlignVCenter)
            text = label(value)
            text.setMinimumWidth(40)
            grid.addWidget(text, line, side * 2 + 1, Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        col.addWidget(summary)

        head = QHBoxLayout()
        self._regen_btn = Button(tr("fp.regenerate"), None, icon="wand")
        self._regen_btn.clicked.connect(self._on_regenerate)
        head.addWidget(self._regen_btn)
        head.addStretch(1)
        col.addSpacing(12)
        col.addLayout(head)
        self._regen_note = label(tr("fp.regenerated"), "small", wrap=True)
        self._regen_note.setVisible(False)
        col.addWidget(self._regen_note)

        col.addSpacing(18)
        col.addWidget(label(tr("fp.advanced").upper(), "section"))
        col.addSpacing(6)
        fine = QGridLayout()
        fine.setHorizontalSpacing(14)
        fine.setVerticalSpacing(12)
        fine.setColumnStretch(0, 1)
        fine.setColumnStretch(1, 1)
        cfg = self._config

        def add(position: int, key: str, caption: str, combo: Select) -> None:
            row_index, column = divmod(position, 2)
            combo.fit_to_width(12)
            fine.addLayout(_captioned(caption, combo), row_index, column)
            self._fp_widgets[key] = combo

        region = Select()
        current_tz = (cfg.timezone if cfg else None) or profile.timezone
        region.addItem(current_tz or "—", None)
        for code in known_codes():
            if code in COUNTRY_DEFAULTS:
                region.addItem(flags.icon(code), country_name(code), code)
        add(0, "region", tr("fp.timezone"), region)
        language = Select()
        language.addItem(((cfg.language if cfg else None) or profile.language) or "—", None)
        for item in SUPPORTED_LANGUAGES:
            language.addItem(item, item)
        add(1, "language", tr("fp.language"), language)
        screen = Select()
        screen.addItem(profile.screen or "—", None)
        for sc in fd.SCREENS.get(self._platform, ()):
            screen.addItem(f"{sc.width}×{sc.height}  @{sc.dpr:g}x", (sc.width, sc.height, sc.dpr))
        add(2, "screen", tr("fp.screen"), screen)
        gpu = Select()
        gpu.addItem(profile.gpu or "—", None)
        for g in fd.GPUS.get(self._platform, ()):
            gpu.addItem(g.label, g)
        add(3, "gpu", tr("fp.gpu"), gpu)
        cores = Select()
        cores.addItem(str(profile.cores or "—"), None)
        for value in _CORES.get(self._platform, ()):
            cores.addItem(str(value), value)
        add(4, "cores", tr("fp.cores"), cores)
        memory = Select()
        memory.addItem(str(profile.memory_gb or "—"), None)
        for value in _MEMORY:
            memory.addItem(str(value), value)
        add(5, "memory", tr("fp.memory"), memory)
        col.addLayout(fine)
        self._fine_note = label(tr("fp.auto.note"), "small", wrap=True)
        col.addSpacing(8)
        col.addWidget(self._fine_note)

        col.addSpacing(18)
        col.addWidget(label(tr("fp.protection").upper(), "section"))
        col.addSpacing(6)
        stored = privacy.resolve(cfg.privacy_settings if cfg is not None else None)
        tile = QFrame()
        tile.setProperty("role", "tile")
        rows = QVBoxLayout(tile)
        rows.setContentsMargins(16, 6, 16, 6)
        rows.setSpacing(0)
        self._theme = Select()
        for choice in privacy.THEMES:
            self._theme.addItem(tr(f"theme.{choice}"), choice)
        self._theme.fit_to_width(14)
        self._theme.select_data(stored["theme"])
        theme_line = QWidget()
        theme_row = QHBoxLayout(theme_line)
        theme_row.setContentsMargins(0, 12, 0, 12)
        theme_row.setSpacing(16)
        theme_texts = QVBoxLayout()
        theme_texts.setSpacing(2)
        theme_texts.addWidget(label(tr("fp.theme"), "h3"))
        theme_texts.addWidget(label(tr("fp.theme.hint"), "small", wrap=True))
        theme_row.addLayout(theme_texts, 1)
        theme_row.addWidget(self._theme, 0, Qt.AlignmentFlag.AlignVCenter)
        rows.addWidget(theme_line)
        rows.addWidget(divider())
        self._noise_canvas = self._switch_row(rows, "fp.noise.canvas", stored["noise_canvas"], with_divider=True)
        self._noise_audio = self._switch_row(rows, "fp.noise.audio", stored["noise_audio"])
        col.addWidget(tile)
        col.addStretch(1)
        return page

    @staticmethod
    def _switch_row(rows: QVBoxLayout, key: str, checked: bool, *, with_divider: bool = False) -> Switch:
        """A caption, its one-line hint and a switch, as one line of a tile."""
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 12, 0, 12)
        line.setSpacing(16)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(tr(key), "h3"))
        texts.addWidget(label(tr(f"{key}.hint"), "small", wrap=True))
        line.addLayout(texts, 1)
        switch = Switch(checked)
        line.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
        rows.addWidget(row)
        if with_divider:
            rows.addWidget(divider())
        return switch

    def _build_notes(self, profile: ProfileRow | None) -> QWidget:
        page, col = _page()
        self._tags = TagField(self._catalog)
        self._tags.set_tags(list(profile.tags) if profile else [])
        _field(col, tr("field.tags"), self._tags, gap=0)
        self._notes = QPlainTextEdit(profile.notes if profile else "")
        self._notes.setPlaceholderText(tr("drawer.notes.hint"))
        self._notes.setMinimumHeight(170)
        _field(col, tr("field.notes"), self._notes, gap=16)
        col.addStretch(1)
        return page

    # ---------------------------------------------------------------- fingerprint
    def _on_regenerate(self) -> None:
        self._regenerate = True
        self._regen_note.setVisible(True)
        self._regen_btn.setEnabled(False)
        self._set_fine_enabled(False)

    def _set_fine_enabled(self, enabled: bool) -> None:
        for key, combo in self._fp_widgets.items():
            combo.setEnabled(enabled and not (self._geo.isChecked() and key in ("region", "language")))

    # ------------------------------------------------------------------ handlers
    def _on_os(self, key: str, initial: bool = False) -> None:
        self._platform = key
        native = key == self._host
        self._os_hint.set_tone("accent" if native else "warning", "info" if native else "alert")
        self._os_hint.set_content(tr("os.hint.native" if native else "os.hint.other"))
        if self._profile is not None and not initial and key != (self._profile.platform or self._host):
            self._regenerate = True
            self._regen_note.setVisible(True)
            self._regen_btn.setEnabled(False)
            self._set_fine_enabled(False)

    def _on_proxy_mode(self) -> None:
        mode = self._proxy_combo.currentData()
        self._proxy_new.setVisible(mode == _PROXY_NEW)
        self._new_gap.setVisible(mode == _PROXY_NEW)
        self._sync_free_notice()
        self._checked_proxy_id = None
        self._proxy_result.setText("")
        self._proxy_result.setVisible(False)
        self._validate()

    def _sync_free_notice(self) -> None:
        free = self._proxy_combo.currentData() in self._free_proxy_ids
        self._free_notice.setVisible(free)
        self._free_gap.setVisible(free)

    def _on_geo(self, checked: bool) -> None:
        if self._fp_widgets:
            for key in ("region", "language"):
                self._fp_widgets[key].setEnabled(not checked and not self._regenerate)
            self._fine_note.setVisible(checked)

    def _on_proxy_text(self) -> None:
        self._checked_proxy_id = None
        self._proxy_text.setProperty("invalid", False)
        repolish(self._proxy_text)
        self._proxy_result.setText("")
        self._proxy_result.setVisible(False)
        self._validate()

    def _proxy_lines(self) -> list[str]:
        return [ln.strip() for ln in self._proxy_text.toPlainText().splitlines() if ln.strip()]

    def _proxy_readable(self) -> bool:
        lines = self._proxy_lines()
        return bool(lines) and parse_line(lines[0]) is not None

    def _check_proxy(self) -> None:
        if not self._proxy_readable():
            self._set_proxy_result(tr("proxy.unreadable"), "danger")
            return
        self._check_btn.setEnabled(False)
        self._set_proxy_result(tr("proxy.checking"), "small")
        text = self._proxy_lines()[0]
        self._runner.submit(
            workers.tasks.check_new_proxy(self._container, text, self._protocol.value() or "HTTP"),
            on_result=self._on_checked,
            on_error=lambda exc: self._set_proxy_result(tr("proxy.fail", detail=str(exc)), "danger"),
            on_finished=lambda: self._check_btn.setEnabled(True),
        )

    def _on_checked(self, result: dict) -> None:
        if result.get("unreadable"):
            self._set_proxy_result(tr("proxy.unreadable"), "danger")
            return
        self._checked_proxy_id = result.get("id")
        if result.get("ok"):
            self._set_proxy_result(
                tr("proxy.ok", country=country_name(result.get("country_code"), result.get("country")),
                   ms=result.get("latency") or "?"),
                "success",
            )
        else:
            self._set_proxy_result(tr("proxy.fail", detail=(result.get("error") or "—")), "danger")

    def _set_proxy_result(self, text: str, role: str) -> None:
        self._proxy_result.setText(text)
        self._proxy_result.setVisible(bool(text))
        set_role(self._proxy_result, role)

    # ------------------------------------------------------------------ validation / result
    def _flag_tab(self, key: str, invalid: bool) -> None:
        button = self._tabs.bar.buttons().get(key)
        if button is None:
            return
        if bool(button.property("invalid")) != invalid:
            button.setProperty("invalid", invalid)
            repolish(button)

    def _validate(self) -> None:
        if not hasattr(self, "_primary"):  # a signal fired while the dialog is still being assembled
            return
        name = self._name.text().strip()
        error = ""
        if not name:
            error = tr("err.name.empty")
        elif name.casefold() in self._existing:
            error = tr("err.name.exists")
        self._name_error.setText(error)
        self._name_error.setVisible(bool(error))
        self._name.setProperty("invalid", bool(error))
        repolish(self._name)
        self._flag_tab(TAB_GENERAL, bool(error))
        proxy_bad = False
        if self._proxy_combo.currentData() == _PROXY_NEW and self._proxy_lines():
            readable = self._proxy_readable()
            self._proxy_text.setProperty("invalid", not readable)
            repolish(self._proxy_text)
            proxy_bad = not readable
        self._flag_tab(TAB_PROXY, proxy_bad)
        valid = not error and not proxy_bad
        for btn in self._primary:
            btn.setEnabled(valid)

    def _finish(self, start: bool) -> None:
        self.start_after = start
        self.accept()

    def spec(self) -> ProfileSpec:
        mode = self._proxy_combo.currentData()
        proxy_id = mode if isinstance(mode, int) else None
        proxy_text = ""
        if mode == _PROXY_NEW and self._proxy_lines():
            proxy_text = "\n".join(self._proxy_lines()[:1])
            if self._checked_proxy_id is not None:
                proxy_id, proxy_text = self._checked_proxy_id, ""
        spec = ProfileSpec(
            name=self._name.text().strip(),
            platform=self._platform,
            geo_auto=self._geo.isChecked(),
            proxy_id=proxy_id,
            proxy_text=proxy_text,
            proxy_protocol=self._protocol.value() or "HTTP",
            start_url=self._start_url.text().strip(),
            notes=self._notes.toPlainText().strip(),
            tags=self._tags.tags(),
            workspace_id=(self._workspace.currentData() if self._workspace is not None
                          else (self._profile.workspace_id if self._profile else self._default_workspace)),
            regenerate=self._regenerate,
            privacy=self._privacy_choice(),
        )
        if self._profile is not None and not self._regenerate:
            spec.fingerprint = self._fingerprint_changes()
        return spec

    def _privacy_choice(self) -> dict | None:
        """The protection switches to store, or ``None`` when nothing differs from what is stored."""
        chosen = {"webrtc": self._webrtc.currentData()}
        if self._noise_canvas is not None and self._noise_audio is not None and self._theme is not None:
            chosen.update(noise_canvas=self._noise_canvas.isChecked(), noise_audio=self._noise_audio.isChecked(),
                          theme=self._theme.currentData())
        elif self._config is not None:                   # the tab was never built: keep what is stored for the rest
            chosen.update({k: v for k, v in privacy.resolve(self._config.privacy_settings).items() if k != "webrtc"})
        wanted = privacy.minimal(chosen)
        stored = privacy.minimal(self._config.privacy_settings if self._config is not None else None)
        return wanted if wanted != stored else None

    def _fingerprint_changes(self) -> dict:
        changes: dict = {}
        widgets = self._fp_widgets
        if not widgets:
            return changes
        region = widgets["region"].currentData()
        if region and not self._geo.isChecked():
            language, locale_tag, tz = COUNTRY_DEFAULTS[region]
            changes.update(language=language, locale=locale_tag, timezone=tz)
        lang = widgets["language"].currentData()
        if lang and not self._geo.isChecked():
            changes["language"] = lang
        screen = widgets["screen"].currentData()
        if screen:
            changes.update(screen_width=screen[0], screen_height=screen[1], device_pixel_ratio=screen[2],
                           color_depth=fd.default_color_depth(self._platform, screen[2]))
        gpu = widgets["gpu"].currentData()
        cfg = self._config
        if gpu is not None and cfg is not None:
            webgl = dict(cfg.webgl_settings or {})
            webgl.update(vendor=gpu.vendor, renderer=gpu.renderer)
            changes["webgl_settings"] = webgl
        cores, memory = widgets["cores"].currentData(), widgets["memory"].currentData()
        if (cores or memory) and cfg is not None:
            hardware = dict(cfg.hardware_settings or {})
            if cores:
                hardware["cores"] = cores
            if memory:
                hardware["memory_gb"] = memory
                bucket = 1
                while bucket * 2 <= memory:
                    bucket *= 2
                hardware["device_memory_gb"] = min(bucket, 32)
            changes["hardware_settings"] = hardware
        return changes
