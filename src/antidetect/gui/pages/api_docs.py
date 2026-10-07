"""The API instruction: how to connect, every method, every type, every error.

Built from :mod:`antidetect.api.reference` (the same text the command line prints and ``docs/API.md``
holds), so it cannot drift from what the server does. Methods fold open on a click.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from antidetect.api import reference as ref
from antidetect.api.examples import examples
from antidetect.gui.components import (
    Button,
    Callout,
    IconLabel,
    SettingGroup,
    TabView,
    flash,
    label,
)
from antidetect.gui.metrics import CONTENT_MAX_WIDTH, PAGE_MARGINS
from antidetect.gui.theme import bus, current_palette
from antidetect.gui.theme.palette import Palette
from antidetect.i18n import get_language, tr

_MONO = "font-family:Menlo,Consolas,'DejaVu Sans Mono',monospace"


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


# ------------------------------------------------------------------------------------ html bits

def _table(headers: list[str], rows: list[list[str]], pal: Palette) -> str:
    """A plain table. Cells arrive as ready HTML."""
    head = "".join(
        f'<th align="left" style="color:{pal.faint};font-size:11px;font-weight:600">{_esc(h)}</th>' for h in headers
    )
    body = "".join("<tr>" + "".join(f'<td valign="top">{cell}</td>' for cell in row) + "</tr>" for row in rows)
    return f'<table width="100%" cellspacing="0" cellpadding="6"><tr bgcolor="{pal.subtle}">{head}</tr>{body}</table>'


def _mono(text: str, pal: Palette, *, bold: bool = False, muted: bool = False) -> str:
    color = f"color:{pal.muted};" if muted else ""
    weight = "font-weight:600;" if bold else ""
    return f'<span style="{_MONO};font-size:12px;{color}{weight}">{_esc(text)}</span>'


def _code(text: str, pal: Palette) -> str:
    return (f'<table width="100%" cellspacing="0" cellpadding="10"><tr><td bgcolor="{pal.subtle}">'
            f'<pre style="margin:0;{_MONO};font-size:12px">{_esc(text)}</pre></td></tr></table>')


def _caption(text: str, pal: Palette) -> str:
    return f'<p style="margin:12px 0 4px 0;color:{pal.faint};font-size:11px;font-weight:600">{_esc(text.upper())}</p>'


def fields_html(fields: tuple[ref.Field, ...], lang: str, pal: Palette, *, required: bool) -> str:
    headers = [ref.pick(ref.FIELD_HEADERS["name"], lang), ref.pick(ref.FIELD_HEADERS["type"], lang)]
    if required:
        headers.append(ref.pick(ref.FIELD_HEADERS["required"], lang))
    headers.append(ref.pick(ref.FIELD_HEADERS["desc"], lang))
    rows = []
    for f in fields:
        row = [_mono(f.name, pal, bold=True), _mono(f.type, pal, muted=True)]
        if required:
            row.append(_esc(ref.pick(ref.LABELS["yes"], lang)) if f.required else "")
        row.append(_esc(ref.pick(f.desc, lang)))
        rows.append(row)
    return _table(headers, rows, pal)


def endpoint_html(e: ref.Endpoint, lang: str, pal: Palette) -> str:
    parts: list[str] = []
    desc = ref.pick(e.desc, lang)
    if desc:
        parts.append(f'<p style="margin:0 0 4px 0">{_esc(desc)}</p>')
    if e.query:
        parts += [_caption(ref.pick(ref.LABELS["query"], lang), pal), fields_html(e.query, lang, pal, required=False)]
    if e.body:
        parts += [_caption(ref.pick(ref.LABELS["body"], lang), pal), fields_html(e.body, lang, pal, required=True)]
    if e.returns:
        parts.append(f'<p style="margin:12px 0 0 0"><span style="color:{pal.muted}">{_esc(ref.pick(ref.LABELS["returns"], lang))}:</span> '
                     f'{_mono(e.returns, pal)}</p>')
    if e.request:
        parts += [_caption(ref.pick(ref.LABELS["request"], lang), pal), _code(e.request, pal)]
    if e.response:
        parts += [_caption(ref.pick(ref.LABELS["response"], lang), pal), _code(e.response, pal)]
    return "".join(parts)


def errors_html(lang: str, pal: Palette) -> str:
    return _table(
        [ref.pick(ref.FIELD_HEADERS["status"], lang), ref.pick(ref.FIELD_HEADERS["code"], lang), ref.pick(ref.FIELD_HEADERS["meaning"], lang)],
        [[_mono(str(status), pal, muted=True), _mono(code, pal, bold=True), _esc(ref.pick(meaning, lang))]
         for status, code, meaning in ref.ERRORS],
        pal,
    )


# ---------------------------------------------------------------------------------------- widgets

def _text_row(text: str, *, role: str | None = None, rich: bool = False) -> QWidget:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(20, 14, 20, 14)
    widget = label(text, role, wrap=True)
    if rich:
        widget.setTextFormat(Qt.TextFormat.RichText)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(widget)
    return row


class _FoldRow(QWidget):
    """A header that unfolds a body, which is only built the first time it is opened.

    The bodies are rich-text tables: the costliest thing in the app to lay out and to restyle, so a
    row nobody opened costs nothing (the instruction used to hold ~25 of them and a theme switch took 2 s).
    """

    def __init__(self) -> None:
        super().__init__()
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self._head = QFrame()
        self._head.setProperty("role", "endpoint")
        self._head.setCursor(Qt.CursorShape.PointingHandCursor)
        self._head_row = QHBoxLayout(self._head)
        self._head_row.setContentsMargins(20, 10, 16, 10)
        self._head_row.setSpacing(12)
        self._chevron = IconLabel("chevron-right", "muted", 16)
        self._details: QWidget | None = None
        self._opened = False
        self._head.mousePressEvent = lambda event: self.toggle()        # type: ignore[method-assign]

    def _seal(self) -> None:
        """Called by the subclass once the header's own widgets are in."""
        self._head_row.addWidget(self._chevron)
        self._outer.addWidget(self._head)

    def _body_html(self) -> str:
        raise NotImplementedError

    def _build_details(self) -> QWidget:
        details = QWidget()
        box = QVBoxLayout(details)
        box.setContentsMargins(20, 0, 20, 16)
        body = QLabel(self._body_html())
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(body)
        return details

    def toggle(self) -> None:
        self.set_open(not self._opened)

    def set_open(self, opened: bool) -> None:
        if opened and self._details is None:
            self._details = self._build_details()
            self._outer.addWidget(self._details)
        if self._details is not None:
            self._details.setVisible(opened)
        self._opened = opened
        self._chevron.set_icon("chevron-down" if opened else "chevron-right")

    @property
    def is_open(self) -> bool:
        return self._opened


