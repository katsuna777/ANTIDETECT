"""Tag widgets: colour swatches, a chip field with a picker, and the picker itself.

A tag is created once (with a colour) and handed out from a list — there is no typing of tag names into
profiles. ``TagPicker`` is the one list used everywhere: in the profile dialog and the drawer it edits a
set of names, on the bulk bar and in the context menu it adds / removes tags of several profiles at once.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui.catalog import Catalog
from antidetect.gui.components.basics import Button, divider, label
from antidetect.gui.components.fields import SearchField
from antidetect.gui.components.flow import FlowLayout
from antidetect.gui.components.popover import Popover
from antidetect.gui.theme import current_palette
from antidetect.gui.theme import icons as ic
from antidetect.gui.theme import tags as palette_tags
from antidetect.gui.views.paint import draw_icon, draw_text, elide, ratio, text_width
from antidetect.i18n import tr

ROW_H = 34
MAX_ROWS = 7
CHIP_H = 26
CHIP_MAX_TEXT = 150          # a longer name (an e-mail) is cut with an ellipsis instead of stretching the row

NONE, SOME, ALL = 0, 1, 2          # how many of the profiles in question carry the tag


# ------------------------------------------------------------------------------------ swatches
class SwatchRow(QWidget):
    """The twelve colours of the palette as rounded squares (``per_row`` to a line); one is ticked."""

    changed = Signal(int)

    PAD = 4              # room around the squares for the ring of the ticked one

    def __init__(self, value: int = 0, parent: QWidget | None = None, *, per_row: int = 12, size: int = 24,
                 gap: int = 6) -> None:
        super().__init__(parent)
        self._value = value
        self._over = -1
        self._per_row, self._size, self._gap = per_row, size, gap
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        count = len(palette_tags.colors())
        lines = -(-count // per_row)
        self.setFixedSize(2 * self.PAD + min(count, per_row) * size + (min(count, per_row) - 1) * gap,
                          2 * self.PAD + lines * size + (lines - 1) * gap)

    def value(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = value
        self.update()

    def _rect(self, slot: int) -> QRectF:
        line, column = divmod(slot, self._per_row)
        return QRectF(self.PAD + column * (self._size + self._gap), self.PAD + line * (self._size + self._gap),
                      self._size, self._size)

    def _slot_at(self, pos: QPoint) -> int:
        for slot in range(len(palette_tags.colors())):
            if self._rect(slot).contains(pos.x(), pos.y()):
                return slot
        return -1

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self._size * 0.32
        for slot, color in enumerate(palette_tags.colors()):
            rect = self._rect(slot)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(rect, radius, radius)
            if slot == self._over and slot != self._value:
                painter.setBrush(QColor(255, 255, 255, 46))
                painter.drawRoundedRect(rect, radius, radius)
            if slot == self._value:
                painter.setPen(QPen(QColor(pal.text), 1.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), radius + 2, radius + 2)
                draw_icon(painter, "check", "#FFFFFF", rect.center().x() - 7, rect.center().y() - 7, 14, 2.6)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        over = self._slot_at(event.position().toPoint())
        if over != self._over:
            self._over = over
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._over = -1
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        slot = self._slot_at(event.position().toPoint())
        if slot >= 0 and slot != self._value:
            self._value = slot
            self.update()
            self.changed.emit(slot)


# ---------------------------------------------------------------------------------------- chips
def paint_chip(painter: QPainter, rect: QRectF, name: str, font: QFont, *, color: str | None = None,
               removable: bool = False, hovered: bool = False) -> None:
    """A tag chip: a soft rounded fill, the colour dot, the name and (when ``removable``) a cross."""
    pal = current_palette()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(pal.nav_selected if hovered else pal.subtle))
    painter.drawRoundedRect(rect, 8, 8)
    x = rect.left() + 9
    painter.setBrush(QColor(color or palette_tags.tag_color(name)))
    painter.drawEllipse(QRectF(x, rect.center().y() - 3.5, 7, 7))
    x += 15
    painter.setFont(font)
    painter.setPen(QColor(pal.text))
    room = rect.right() - x - (22 if removable else 8)
    painter.drawText(QRectF(x, rect.top(), room, rect.height()), Qt.AlignmentFlag.AlignVCenter,
                     elide(name, font, int(room)))
    if removable:
        painter.drawPixmap(int(rect.right() - 19), int(rect.center().y() - 6),
                           ic.pixmap("x", pal.muted if not hovered else pal.text, 12, 2.0, ratio(painter)))


class _Chip(QAbstractButton):
    """A tag in a field; a click on it removes it."""

    def __init__(self, name: str, removable: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self._removable = removable
        self.setCursor(Qt.CursorShape.PointingHandCursor if removable else Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._font = QFont(self.font())
        self._font.setPixelSize(12)
        self._font.setWeight(QFont.Weight.Medium)
        tip = tr("tags.remove.tip") if removable else ""
        if text_width(name, self._font) > CHIP_MAX_TEXT:          # cut by the ellipsis: show the whole name
            tip = f"{name}\n{tip}".strip()
        self.setToolTip(tip)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(min(text_width(self.name, self._font), CHIP_MAX_TEXT) + 15 + 9 + (22 if self._removable else 8),
                     CHIP_H)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_chip(painter, QRectF(self.rect()), self.name, self._font, removable=self._removable,
                   hovered=self._removable and self.underMouse())

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class _AddChip(QAbstractButton):
    """The "+ Tag" at the end of a field: a chip of exactly the size of the tags beside it."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._font = QFont(self.font())
        self._font.setPixelSize(12)
        self._font.setWeight(QFont.Weight.Medium)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(10 + 14 + 6 + text_width(self.text(), self._font) + 11, CHIP_H)

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hot = self.underMouse() or self.hasFocus()
        rect = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.nav_selected if hot else pal.subtle))
        painter.drawRoundedRect(rect, 8, 8)
        painter.drawPixmap(10, int(rect.center().y() - 7), ic.pixmap("plus", pal.text if hot else pal.muted, 14, 2.0,
                                                                     ratio(painter)))
        painter.setFont(self._font)
        painter.setPen(QColor(pal.text if hot else pal.muted))
        painter.drawText(QRectF(30, 0, rect.width() - 30, rect.height()), Qt.AlignmentFlag.AlignVCenter, self.text())

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class TagField(QWidget):
    """The tags of a profile as chips with a "+" that opens the picker. ``changed`` fires after every edit."""

    changed = Signal()

    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._names: list[str] = []
        self._picker: TagPicker | None = None
        self._flow = FlowLayout(self, spacing=6)
        self._add = _AddChip(tr("tags.add"))
        self._add.clicked.connect(self._open_picker)
        self._rebuild()

    def tags(self) -> list[str]:
        return list(self._names)

    def set_tags(self, names: list[str]) -> None:
        names = list(names)
        if names != self._names:
            self._names = names
            self._rebuild()

    def retranslate(self) -> None:
        self._add.setText(tr("tags.add"))
        self._add.updateGeometry()
        self._rebuild()

    def _rebuild(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._add:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for name in self._names:
            chip = _Chip(name, removable=True, parent=self)
            chip.clicked.connect(lambda _=False, n=name: self._remove(n))
            self._flow.addWidget(chip)
            chip.show()
        self._flow.addWidget(self._add)
        self._add.setParent(self)
        self._add.show()
        self.updateGeometry()

    def _remove(self, name: str) -> None:
        self._names = [n for n in self._names if n != name]
        self._rebuild()
        self.changed.emit()

    def _open_picker(self) -> None:
        states = {n: ALL for n in self._names}
        picker = TagPicker(self._catalog, states, self.window())
        picker.toggled.connect(self._toggled)
        self._picker = picker
        picker.popup_at(QRect(self._add.mapToGlobal(QPoint(0, 0)), self._add.size()), align="left")

    def _toggled(self, name: str, add: bool) -> None:
        if add and name not in self._names:
            self._names.append(name)
        elif not add:
            self._names = [n for n in self._names if n != name]
        self._rebuild()
        self.changed.emit()


# --------------------------------------------------------------------------------------- picker
class _PickerModel(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, int, int]] = []      # name, profiles, colour slot

    def set_items(self, items: list[tuple[str, int, int]]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return self.items[index.row()][0]
        return None


class _PickerDelegate(QStyledItemDelegate):
    def __init__(self, picker: "TagPicker") -> None:
        super().__init__(picker)
        self._picker = picker
        self._font = QFont()
        self._font.setPixelSize(13)
        self._small = QFont()
        self._small.setPixelSize(12)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        name, count, slot = self._picker.model.items[index.row()]
        state = self._picker.states.get(name, NONE)
        pal = current_palette()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row = QRectF(option.rect).adjusted(2, 1, -2, -1)
        if option.state & QStyle.StateFlag.State_MouseOver or option.widget.currentIndex() == index:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.subtle))
            painter.drawRoundedRect(row, 8, 8)
        box = QRectF(row.left() + 8, row.center().y() - 8, 16, 16)
        if state == NONE:
            painter.setPen(QPen(QColor(pal.border_strong), 1.4))
            painter.setBrush(QColor(pal.raised))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.accent))
        painter.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 5, 5)
        if state != NONE:
            draw_icon(painter, "check" if state == ALL else "minus", pal.accent_text, box.center().x() - 6,
                      box.center().y() - 6, 12, 3.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette_tags.slot_color(slot)))
        painter.drawEllipse(QRectF(box.right() + 12, row.center().y() - 4, 8, 8))
        number_w = text_width(str(count), self._small) + 4
        left = int(box.right() + 28)
        draw_text(painter, QRect(left, int(row.top()), int(row.right() - left - number_w - 10), int(row.height())),
                  name, self._font, pal.text)
        draw_text(painter, QRect(int(row.right() - number_w - 8), int(row.top()), number_w, int(row.height())),
                  str(count), self._small, pal.faint, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        painter.restore()


class TagPicker(Popover):
    """A list of every tag with a tick per tag; ``toggled(name, add)`` after each click.

    ``states`` says how many of the profiles in question carry a tag (``NONE`` / ``SOME`` / ``ALL``); a click
    on ``NONE`` or ``SOME`` means *add it to all*, a click on ``ALL`` means *remove it from all*.
    The last row creates a tag (name + colour) without leaving the list: the new tag is ticked at once.
    """

    toggled = Signal(str, bool)

    def __init__(self, catalog: Catalog, states: dict[str, int], parent: QWidget | None = None) -> None:
        super().__init__(parent, width=290, padding=10)
        self._catalog = catalog
        self.states = dict(states)
        self.body.setSpacing(8)
        self._search = SearchField(tr("tags.search"))
        self._search.textChanged.connect(self._refill)
        self.body.addWidget(self._search)

        self.model = _PickerModel()
        self._list = QListView()
        self._list.setModel(self.model)
        self._list.setItemDelegate(_PickerDelegate(self))
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setMouseTracking(True)
        self._list.viewport().setMouseTracking(True)
        self._list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setUniformItemSizes(True)
        self._list.setStyleSheet("QListView { background: transparent; }")
        self._list.clicked.connect(self._clicked)
        self._list.entered.connect(self._list.setCurrentIndex)
        self.body.addWidget(self._list)
        self._empty = label(tr("tags.none"), "small", wrap=True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self._empty)
        self.body.addWidget(divider())

        # "New tag": a row that turns into a small form
        self._new_row = Button(tr("tags.new"), "ghost", icon="plus", size="sm")
        self._new_row.clicked.connect(self._show_form)
        self.body.addWidget(self._new_row, 0, Qt.AlignmentFlag.AlignLeft)
        self._form = QWidget()
        form = QVBoxLayout(self._form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self._name = QLineEdit()
        self._name.setPlaceholderText(tr("tags.name"))
        self._name.setMaxLength(40)
        self._name.returnPressed.connect(self._create)
        form.addWidget(self._name)
        self._swatches = SwatchRow(0, per_row=6, size=28, gap=14)
        form.addWidget(self._swatches, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._error = label("", "danger")
        self._error.setVisible(False)
        row.addWidget(self._error, 1)
        cancel = Button(tr("common.cancel"), None, size="sm")
        cancel.clicked.connect(self._hide_form)
        self._create_button = Button(tr("tags.create"), "primary", size="sm")
        self._create_button.clicked.connect(self._create)
        row.addWidget(cancel)
        row.addWidget(self._create_button)
        form.addLayout(row)
        self._form.setVisible(False)
        self.body.addWidget(self._form)

        catalog.changed.connect(self._on_catalog)
        self.closed.connect(lambda: _disconnect(catalog.changed, self._on_catalog))
        self._refill()

    # ---------------------------------------------------------------- list
    def _on_catalog(self) -> None:
        self._refill()

    def _refill(self) -> None:
        query = self._search.text().strip().casefold()
        items = [(t.name, t.count, t.color) for t in self._catalog.tags if query in t.name.casefold()]
        self.model.set_items(items)
        rows = min(len(items), MAX_ROWS)
        self._list.setFixedHeight(rows * ROW_H + 2 if items else 0)
        self._list.setVisible(bool(items))
        self._empty.setVisible(not items)
        self._empty.setText(tr("tags.none.match") if self._catalog.tags else tr("tags.none"))
        self._new_row.setText(tr("tags.new.named", name=self._search.text().strip()) if query and not any(
            t.name.casefold() == query for t in self._catalog.tags) else tr("tags.new"))
        self._fit()

    def _clicked(self, index) -> None:
        name = self.model.items[index.row()][0]
        add = self.states.get(name, NONE) != ALL
        self.states[name] = ALL if add else NONE
        self._list.viewport().update()
        self.toggled.emit(name, add)

    # ---------------------------------------------------------------- create
    def _show_form(self) -> None:
        self._new_row.setVisible(False)
        self._form.setVisible(True)
        self._name.setText(self._search.text().strip())
        used = [t.color for t in self._catalog.tags]
        from antidetect.application import palette

        self._swatches.set_value(palette.least_used(used))
        self._error.setVisible(False)
        self._fit()
        self._name.setFocus()
        self._name.selectAll()

    def _hide_form(self) -> None:
        self._form.setVisible(False)
        self._new_row.setVisible(True)
        self._fit()

    def _create(self) -> None:
        name = " ".join(self._name.text().replace(",", " ").split())
        if not name:
            return
        existing = self._catalog.tag(name)
        if existing is not None:                     # it is there already: just tick it
            self._tick(existing.name)
            return
        self._create_button.setEnabled(False)
        self._catalog.create_tag(name, self._swatches.value(), on_result=lambda tag: self._created(tag.name),
                                 on_error=self._failed)

    def _created(self, name: str) -> None:
        self._create_button.setEnabled(True)
        self._search.clear()
        self._hide_form()
        self._tick(name)

    def _tick(self, name: str) -> None:
        if self.states.get(name, NONE) != ALL:
            self.states[name] = ALL
            self.toggled.emit(name, True)
        self._list.viewport().update()
        self._hide_form()

    def _failed(self, exc) -> None:
        from antidetect.gui.errors import friendly_error_text

        self._create_button.setEnabled(True)
        self._error.setText(friendly_error_text(exc))
        self._error.setVisible(True)

    def _fit(self) -> None:
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()

    def popup_at(self, anchor: QRect, *, align: str = "left", gap: int = 6) -> None:
        super().popup_at(anchor, align=align, gap=gap)
        self._search.setFocus()


def _disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


def tag_states(rows) -> dict[str, int]:
    """For the profiles ``rows``: which tags all / some of them carry."""
    if not rows:
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        for tag in row.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return {tag: ALL if n == len(rows) else SOME for tag, n in counts.items()}


_tile_cache: dict[tuple, "QIcon"] = {}


def workspace_icon(slot: int | None, name: str = "", size: int = 18):
    """A workspace as a small coloured square with its first letter (``slot=None``: the neutral "no workspace" tile)."""
    from PySide6.QtGui import QIcon, QImage, QPixmap

    dpr = ic.device_ratio()
    key = (slot, name[:1].casefold(), size, dpr, current_palette().name)
    cached = _tile_cache.get(key)
    if cached is not None:
        return cached
    pal = current_palette()
    side = round(size * dpr)
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    rect = QRectF(0.5, 0.5, side - 1, side - 1)
    if slot is None:
        painter.setBrush(QColor(pal.subtle))
        painter.drawRoundedRect(rect, side * 0.3, side * 0.3)
        glyph = ic.pixmap("layers", pal.faint, round(size * 0.66), 2.0, dpr)
        painter.drawPixmap(int((side - glyph.width()) / 2), int((side - glyph.height()) / 2), glyph)
    else:
        painter.setBrush(QColor(palette_tags.slot_color(slot)))
        painter.drawRoundedRect(rect, side * 0.3, side * 0.3)
        font = QFont()
        font.setPixelSize(max(8, round(side * 0.58)))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        letter = next((ch for ch in name.strip() if ch.isalnum()), "?").upper()
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    icon = QIcon(pixmap)
    if len(_tile_cache) > 200:
        _tile_cache.clear()
    _tile_cache[key] = icon
    return icon
