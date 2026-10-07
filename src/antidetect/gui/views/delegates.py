"""Cell painters for the profile and proxy tables.

Everything is painted by hand: rounded hover / selection rows, avatars, flags, the little
white cards (status, cookies, dates), the round Start / Stop button and the proxy buttons.
Fonts are cached per delegate and colours come from the live palette, so a theme switch needs
only a repaint.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from antidetect.gui.components.avatar import paint_avatar
from antidetect.gui.models import profiles as pm
from antidetect.gui.models import proxies as xm
from antidetect.gui.models import trash as tm
from antidetect.gui.models.roles import BUSY_ROLE, CHECKING_ROLE, CHIPS_ROLE, ROW_ROLE, SUB_ROLE
from antidetect.gui.theme import current_palette
from antidetect.gui.theme.tags import slot_color, tag_color
from antidetect.gui.views.paint import (
    draw_card,
    draw_flag,
    draw_icon,
    draw_spinner,
    draw_text,
    elide,
    text_width,
)
from antidetect.gui.views.table import CELL_PAD
from antidetect.gui.countries import country_name
from antidetect.i18n import tr

PROFILE_ROW_HEIGHT = 64
PROXY_ROW_HEIGHT = 58
_RADIUS = 12


class _BaseDelegate(QStyledItemDelegate):
    ROW_HEIGHT = PROFILE_ROW_HEIGHT

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fonts: dict[tuple[int, int], QFont] = {}

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def font(self, base: QFont, px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        key = (px, int(weight))
        cached = self._fonts.get(key)
        if cached is None:
            cached = QFont(base)
            cached.setPixelSize(px)
            cached.setWeight(weight)
            self._fonts[key] = cached
        return cached

    # ------------------------------------------------------------ row chrome
    @staticmethod
    def paint_row(painter: QPainter, option, index) -> None:
        """Rounded hover / selection fill spanning the whole row (drawn cell by cell, joined)."""
        table = option.widget
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = getattr(table, "hover_row", -1) == index.row()
        if not (selected or hovered):
            return
        pal = current_palette()
        _BaseDelegate._joined_card(painter, option.rect, index, QColor(pal.accent_soft if selected else pal.hover))

    @staticmethod
    def _joined_card(painter: QPainter, rect: QRect, index, fill: QColor, border: QColor | None = None) -> None:
        """One rounded card across the whole row; each cell paints its own slice of it, so the slices join."""
        last_column = index.column() == index.model().columnCount() - 1
        first_column = index.column() == 0
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(rect)
        painter.setPen(QPen(border, 1) if border is not None else Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        left = rect.left() if first_column else rect.left() - _RADIUS
        right = rect.right() + 1 if last_column else rect.right() + 1 + _RADIUS
        path = QPainterPath()
        inset = 0.5 if border is not None else 0.0          # keep a hairline inside the clip
        path.addRoundedRect(QRectF(left + (inset if first_column else 0), rect.top() + 2 + inset,
                                   right - left - (inset if first_column else 0) - (inset if last_column else 0),
                                   rect.height() - 4 - 2 * inset), _RADIUS, _RADIUS)
        painter.drawPath(path)
        painter.restore()

    def begin_row(self, painter: QPainter, option, index):
        """Paint the row's background and return the option to paint its cells with.

        A row with an open drawer is taller than usual: its card covers all of it, but the cells are laid out
        in the first ``ROW_HEIGHT`` pixels, exactly as in any other row.
        """
        extra = option.widget.expansion_extra(index.row()) if hasattr(option.widget, "expansion_extra") else 0
        if not extra:
            self.paint_row(painter, option, index)
            return option
        pal = current_palette()
        self._joined_card(painter, option.rect, index, QColor(pal.drawer), QColor(pal.border))
        band = QStyleOptionViewItem(option)
        band.rect = QRect(option.rect.left(), option.rect.top(), option.rect.width(), self.ROW_HEIGHT)
        return band

    def band(self, rect: QRect, table, index) -> QRect:
        """The cell's rectangle with the drawer's space cut off (events and hit tests use this)."""
        if hasattr(table, "expansion_extra") and table.expansion_extra(index.row()):
            return QRect(rect.left(), rect.top(), rect.width(), self.ROW_HEIGHT)
        return rect

    AVATAR = 40
    catalog = None            # set by the page: where the names and colours of workspaces come from

    def avatar_rect(self, cell: QRect) -> QRect:
        return QRect(cell.left() + CELL_PAD, cell.center().y() - self.AVATAR // 2 + 1, self.AVATAR, self.AVATAR)

    def shows_check(self, table, index) -> bool:
        """The avatar turns into a checkbox under the pointer, and on every row once any is selected."""
        if getattr(table, "hover_row", -1) == index.row():
            return True
        selection = table.selectionModel()
        return selection is not None and selection.hasSelection()

    def _paint_name(self, painter: QPainter, inner: QRect, row, base: QFont, index, option) -> None:
        pal = current_palette()
        size = self.AVATAR
        tile = QRectF(self.avatar_rect(option.rect))
        if self.shows_check(option.widget, index):
            # the avatar turns into a checkbox: the same rounded square, ticked = filled with the accent
            checked = bool(option.state & QStyle.StateFlag.State_Selected)
            corner = tile.height() * 0.3
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.accent if checked else pal.subtle))
            painter.drawRoundedRect(tile, corner, corner)
            if checked:
                draw_icon(painter, "check", pal.accent_text, tile.center().x() - 9, tile.center().y() - 9, 18, 2.6)
            else:
                box = QRectF(tile.center().x() - 10, tile.center().y() - 10, 20, 20)
                painter.setPen(QPen(QColor(pal.border_strong), 1.5))
                painter.setBrush(QColor(pal.surface))
                painter.drawRoundedRect(box.adjusted(0.75, 0.75, -0.75, -0.75), 6, 6)
        else:
            paint_avatar(painter, tile, row.name, pal.is_dark)
        text_left = inner.left() + size + 12
        text_w = inner.right() - text_left
        tfont, sfont, cfont = self.font(base, 13, QFont.Weight.DemiBold), self.font(base, 12), self.font(base, 11, QFont.Weight.Medium)
        sub = str(index.data(SUB_ROLE) or "")
        top = inner.center().y() - (16 + 2 + 15) // 2 + 1
        name_w = min(text_width(row.name, tfont), text_w)
        draw_text(painter, QRect(text_left, top, text_w, 16), row.name, tfont, pal.text)
        # tags ride on the name line, as many as fit
        x, tags = text_left + name_w + 10, list(index.data(CHIPS_ROLE) or ())
        shown = [(tag, tag_color(tag)) for tag in tags[:2]]
        if len(tags) > 2:
            shown.append((f"+{len(tags) - 2}", None))
        for label, color in shown:
            width = text_width(label, cfont) + 14 + (11 if color else 0)
            if x + width > text_left + text_w:
                break
            chip = QRectF(x, top - 1, width, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.subtle))
            painter.drawRoundedRect(chip, 6, 6)
            cx = x + 7
            if color:
                painter.setBrush(QColor(color))
                painter.drawEllipse(QRectF(cx, chip.center().y() - 2.5, 5, 5))
                cx += 11
            painter.setFont(cfont)
            painter.setPen(QColor(pal.muted))
            painter.drawText(QRectF(cx, chip.top(), width - (cx - x) - 7, 18), Qt.AlignmentFlag.AlignVCenter, label)
            x += width + 5
        draw_text(painter, QRect(text_left, top + 18, text_w, 15), sub, sfont, pal.muted)
        self._paint_workspace(painter, row, QRect(text_left, top + 18, text_w, 15), sub, sfont)

    def _paint_workspace(self, painter: QPainter, row, line: QRect, sub: str, font: QFont) -> None:
        """After "Windows · Chrome 154": a small tile in the workspace's colour and its name."""
        item = self.catalog.workspace(row.workspace_id) if self.catalog is not None else None
        if item is None:
            return
        pal = current_palette()
        x = line.left() + min(text_width(sub, font), line.width()) + 10
        room = line.right() - x
        if room < 40:
            return
        tile = QRectF(x, line.center().y() - 5, 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(slot_color(item.color)))
        painter.drawRoundedRect(tile, 3, 3)
        draw_text(painter, QRect(int(x) + 15, line.top(), room - 15, line.height()), item.name, font, pal.muted)

    def pill(self, painter: QPainter, left: int, center_y: int, text: str, font: QFont, fg: str, *,
             dot: str | None = None, icon: str | None = None, fill: str | None = None, border: str | None = None,
             shadow: bool = True, max_width: int = 10_000, height: int = 28) -> int:
        """A small card with a label (and a dot or an icon); returns its width."""
        pal = current_palette()
        pad = 11
        lead = 14 if dot else 20 if icon else 0
        text = elide(text, font, max(24, max_width - 2 * pad - lead))
        width = text_width(text, font) + 2 * pad + lead
        rect = QRectF(left, center_y - height / 2, width, height)
        draw_card(painter, rect, pal, fill=fill, border=border, shadow=shadow)
        x = left + pad
        if dot:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(dot))
            painter.drawEllipse(QRectF(x, center_y - 3, 6, 6))
            painter.restore()
            x += 14
        elif icon:
            draw_icon(painter, icon, fg, x, center_y - 7, 14, 1.9)
            x += 20
        painter.setFont(font)
        painter.setPen(QColor(fg))
        painter.drawText(QRectF(x, rect.top(), width - (x - left) - pad, height),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        return int(width)

    def two_lines(self, painter: QPainter, rect: QRect, title: str, sub: str, base: QFont, *,
                  title_weight=QFont.Weight.Normal, title_color: str | None = None, sub_color: str | None = None) -> None:
        pal = current_palette()
        tfont, sfont = self.font(base, 13, title_weight), self.font(base, 12)
        theight, sheight = 16, 15
        total = theight + (sheight + 2 if sub else 0)
        top = rect.top() + (rect.height() - total) // 2
        draw_text(painter, QRect(rect.left(), top, rect.width(), theight), title, tfont, title_color or pal.text)
        if sub:
            draw_text(painter, QRect(rect.left(), top + theight + 2, rect.width(), sheight), sub, sfont,
                      sub_color or pal.muted)


class ProfileDelegate(_BaseDelegate):
    """Profile rows. Emits ``actionClicked`` / ``menuClicked`` / ``proxyCheckClicked`` / ``proxyInfoClicked``."""

    actionClicked = Signal(object)            # index
    menuClicked = Signal(object, object)      # index, global position
    proxyCheckClicked = Signal(object)        # index
    proxyInfoClicked = Signal(object, object)  # index, global QRect of the info button

    PLAY, MORE, SMALL = 34, 32, 26
    BUTTON_W, BUTTON_H = PLAY, PLAY            # the Start / Stop button (kept for callers that size against it)

    # ------------------------------------------------------------- geometry
    def play_rect(self, cell: QRect) -> QRect:
        return QRect(cell.left() + CELL_PAD, cell.center().y() - self.PLAY // 2 + 1, self.PLAY, self.PLAY)

    action_rect = play_rect

    def more_rect(self, cell: QRect) -> QRect:
        return QRect(cell.right() - CELL_PAD - self.MORE + 1, cell.center().y() - self.MORE // 2 + 1, self.MORE, self.MORE)

    def check_rect(self, cell: QRect) -> QRect:
        return QRect(cell.left() + CELL_PAD, cell.center().y() - self.SMALL // 2 + 1, self.SMALL, self.SMALL)

    def info_rect(self, cell: QRect) -> QRect:
        return self.check_rect(cell).translated(self.SMALL + 2, 0)

    def hotspot(self, index, pos: QPoint, table) -> bool:
        column = index.column()
        if column not in (pm.COL_PLAY, pm.COL_MORE, pm.COL_PROXY, pm.COL_NAME):
            return False
        cell = self.band(table.visualRect(index), table, index)
        if column == pm.COL_NAME:
            return self.avatar_rect(cell).contains(pos) and self.shows_check(table, index)
        if column == pm.COL_PLAY:
            return self.play_rect(cell).contains(pos)
        if column == pm.COL_MORE:
            return self.more_rect(cell).contains(pos)
        row = index.data(ROW_ROLE)
        return row is not None and row.proxy_endpoint is not None and (
            self.check_rect(cell).contains(pos) or self.info_rect(cell).contains(pos))

    # --------------------------------------------------------------- paint
    def paint(self, painter: QPainter, option, index) -> None:
        option = self.begin_row(painter, option, index)
        row = index.data(ROW_ROLE)
        if row is None:
            return
        pal = current_palette()
        column = index.column()
        inner = option.rect.adjusted(CELL_PAD, 0, -CELL_PAD, 0)
        base = option.font
        model = index.model()
        busy = model.busy(row.id)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if column == pm.COL_PLAY:
            self._paint_play(painter, option, row, busy)
        elif column == pm.COL_NAME:
            self._paint_name(painter, inner, row, base, index, option)
        elif column == pm.COL_PROXY:
            self._paint_proxy(painter, option, row, base, model.checking(row.id))
        elif column == pm.COL_STATUS:
            if busy:
                fg, dot, fill, shadow = pal.warning, pal.warning, pal.warning_soft, False
            elif row.running:
                fg, dot, fill, shadow = pal.success, pal.success, pal.success_soft, False
            else:
                fg, dot, fill, shadow = pal.muted, pal.faint, None, True
            self.pill(painter, inner.left(), inner.center().y() + 1, pm.status_text(row, busy),
                      self.font(base, 12, QFont.Weight.Medium), fg, dot=dot, fill=fill,
                      border=fill if fill else None, shadow=shadow, max_width=inner.width())
        elif column == pm.COL_COOKIES:
            count = row.cookie_count
            if count:
                self.pill(painter, inner.left(), inner.center().y() + 1, pm.count_text(count),
                          self.font(base, 12, QFont.Weight.Medium), pal.warning, icon="cookie",
                          fill=pal.warning_soft, border=pal.warning_soft, shadow=False, max_width=inner.width())
            else:
                self.pill(painter, inner.left(), inner.center().y() + 1, pm.count_text(count),
                          self.font(base, 12, QFont.Weight.Medium), pal.faint, icon="cookie",
                          max_width=inner.width())
        elif column in (pm.COL_LAST, pm.COL_CREATED):
            text = str(index.data())
            never = text in ("—", tr("common.never"))
            self.pill(painter, inner.left(), inner.center().y() + 1, text, self.font(base, 12),
                      pal.faint if never else pal.text, max_width=inner.width())
        elif column == pm.COL_MORE:
            self._paint_more(painter, option)
        painter.restore()

    def _paint_play(self, painter: QPainter, option, row, busy) -> None:
        pal = current_palette()
        table = option.widget
        pos = getattr(table, "hover_pos", QPoint(-1, -1))
        rect = QRectF(self.play_rect(option.rect))
        over = rect.contains(pos) and not busy
        corner = rect.width() * 0.3
        if busy:
            draw_card(painter, rect, pal, radius=corner, shadow=False)
            draw_spinner(painter, rect.center().x(), rect.center().y(), pal.muted, getattr(table, "spin_phase", 0), 16)
        elif row.running:
            fill = pal.danger if over else pal.danger_soft
            draw_card(painter, rect, pal, radius=corner, fill=fill, border=fill, shadow=False)
            draw_icon(painter, "stop-fill", pal.danger_text if over else pal.danger,
                      rect.center().x() - 8, rect.center().y() - 8, 16)
        else:
            fill = pal.accent if over else pal.pill
            draw_card(painter, rect, pal, radius=corner, fill=fill, border=pal.accent if over else None)
            draw_icon(painter, "play-fill", pal.accent_text if over else pal.text,
                      rect.center().x() - 7, rect.center().y() - 8, 16)

    def _paint_proxy(self, painter: QPainter, option, row, base: QFont, checking: bool) -> None:
        pal = current_palette()
        table = option.widget
        pos = getattr(table, "hover_pos", QPoint(-1, -1))
        cell = option.rect
        if row.proxy_endpoint is None:
            self.two_lines(painter, cell.adjusted(CELL_PAD, 0, -CELL_PAD, 0), tr("proxy.none"), "", base,
                           title_color=pal.faint)
            return
        # [refresh] [info]  (flag)  endpoint / country · ping
        for rect, glyph in ((self.check_rect(cell), "refresh"), (self.info_rect(cell), "info")):
            if rect.contains(pos):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(pal.subtle))
                painter.drawRoundedRect(QRectF(rect), 8, 8)
            if glyph == "refresh" and checking:
                draw_spinner(painter, rect.center().x() + 0.5, rect.center().y() + 0.5, pal.accent,
                             getattr(table, "spin_phase", 0), 15)
            else:
                draw_icon(painter, glyph, pal.text if rect.contains(pos) else pal.muted,
                          rect.center().x() - 7.5, rect.center().y() - 7.5, 15, 1.8)
        flag_x = self.info_rect(cell).right() + 12 + 12
        code = row.proxy_country_code
        draw_flag(painter, flag_x, cell.center().y() + 1, code, pal, 24)
        dot = {"WORKING": pal.success, "DEAD": pal.danger, "ERROR": pal.warning}.get(row.proxy_status or "")
        if dot:
            painter.setPen(QPen(QColor(pal.surface), 1.5))
            painter.setBrush(QColor(dot))
            painter.drawEllipse(QRectF(flag_x + 6, cell.center().y() + 8, 8, 8))
        text_left = int(flag_x + 12 + 10)
        rect = QRect(text_left, cell.top(), cell.right() - CELL_PAD - text_left, cell.height())
        sub = " · ".join(
            part for part in (country_name(code, row.proxy_country) if code or row.proxy_country else "",
                              f"{row.proxy_latency} ms" if row.proxy_latency else "",
                              tr("proxy.free.tag") if row.proxy_free else "") if part
        )
        self.two_lines(painter, rect, row.proxy_endpoint, sub, base, title_weight=QFont.Weight.Medium)

    def _paint_more(self, painter: QPainter, option) -> None:
        pal = current_palette()
        pos = getattr(option.widget, "hover_pos", QPoint(-1, -1))
        rect = self.more_rect(option.rect)
        if rect.contains(pos):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.subtle))
            painter.drawRoundedRect(QRectF(rect), 9, 9)
        draw_icon(painter, "more", pal.text if rect.contains(pos) else pal.muted, rect.center().x() - 9, rect.center().y() - 9, 18)

    # --------------------------------------------------------------- input
    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if event.type() not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            return False                      # keys (Space asks the delegate too) are the view's business
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        cell = self.band(option.rect, option.widget, index)
        if (index.column() == pm.COL_NAME and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
                and self.avatar_rect(cell).contains(event.position().toPoint())
                and self.shows_check(option.widget, index)):
            if event.type() == QEvent.Type.MouseButtonPress:     # the checkbox: toggle just this row
                option.widget.selectionModel().select(
                    index, QItemSelectionModel.SelectionFlag.Toggle | QItemSelectionModel.SelectionFlag.Rows)
            return True
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        point = event.position().toPoint()
        column = index.column()
        if column == pm.COL_NAME:
            return False
        if column == pm.COL_PLAY:
            if self.play_rect(cell).contains(point) and not model.data(index, BUSY_ROLE):
                self.actionClicked.emit(index)
                return True
        elif column == pm.COL_MORE:
            if self.more_rect(cell).contains(point):
                self.menuClicked.emit(index, event.globalPosition().toPoint())
                return True
        elif column == pm.COL_PROXY:
            row = model.data(index, ROW_ROLE)
            if row is not None and row.proxy_endpoint is not None:
                if self.check_rect(cell).contains(point):
                    if not model.data(index, CHECKING_ROLE):
                        self.proxyCheckClicked.emit(index)
                    return True
                info = self.info_rect(cell)
                if info.contains(point):
                    top_left = option.widget.viewport().mapToGlobal(info.topLeft())
                    self.proxyInfoClicked.emit(index, QRect(top_left, info.size()))
                    return True
        return False


class TrashDelegate(_BaseDelegate):
    """Rows of the trash: who, when it was deleted, how long it stays, and the two buttons."""

    restoreClicked = Signal(object)           # index
    purgeClicked = Signal(object)             # index

    BUTTON = 32

    def restore_rect(self, cell: QRect) -> QRect:
        return QRect(cell.right() - CELL_PAD - 2 * self.BUTTON - 6 + 1, cell.center().y() - self.BUTTON // 2 + 1,
                     self.BUTTON, self.BUTTON)

    def purge_rect(self, cell: QRect) -> QRect:
        return self.restore_rect(cell).translated(self.BUTTON + 6, 0)

    def hotspot(self, index, pos: QPoint, table) -> bool:
        column = index.column()
        cell = self.band(table.visualRect(index), table, index)
        if column == tm.COL_NAME:
            return self.avatar_rect(cell).contains(pos) and self.shows_check(table, index)
        if column == tm.COL_ACTIONS:
            return self.restore_rect(cell).contains(pos) or self.purge_rect(cell).contains(pos)
        return False

    def paint(self, painter: QPainter, option, index) -> None:
        self.paint_row(painter, option, index)
        row = index.data(ROW_ROLE)
        if row is None:
            return
        pal = current_palette()
        column = index.column()
        inner = option.rect.adjusted(CELL_PAD, 0, -CELL_PAD, 0)
        base = option.font
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if column == tm.COL_NAME:
            self._paint_name(painter, inner, row, base, index, option)
        elif column == tm.COL_DELETED:
            self.pill(painter, inner.left(), inner.center().y() + 1, str(index.data()), self.font(base, 12),
                      pal.text, max_width=inner.width())
        elif column == tm.COL_LEFT:
            left = tm.days_left(row, index.model().retention_days)
            soon = left is not None and left <= 3
            self.pill(painter, inner.left(), inner.center().y() + 1, str(index.data()),
                      self.font(base, 12, QFont.Weight.Medium), pal.warning if soon else pal.muted,
                      icon="clock", fill=pal.warning_soft if soon else None,
                      border=pal.warning_soft if soon else None, shadow=not soon, max_width=inner.width())
        elif column == tm.COL_COOKIES:
            count = row.cookie_count
            self.pill(painter, inner.left(), inner.center().y() + 1, pm.count_text(count),
                      self.font(base, 12, QFont.Weight.Medium), pal.warning if count else pal.faint, icon="cookie",
                      fill=pal.warning_soft if count else None, border=pal.warning_soft if count else None,
                      shadow=not count, max_width=inner.width())
        elif column == tm.COL_ACTIONS:
            pos = getattr(option.widget, "hover_pos", QPoint(-1, -1))
            for rect, glyph, danger in ((self.restore_rect(option.rect), "rotate-ccw", False),
                                        (self.purge_rect(option.rect), "trash", True)):
                over = rect.contains(pos)
                if over:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(pal.danger_soft if danger else pal.subtle))
                    painter.drawRoundedRect(QRectF(rect), 10, 10)
                tint = pal.danger if danger and over else pal.text if over else pal.muted
                draw_icon(painter, glyph, tint, rect.center().x() - 9, rect.center().y() - 9, 18, 1.8)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if event.type() not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        point = event.position().toPoint()
        if (index.column() == tm.COL_NAME and self.avatar_rect(option.rect).contains(point)
                and self.shows_check(option.widget, index)):
            if event.type() == QEvent.Type.MouseButtonPress:
                option.widget.selectionModel().select(
                    index, QItemSelectionModel.SelectionFlag.Toggle | QItemSelectionModel.SelectionFlag.Rows)
            return True
        if event.type() != QEvent.Type.MouseButtonRelease or index.column() != tm.COL_ACTIONS:
            return False
        if self.restore_rect(option.rect).contains(point):
            self.restoreClicked.emit(index)
            return True
        if self.purge_rect(option.rect).contains(point):
            self.purgeClicked.emit(index)
            return True
        return False