class EndpointRow(_FoldRow):
    """``[GET] /v1/profiles   List profiles  ⌄`` — a click unfolds the fields and examples."""

    def __init__(self, endpoint: ref.Endpoint, lang: str, pal: Palette) -> None:
        super().__init__()
        self.endpoint = endpoint
        self._lang, self._pal = lang, pal
        method = label(endpoint.method, "method")
        method.setProperty("tone", endpoint.method.lower())
        path = label(endpoint.path, "path")
        path.setMinimumWidth(250)
        self._head_row.addWidget(method)
        self._head_row.addWidget(path)
        self._head_row.addWidget(label(ref.pick(endpoint.summary, lang), "muted"), 1)
        self._seal()

    def _body_html(self) -> str:
        return endpoint_html(self.endpoint, self._lang, current_palette())     # colours of the theme it is built in


class ModelRow(_FoldRow):
    """``Profile   A browser profile: ...  ⌄`` — a click unfolds the table of its fields."""

    def __init__(self, model: ref.Model, lang: str, pal: Palette) -> None:
        super().__init__()
        self.model = model
        self._lang, self._pal = lang, pal
        name = label(model.name, "path")
        name.setMinimumWidth(110)
        name.setAlignment(Qt.AlignmentFlag.AlignTop)
        intro = label(ref.pick(model.intro, lang), "muted", wrap=True)
        self._head_row.addWidget(name, 0, Qt.AlignmentFlag.AlignTop)
        self._head_row.addWidget(intro, 1)
        self._seal()

    def _body_html(self) -> str:
        fields = self.model.fields
        return fields_html(fields, self._lang, current_palette(), required=any(f.required for f in fields))


