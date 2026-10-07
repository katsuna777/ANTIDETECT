"""Quick search (Ctrl/⌘ K): jump to a page, start a profile, open a tag or run an action from the keyboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui.components.avatar import paint_avatar
from antidetect.gui.components.basics import divider, label
from antidetect.gui.components.popover import RADIUS, SHADOW, paint_floating_card
from antidetect.gui.theme import current_palette
from antidetect.gui.theme.tags import tag_color
from antidetect.gui.views.paint import draw_icon, draw_text
from antidetect.i18n import tr

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_H = 46
MAX_RESULTS = 40


@dataclass(frozen=True)
class Entry:
    kind: str                     # "page" | "action" | "profile" | "tag" | "workspace"
    title: str
    subtitle: str = ""
    icon: str = "search"          # page / action glyph
    hint: str = ""                # right-hand caption ("Start", "⌘N")
    run: Callable[[], object] | None = None
    keywords: str = ""
    running: bool = False         # profiles: show the green dot
    color: str | None = None      # tags: the dot colour

    def haystack(self) -> str:
        return f"{self.title} {self.subtitle} {self.keywords}".casefold()


def rank(entries: list[Entry], query: str) -> list[Entry]:
    """Entries matching every word of ``query``, best first; without a query the natural order (capped)."""
    words = query.casefold().split()
    if not words:
        return entries[:MAX_RESULTS]
    scored: list[tuple[int, int, Entry]] = []
    for position, entry in enumerate(entries):
        hay, title = entry.haystack(), entry.title.casefold()
        if not all(word in hay for word in words):
            continue
        score = 0
        for word in words:
            if title.startswith(word):
                score += 4
            elif f" {word}" in f" {title}":
                score += 3
            elif word in title:
                score += 2
            else:
                score += 1
        scored.append((-score, position, entry))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in scored[:MAX_RESULTS]]


class _Model(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self._entries: list[Entry] = []

    def set_entries(self, entries: list[Entry]) -> None:
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        if role == ENTRY_ROLE:
            return entry
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.title
        return None


class _Delegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        entry: Entry = index.data(ENTRY_ROLE)
        pal = current_palette()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(6, 2, -6, -2)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.accent_soft))
            painter.drawRoundedRect(rect, 10, 10)
        left, cy = int(rect.left()) + 10, int(rect.center().y())
        if entry.kind == "profile":
            paint_avatar(painter, QRectF(left, cy - 15, 30, 30), entry.title, pal.is_dark, font_px=13)
        elif entry.kind == "workspace":
            tile = QRectF(left, cy - 15, 30, 30)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(entry.color or pal.subtle))
            painter.drawRoundedRect(tile, 9, 9)
            font = QFont(option.font)
            font.setPixelSize(14)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(tile, Qt.AlignmentFlag.AlignCenter,
                             next((ch for ch in entry.title if ch.isalnum()), "?").upper())
        elif entry.kind == "tag":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.subtle))
            painter.drawRoundedRect(QRectF(left, cy - 15, 30, 30), 9, 9)
            painter.setBrush(QColor(entry.color or tag_color(entry.title)))
            painter.drawEllipse(QRectF(left + 11, cy - 4, 8, 8))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.subtle))
            painter.drawRoundedRect(QRectF(left, cy - 15, 30, 30), 9, 9)
            draw_icon(painter, entry.icon, pal.text, left + 7, cy - 8, 16)
        base = option.font
        tfont, sfont = QFont(base), QFont(base)
        tfont.setPixelSize(13)
        tfont.setWeight(QFont.Weight.DemiBold)
        sfont.setPixelSize(12)
        right = int(rect.right()) - 12
        hint_w = 0
        if entry.hint:
            hfont = QFont(base)
            hfont.setPixelSize(12)
            hint_w = QFontMetrics(hfont).horizontalAdvance(entry.hint) + 8
            painter.setFont(hfont)
            painter.setPen(QColor(pal.faint))
            painter.drawText(QRect(right - hint_w - 40, int(rect.top()), hint_w + 40, int(rect.height())),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, entry.hint)
        text_left = left + 30 + 12
        text_w = right - hint_w - text_left - 8
        dot = 0
        if entry.running:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.success))
            painter.drawEllipse(QRectF(text_left, cy - 15 + 5.5, 6, 6))
            dot = 12
        top = cy - 17 if entry.subtitle else cy - 9
        draw_text(painter, QRect(text_left + dot, top, text_w - dot, 17), entry.title, tfont, pal.text)
        if entry.subtitle:
            draw_text(painter, QRect(text_left, top + 17, text_w, 16), entry.subtitle, sfont, pal.muted)
        painter.restore()


class CommandPalette(QFrame):
    """A frameless popup with a search box over a list of ``Entry``."""

    def __init__(self, entries: list[Entry], parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("Palette")
        self._entries = entries
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        outer.setSpacing(0)
        card = QWidget()
        outer.addWidget(card)
        col = self._card_layout = QVBoxLayout(card)
        col.setContentsMargins(0, 0, 0, 8)
        col.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(18, 0, 14, 0)
        head.setSpacing(10)
        from antidetect.gui.components.basics import IconLabel

        head.addWidget(IconLabel("search", "muted", 18))
        self._input = QLineEdit()
        self._input.setPlaceholderText(tr("palette.placeholder"))
        self._input.setFrame(False)
        self._input.setStyleSheet("QLineEdit { background: transparent; border: none; font-size: 15px; "
                                  "min-height: 54px; padding: 0; }")
        head.addWidget(self._input, 1)
        head.addWidget(label("esc", "faint"))
        col.addLayout(head)
        col.addWidget(divider())
        self._model = _Model()
        self._list = QListView()
        self._list.setModel(self._model)
        self._list.setItemDelegate(_Delegate(self._list))
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list.setMouseTracking(True)
        self._list.setStyleSheet("QListView { background: transparent; }")
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.viewport().setMouseTracking(True)
        col.addWidget(self._list)
        self._empty = label(tr("palette.empty"), "muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setFixedHeight(80)
        col.addWidget(self._empty)
        self._input.textChanged.connect(self._refilter)
        self._input.installEventFilter(self)
        self._list.clicked.connect(lambda index: self._activate(index.row()))
        self._list.entered.connect(lambda index: self._list.setCurrentIndex(index))
        self.setFixedWidth(600 + 2 * SHADOW)
        self._refilter("")

    # ------------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_floating_card(painter, QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW), radius=RADIUS + 2)

    # ------------------------------------------------------------------ behaviour
    def _refilter(self, text: str) -> None:
        found = rank(self._entries, text)
        self._model.set_entries(found)
        self._list.setVisible(bool(found))
        self._empty.setVisible(not found)
        rows = min(len(found), 8)
        self._list.setFixedHeight(rows * ROW_H + 4 if found else 0)
        if found:
            self._list.setCurrentIndex(self._model.index(0))
        self._card_layout.invalidate()      # size hints are re-read lazily: do it now, the popup is sized from them
        self._card_layout.activate()
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        self.setFixedHeight(layout.sizeHint().height())

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                step = 1 if key == Qt.Key.Key_Down else -1
                count = self._model.rowCount()
                if count:
                    self._list.setCurrentIndex(self._model.index((self._list.currentIndex().row() + step) % count))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate(self._list.currentIndex().row())
                return True
        return super().eventFilter(obj, event)

    def _activate(self, row: int) -> None:
        entry = self._model.data(self._model.index(row), ENTRY_ROLE) if row >= 0 else None
        self.close()
        if entry is not None and entry.run is not None:
            entry.run()

    def popup_over(self, window: QWidget) -> None:
        self.adjustSize()
        card_w = self.width() - 2 * SHADOW
        top_left = window.mapToGlobal(QPoint((window.width() - card_w) // 2, max(40, window.height() // 7)))
        self.move(top_left.x() - SHADOW, top_left.y() - SHADOW)
        self.show()
        self._input.setFocus()

    def results(self) -> list[Entry]:
        return [self._model.data(self._model.index(i), ENTRY_ROLE) for i in range(self._model.rowCount())]

    def set_query(self, text: str) -> None:
        self._input.setText(text)