class ProxyDelegate(_BaseDelegate):
    ROW_HEIGHT = PROXY_ROW_HEIGHT

    def paint(self, painter: QPainter, option, index) -> None:
        self.paint_row(painter, option, index)
        row = index.data(ROW_ROLE)
        if row is None:
            return
        pal = current_palette()
        column = index.column()
        inner = option.rect.adjusted(CELL_PAD, 0, -CELL_PAD, 0)
        base = option.font
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if column == xm.COL_ADDRESS:
            draw_flag(painter, inner.left() + 14, inner.center().y() + 1, row.country_code, pal, 28)
            self.two_lines(painter, QRect(inner.left() + 40, inner.top(), inner.width() - 40, inner.height()),
                           row.address, str(index.data(SUB_ROLE) or ""), base, title_weight=QFont.Weight.DemiBold)
        elif column == xm.COL_COUNTRY:
            name = country_name(row.country_code, row.country) if (row.country_code or row.country) else "—"
            draw_text(painter, inner, name, self.font(base, 13), pal.text if name != "—" else pal.faint)
        elif column == xm.COL_PING:
            ms = row.latency_ms
            color = pal.faint if not ms else pal.success if ms < 400 else pal.warning if ms < 1200 else pal.danger
            draw_text(painter, inner, str(index.data()), self.font(base, 13, QFont.Weight.Medium), color)
        elif column == xm.COL_STATUS:
            busy = index.data(BUSY_ROLE)
            if busy:
                fg, fill = pal.warning, pal.warning_soft
            else:
                fg, fill = {
                    "WORKING": (pal.success, pal.success_soft),
                    "DEAD": (pal.danger, pal.danger_soft),
                    "ERROR": (pal.warning, pal.warning_soft),
                }.get(row.status, (pal.muted, None))
            self.pill(painter, inner.left(), inner.center().y() + 1, str(index.data()), self.font(base, 12, QFont.Weight.Medium),
                      fg, dot=fg if fill else pal.faint, fill=fill, border=fill, shadow=fill is None,
                      max_width=inner.width())
        else:
            text = str(index.data())
            draw_text(painter, inner, text, self.font(base, 13), pal.faint if text in ("—", "") else pal.text)
        painter.restore()
