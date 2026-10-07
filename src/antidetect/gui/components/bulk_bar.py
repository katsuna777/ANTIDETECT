"""A floating action bar that appears at the bottom of a list while several rows are selected."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QWidget

from antidetect.gui.components.basics import Button, IconButton, label
from antidetect.gui.components.popover import SHADOW, paint_floating_card
from antidetect.i18n import tr


class BulkBar(QFrame):
    startRequested = Signal()
    stopRequested = Signal()
    deleteRequested = Signal()
    tagsRequested = Signal(object)          # the button (to anchor the picker under)
    workspaceRequested = Signal(object)
    clearRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BulkBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(SHADOW + 14, SHADOW + 8, SHADOW + 8, SHADOW + 8)
        row.setSpacing(8)
        self._count = label("", "h3")
        self._start = Button(tr("bulk.start"), "soft", icon="play", size="sm")
        self._stop = Button(tr("bulk.stop"), "soft", icon="stop", size="sm")
        self._tags = Button(tr("bulk.tags"), "soft", icon="tag", size="sm")
        self._workspace = Button(tr("bulk.workspace"), "soft", icon="briefcase", size="sm")
        self._delete = Button(tr("bulk.delete"), "soft", icon="trash", size="sm")
        self._clear = IconButton("x", tr("bulk.clear"), size=16)
        self._start.clicked.connect(self.startRequested)
        self._stop.clicked.connect(self.stopRequested)
        self._tags.clicked.connect(lambda: self.tagsRequested.emit(self._tags))
        self._workspace.clicked.connect(lambda: self.workspaceRequested.emit(self._workspace))
        self._delete.clicked.connect(self.deleteRequested)
        self._clear.clicked.connect(self.clearRequested)
        for widget in (self._count, self._start, self._stop, self._tags, self._workspace, self._delete, self._clear):
            row.addWidget(widget)
        row.insertSpacing(1, 6)
        self.setVisible(False)

    def set_count(self, count: int) -> None:
        self._count.setText(tr("bulk.selected", n=count))
        self.adjustSize()

    def retranslate(self) -> None:
        self._start.setText(tr("bulk.start"))
        self._stop.setText(tr("bulk.stop"))
        self._tags.setText(tr("bulk.tags"))
        self._workspace.setText(tr("bulk.workspace"))
        self._delete.setText(tr("bulk.delete"))
        self._clear.setToolTip(tr("bulk.clear"))
        self.adjustSize()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_floating_card(painter, QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW), radius=16)

    def place(self, host: QWidget) -> None:
        """Centre the card near the bottom of ``host``."""
        self.adjustSize()
        card_w = self.width() - 2 * SHADOW
        self.move((host.width() - card_w) // 2 - SHADOW, host.height() - self.height() + SHADOW - 14)
        self.raise_()


class TrashBar(QFrame):
    """The same floating card for the trash: restore or delete the ticked profiles."""

    restoreRequested = Signal()
    purgeRequested = Signal()
    clearRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BulkBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(SHADOW + 14, SHADOW + 8, SHADOW + 8, SHADOW + 8)
        row.setSpacing(8)
        self._count = label("", "h3")
        self._restore = Button(tr("trash.restore"), "soft", icon="rotate-ccw", size="sm")
        self._purge = Button(tr("trash.purge"), "soft", icon="trash", size="sm")
        self._clear = IconButton("x", tr("bulk.clear"), size=16)
        self._restore.clicked.connect(self.restoreRequested)
        self._purge.clicked.connect(self.purgeRequested)
        self._clear.clicked.connect(self.clearRequested)
        for widget in (self._count, self._restore, self._purge, self._clear):
            row.addWidget(widget)
        row.insertSpacing(1, 6)
        self.setVisible(False)

    def set_count(self, count: int) -> None:
        self._count.setText(tr("bulk.selected", n=count))
        self.adjustSize()

    def retranslate(self) -> None:
        self._restore.setText(tr("trash.restore"))
        self._purge.setText(tr("trash.purge"))
        self._clear.setToolTip(tr("bulk.clear"))
        self.adjustSize()

    paintEvent = BulkBar.paintEvent
    place = BulkBar.place