class ApiDocsView(QWidget):
    backRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._url, self._token, self._running = "", "", True
        self._built = False
        self._dirty = True                  # language or theme changed since the content was built
        self._rows: list[EndpointRow] = []
        self._models: list[ModelRow] = []
        self._kept_open: set[str] = set()   # what was unfolded when the content was let go
        self._kept_scroll = 0
        self._tabs: TabView | None = None
        self._sample: dict = {}
        self._editors: dict[str, QPlainTextEdit] = {}
        self._example_boxes: dict[str, QVBoxLayout] = {}
        self._off_warning: Callout | None = None
        self._anchors: dict[str, QWidget] = {}
        self._body: QWidget | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(PAGE_MARGINS[0], PAGE_MARGINS[1], PAGE_MARGINS[2], 0)
        root.setSpacing(14)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self._back = Button(tr("api.title"), "ghost", icon="arrow-left")
        self._back.clicked.connect(self.backRequested)
        self._title = label("", "page-title")
        bar.addWidget(self._back)
        bar.addWidget(self._title)
        bar.addStretch(1)
        root.addLayout(bar)
        self._chips = QHBoxLayout()
        self._chips.setSpacing(8)
        root.addLayout(self._chips)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self._scroll, 1)
        QShortcut(QKeySequence("Escape"), self, activated=lambda: self.backRequested.emit())
        bus.aboutToChange.connect(self._release)
        bus.changed.connect(self._on_theme)

    # ------------------------------------------------------------------ content
    def show_docs(self, url: str, token: str, *, running: bool) -> None:
        """Fill in this machine's address and key (the rest is built when first needed, and again after a language / theme change)."""
        if self._dirty or not self._built:
            self._build(opened=self._open_keys() | self._kept_open)
            self._kept_open = set()
        self.set_connection(url, token, running=running)

    def set_connection(self, url: str, token: str, *, running: bool) -> None:
        self._url, self._token, self._running = url, token, running
        for item in examples(url, token, get_language()):
            self._sample[item.key] = item
            editor = self._editors.get(item.key)
            if editor is not None and editor.toPlainText() != item.code:
                editor.setPlainText(item.code)
        if self._off_warning is not None:
            self._off_warning.setVisible(not running)

    def _open_keys(self) -> set[str]:
        return ({row.endpoint.method + row.endpoint.path for row in self._rows if row.is_open}
                | {"type:" + row.model.name for row in self._models if row.is_open})

    def _release(self) -> None:
        """Let go of the built content (remembering what was unfolded and where it was scrolled to).

        Called before the style sheet is swapped: hundreds of widgets, some with rich-text tables, are
        what makes a restyle slow, and the content is rebuilt anyway because its colours are baked in.
        """
        if not self._built:
            return
        self._kept_open = self._open_keys()
        self._kept_scroll = self._scroll.verticalScrollBar().value()
        self._drop_body()
        self._rows, self._models, self._editors, self._anchors = [], [], {}, {}
        self._tabs = self._off_warning = self._body = None
        self._example_boxes = {}
        self._built, self._dirty = False, True

    def _drop_body(self) -> None:
        old = self._scroll.takeWidget()
        if old is not None:
            old.hide()                      # deleteLater() is deferred: until then it would still be restyled and painted
            old.setParent(None)
            old.deleteLater()

    def _on_theme(self) -> None:
        self._invalidate()

    def retranslate(self) -> None:
        self._back.setText(tr("api.title"))
        self._invalidate()

    def _invalidate(self) -> None:
        """The content is out of date: rebuild now when it is on screen, otherwise when it is next opened."""
        if self.isVisible():
            position = self._scroll.verticalScrollBar().value() if self._built else self._kept_scroll
            self._dirty = True
            self.show_docs(self._url, self._token, running=self._running)
            self._restore_scroll(position)
        else:
            self._release()                 # nobody looks at it: do not keep restyling a stale copy
            self._dirty = True

    def _restore_scroll(self, position: int) -> None:
        """The new content has no height until it is laid out: set the position now and once more after."""
        bar = self._scroll.verticalScrollBar()
        bar.setValue(position)

        def again() -> None:
            try:
                bar.setValue(position)
            except RuntimeError:                                  # closed in the meantime
                pass

        QTimer.singleShot(0, again)

    def _build(self, opened: set[str] | None = None) -> None:
        lang, pal = get_language(), current_palette()
        self._title.setText(ref.pick(ref.TITLE, lang))
        self._build_chips(lang)
        if self.isVisible():
            self.repaint()                  # the header is on screen first; the body (~0.1 s) fills in
        self._rows, self._models = [], []
        self._editors = {}
        self._example_boxes = {}
        self._sample = {}
        self._anchors = {}
        body = QWidget()
        holder = QHBoxLayout(body)
        holder.setContentsMargins(0, 4, 0, 28)
        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH)
        holder.addWidget(column, 1)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(22)

        intro = label(ref.pick(ref.INTRO, lang), "muted", wrap=True)
        intro.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(intro)

        # ---- quick start: five tiles in a row
        col.addWidget(label(ref.pick(ref.SECTION_TITLES["quickstart"], lang).upper(), "section"))
        self._anchors["quickstart"] = steps = QWidget()
        tiles = QHBoxLayout(steps)
        tiles.setContentsMargins(0, 0, 0, 0)
        tiles.setSpacing(10)
        icons = ("key", "layers", "play", "terminal", "stop")
        for number, ((title, line), icon) in enumerate(zip(ref.FLOW, icons), 1):
            tile = QFrame()
            tile.setProperty("role", "tile")
            box = QVBoxLayout(tile)
            box.setContentsMargins(14, 14, 14, 14)
            box.setSpacing(6)
            top = QHBoxLayout()
            top.addWidget(IconLabel(icon, "accent", 20))
            top.addStretch(1)
            top.addWidget(label(str(number), "faint"))
            box.addLayout(top)
            box.addWidget(label(ref.pick(title, lang), "h3"))
            hint = label(line, "mono", wrap=True)
            hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(hint)
            box.addStretch(1)
            tiles.addWidget(tile, 1)
        col.addWidget(steps)

        # ---- access keys
        group = SettingGroup(ref.pick(ref.SECTION_TITLES["auth"], lang))
        for paragraph in ref.AUTH:
            text = ref.pick(paragraph, lang)
            if text.startswith("Authorization:"):
                group.add(_text_row(_code(text, pal), rich=True))
            else:
                group.add(_text_row(text))
        col.addWidget(group)
        self._anchors["auth"] = group

        # ---- conventions
        group = SettingGroup(ref.pick(ref.SECTION_TITLES["conventions"], lang))
        for item in ref.CONVENTIONS:
            group.add(_text_row(ref.pick(item, lang)))
        col.addWidget(group)

        # ---- connecting tools
        group = SettingGroup(ref.pick(ref.SECTION_TITLES["connect"], lang))
        group.add(_text_row(ref.pick(ref.CONNECT_INTRO, lang), role="muted"))
        group.add(self._connect_card(lang))
        col.addWidget(group)
        self._anchors["connect"] = group
        self._off_warning = Callout("warning", "alert")
        self._off_warning.set_content(tr("api.docs.off"))
        self._off_warning.setVisible(not self._running)
        col.addWidget(self._off_warning)
        tip = ref.TIPS[0]
        viewport = Callout("accent", "info")
        viewport.set_content(ref.pick(tip.text, lang), title=ref.pick(tip.title, lang))
        col.addWidget(viewport)

        # ---- methods
        methods = label(ref.pick(ref.SECTION_TITLES["methods"], lang).upper(), "section")
        self._anchors["methods"] = methods
        col.addWidget(methods)
        col.addWidget(label(tr("api.docs.methods.hint"), "small"))
        for api_group in ref.GROUPS:
            group = SettingGroup(ref.pick(api_group.title, lang))
            for endpoint in api_group.endpoints:
                row = EndpointRow(endpoint, lang, pal)
                if opened and endpoint.method + endpoint.path in opened:
                    row.set_open(True)
                self._rows.append(row)
                group.add(row)
            col.addWidget(group)

        # ---- types (each unfolds into its table of fields)
        types = label(ref.pick(ref.SECTION_TITLES["types"], lang).upper(), "section")
        self._anchors["types"] = types
        col.addWidget(types)
        group = SettingGroup("")
        for model in ref.MODELS:
            row = ModelRow(model, lang, pal)
            if opened and "type:" + model.name in opened:
                row.set_open(True)
            self._models.append(row)
            group.add(row)
        col.addWidget(group)

        # ---- errors
        group = SettingGroup(ref.pick(ref.SECTION_TITLES["errors"], lang))
        self._anchors["errors"] = group
        table = QLabel(errors_html(lang, pal))
        table.setTextFormat(Qt.TextFormat.RichText)
        table.setWordWrap(True)
        table.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        wrap = QWidget()
        QVBoxLayout(wrap).setContentsMargins(20, 10, 20, 14)
        wrap.layout().addWidget(table)
        group.add(wrap)
        col.addWidget(group)

        # ---- tips
        group = SettingGroup(ref.pick(ref.SECTION_TITLES["tips"], lang))
        self._anchors["tips"] = group
        for tip in ref.TIPS:
            row = QWidget()
            box = QVBoxLayout(row)
            box.setContentsMargins(20, 14, 20, 14)
            box.setSpacing(3)
            box.addWidget(label(ref.pick(tip.title, lang), "h3"))
            text = label(ref.pick(tip.text, lang), "muted", wrap=True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(text)
            group.add(row)
        col.addWidget(group)
        col.addStretch(1)
        self._drop_body()
        self._scroll.setWidget(body)
        self._body = body
        self._built, self._dirty = True, False

    def _build_chips(self, lang: str) -> None:
        """A row of section names that scroll the page to them."""
        while self._chips.count():
            item = self._chips.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for key in ("quickstart", "connect", "methods", "types", "errors", "tips"):
            chip = Button(ref.pick(ref.SECTION_TITLES[key], lang), "chip")
            chip.clicked.connect(lambda _=False, k=key: self.scroll_to(k))
            self._chips.addWidget(chip)
        self._chips.addStretch(1)

    def scroll_to(self, key: str) -> None:
        target, body = self._anchors.get(key), self._body
        if target is not None and body is not None:
            self._scroll.verticalScrollBar().setValue(max(0, target.mapTo(body, QPoint(0, 0)).y() - 6))

    def _connect_card(self, lang: str) -> QWidget:
        """Tabs with a ready script for each tool, a Copy button and a Save button."""
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(20, 0, 20, 16)
        col.setSpacing(8)
        tabs = TabView()
        self._tabs = tabs
        self._sample = {}
        for item in examples(self._url, self._token, lang):
            self._sample[item.key] = item
            page = QWidget()
            box = QVBoxLayout(page)
            box.setContentsMargins(0, 10, 0, 0)
            box.setSpacing(8)
            self._example_boxes[item.key] = box
            tabs.add_tab(item.key, item.title, page)
        tabs.stack.currentChanged.connect(lambda _index: self._ensure_example(tabs.current()))
        self._ensure_example(tabs.current())             # the other scripts are laid out when their tab is first opened
        col.addWidget(tabs)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self._save = Button(tr("api.docs.save"), None, icon="download", size="sm")
        self._save.clicked.connect(self._save_file)
        self._copy = Button(tr("common.copy"), None, icon="copy", size="sm")
        self._copy.clicked.connect(self._copy_code)
        buttons.addWidget(self._save)
        buttons.addWidget(self._copy)
        col.addLayout(buttons)
        return wrap

    def _ensure_example(self, key: str | None) -> None:
        box, item = self._example_boxes.get(key or ""), self._sample.get(key or "")
        if box is None or item is None or key in self._editors:
            return
        if item.install:
            hint = label(f"{tr('api.docs.install')}  {item.install}", "small")
            hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(hint)
        editor = QPlainTextEdit(item.code)
        editor.setReadOnly(True)
        editor.setProperty("role", "mono")
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setFixedHeight(340)
        self._editors[item.key] = editor
        box.addWidget(editor)

    # ------------------------------------------------------------------ actions
    def current_example(self):
        return self._sample[(self._tabs.current() if self._tabs is not None else None) or next(iter(self._sample))]

    def _copy_code(self) -> None:
        QGuiApplication.clipboard().setText(self.current_example().code)
        flash(self._copy, tr("api.docs.copied"), lambda: tr("common.copy"))

    def _save_file(self) -> None:
        item = self.current_example()
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("api.docs.save"), item.filename)
        if path:
            Path(path).write_text(item.code, encoding="utf-8")
            flash(self._save, tr("api.docs.saved", path=Path(path).name), lambda: tr("api.docs.save"))

    def endpoint_rows(self) -> list[EndpointRow]:
        return list(self._rows)
