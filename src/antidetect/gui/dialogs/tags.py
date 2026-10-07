"""Manage tags: add, rename, recolour and delete them in one list."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from antidetect.gui.catalog import Catalog, TagItem
from antidetect.gui.components import BaseDialog, Button, IconButton, confirm, label
from antidetect.gui.components.popover import Popover
from antidetect.gui.components.tags import SwatchRow
from antidetect.gui.errors import friendly_error_text
from antidetect.gui.theme import tags as palette_tags
from antidetect.i18n import tr


class _ColorButton(QAbstractButton):
    """The tag's colour as a rounded square; a click opens the swatches."""

    def __init__(self, slot: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.slot = slot
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(26, 26)
        self.setToolTip(tr("tags.color.tip"))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette_tags.slot_color(self.slot)))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)
        if self.underMouse():
            painter.setBrush(QColor(255, 255, 255, 40))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()


class _TagRow(QFrame):
    def __init__(self, item: TagItem, dialog: "TagManagerDialog") -> None:
        super().__init__()
        self._item, self._dialog = item, dialog
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(10)
        self._color = _ColorButton(item.color)
        self._color.clicked.connect(self._pick_color)
        self.name = QLineEdit(item.name)
        self.name.setMaxLength(40)
        self.name.setProperty("role", "inline")
        self.name.editingFinished.connect(self._rename)
        count = label(tr("tags.count", n=item.count), "small")
        count.setMinimumWidth(110)
        count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        remove = IconButton("trash", tr("tags.delete.tip"), size=16)
        remove.clicked.connect(self._delete)
        row.addWidget(self._color)
        row.addWidget(self.name, 1)
        row.addWidget(count)
        row.addWidget(remove)

    def _rename(self) -> None:
        text = " ".join(self.name.text().replace(",", " ").split())
        if not text or text == self._item.name:
            self.name.setText(self._item.name)
            return
        self._dialog.rename(self._item, text, self.name)

    def _pick_color(self) -> None:
        popover = Popover(self.window(), width=250, padding=10)
        swatches = SwatchRow(self._item.color, per_row=6, size=28, gap=14)
        popover.body.addWidget(swatches, 0, Qt.AlignmentFlag.AlignHCenter)

        def chosen(slot: int) -> None:
            self._color.slot = slot
            self._color.update()
            self._dialog.catalog.recolor_tag(self._item.id, slot)
            popover.close()

        swatches.changed.connect(chosen)
        self._dialog._popover = popover
        popover.popup_at(QRect(self._color.mapToGlobal(QPoint(0, 0)), self._color.size()), align="left")

    def _delete(self) -> None:
        self._dialog.remove(self._item)


class TagManagerDialog(BaseDialog):
    def __init__(self, catalog: Catalog, parent: QWidget | None = None) -> None:
        super().__init__(tr("tags.manage.title"), tr("tags.manage.subtitle"), parent=parent, width=560)
        self.catalog = catalog
        self._popover: Popover | None = None
        add = QHBoxLayout()
        add.setSpacing(8)
        self._new = QLineEdit()
        self._new.setPlaceholderText(tr("tags.name"))
        self._new.setMaxLength(40)
        self._new.returnPressed.connect(self._create)
        self._add = Button(tr("tags.create"), "primary", icon="plus")
        self._add.clicked.connect(self._create)
        add.addWidget(self._new, 1)
        add.addWidget(self._add)
        self.body.addLayout(add)
        self._error = label("", "danger")
        self._error.setVisible(False)
        self.body.addWidget(self._error)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(300)
        self._inner = QWidget()
        self._rows = QVBoxLayout(self._inner)
        self._rows.setContentsMargins(0, 4, 0, 4)
        self._rows.setSpacing(0)
        self._scroll.setWidget(self._inner)
        self.body.addWidget(self._scroll, 1)
        self._empty = label(tr("tags.none"), "muted", wrap=True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self._empty)
        self.add_footer_button(tr("common.close"), "primary", self.accept)
        catalog.changed.connect(self._refill)
        self.finished.connect(lambda _=0: _disconnect(catalog.changed, self._refill))
        self._refill()

    def _refill(self) -> None:
        if any(isinstance(w, QLineEdit) and w.hasFocus() for w in self.findChildren(QLineEdit)
               if w is not self._new):                      # do not pull a name away while it is typed
            return
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for item in sorted(self.catalog.tags, key=lambda t: t.name.casefold()):
            self._rows.addWidget(_TagRow(item, self))
        self._rows.addStretch(1)
        self._empty.setVisible(not self.catalog.tags)
        self._scroll.setVisible(bool(self.catalog.tags))

    def _show_error(self, text: str) -> None:
        self._error.setText(text)
        self._error.setVisible(bool(text))

    def _create(self) -> None:
        name = " ".join(self._new.text().replace(",", " ").split())
        if not name:
            return
        self._show_error("")
        self.catalog.create_tag(name, on_result=lambda _tag: self._new.clear(),
                                on_error=lambda exc: self._show_error(friendly_error_text(exc)))

    def rename(self, item: TagItem, name: str, edit: QLineEdit) -> None:
        self._show_error("")

        def failed(exc) -> None:
            edit.setText(item.name)
            self._show_error(friendly_error_text(exc))

        self.catalog.rename_tag(item.id, name, on_error=failed)

    def remove(self, item: TagItem) -> None:
        if item.count and not confirm(self, tr("tags.delete.title", name=item.name),
                                      tr("tags.delete.text", n=item.count), tr("common.delete"), danger=True):
            return
        self.catalog.delete_tag(item.id)


def _disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):
        pass
