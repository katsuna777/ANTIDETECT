"""Feedback widgets: empty state, callout banner, toasts."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui.components.basics import Button, IconLabel, label, repolish
from antidetect.gui.theme import current_palette
from antidetect.gui.theme import icons as ic
from antidetect.i18n import tr


class EmptyState(QWidget):
    """Centered call to action shown when a list has nothing to show yet."""

    def __init__(self, icon_name: str = "user", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile = QFrame()
        tile.setProperty("role", "tile")
        tile.setFixedSize(64, 64)
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(0, 0, 0, 0)
        self._icon = IconLabel(icon_name, "accent", 28)
        tile_layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignCenter)
        self.title = label("", "h2")
        self.title.setStyleSheet("font-size: 18px;")
        self.text = label("", "muted", wrap=True)
        self.text.setFixedWidth(420)
        self.action = Button("", "primary", icon="plus")
        self.action.setMinimumWidth(180)
        self.steps = QWidget()
        steps = QVBoxLayout(self.steps)
        steps.setContentsMargins(0, 8, 0, 0)
        steps.setSpacing(8)
        self._step_labels: list[QLabel] = []
        for _ in range(3):
            row = QLabel()
            row.setProperty("role", "small")
            row.setWordWrap(True)
            row.setFixedWidth(420)
            steps.addWidget(row)
            self._step_labels.append(row)
        for widget, gap in ((tile, 0), (self.title, 16), (self.text, 6), (self.action, 18), (self.steps, 10)):
            outer.addSpacing(gap)
            outer.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        for widget in (self.title, self.text):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_content(self, title: str, text: str = "", action: str = "", steps: list[str] | tuple[str, ...] = ()) -> None:
        self.title.setText(title)
        self.text.setText(text)
        self.text.setVisible(bool(text))
        self.action.setText(action)
        self.action.setVisible(bool(action))
        for row, line in zip(self._step_labels, list(steps) + [""] * 3):
            row.setText(line)
            row.setVisible(bool(line))
        self.steps.setVisible(bool(steps))


class Callout(QFrame):
    """A notice with an icon, an optional bold title and an optional action.

    ``prominent`` adds a hairline border in the tone colour: for a warning the user must not miss.
    """

    activated = Signal()

    def __init__(self, tone: str = "warning", icon: str = "alert", parent: QWidget | None = None,
                 *, prominent: bool = False) -> None:
        super().__init__(parent)
        self.setProperty("role", "callout")
        self.setProperty("tone", tone)
        if prominent:
            self.setProperty("prominent", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 10, 10)
        row.setSpacing(10)
        self._icon = IconLabel(icon, tone, 18)
        self._title = label("", "callout-title", wrap=True)
        self._title.setVisible(False)
        self._text = QLabel()
        self._text.setWordWrap(True)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(self._title)
        texts.addWidget(self._text)
        self._button = Button("", None, size="sm")
        self._button.clicked.connect(self.activated)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        row.addWidget(self._button, 0, Qt.AlignmentFlag.AlignTop)

    def set_content(self, text: str, action: str = "", title: str = "") -> None:
        self._title.setText(title)
        self._title.setVisible(bool(title))
        self._text.setText(text)
        self._button.setText(action)
        self._button.setVisible(bool(action))

    def set_tone(self, tone: str, icon: str) -> None:
        self.setProperty("tone", tone)
        self._icon.set_icon(icon, tone)
        repolish(self)


class FreeProxyNotice(Callout):
    """Yellow warning: free proxies are for tests only (flagged IPs, captchas, failed checks)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("warning", "alert", parent, prominent=True)
        self.retranslate()

    def retranslate(self) -> None:
        self.set_content(tr("proxy.free.warn.text"), title=tr("proxy.free.warn.title"))


_TOAST_ICONS = {"info": "check-circle", "error": "alert"}


class _Toast(QFrame):
    def __init__(self, parent: QWidget, text: str, kind: str, action: tuple[str, Callable] | None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(10)
        pal = current_palette()
        tint = pal.danger if kind == "error" else pal.success
        glyph = QLabel()
        glyph.setPixmap(ic.pixmap(_TOAST_ICONS.get(kind, "check-circle"), tint, 18))
        glyph.setFixedSize(18, 18)
        layout.addWidget(glyph)
        message = QLabel(text)
        message.setWordWrap(False)
        layout.addWidget(message)
        if action is not None:
            button = QPushButton(action[0])
            button.setProperty("variant", "link")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda: (action[1](), self.dismiss()))
            layout.addWidget(button)
        self.adjustSize()
        self._fade: QPropertyAnimation | None = None

    def fade_in(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._fade = QPropertyAnimation(effect, b"opacity", self)
        self._fade.setDuration(140)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.finished.connect(lambda: self.setGraphicsEffect(None))
        self._fade.start()

    def dismiss(self) -> None:
        self.hide()
        self.deleteLater()


class ToastHost(QObject):
    """Stacks toasts at the bottom-centre of ``parent`` (usually the main window)."""

    MAX_VISIBLE = 4

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._parent = parent
        self._toasts: list[_Toast] = []
        parent.installEventFilter(self)

    def show_message(self, text: str, kind: str = "info", action: tuple[str, Callable] | None = None,
                     timeout_ms: int = 4200) -> _Toast:
        toast = _Toast(self._parent, text, kind, action)
        toast.destroyed.connect(lambda _=None, t=toast: self._forget(t))
        self._toasts.append(toast)
        while len(self._toasts) > self.MAX_VISIBLE:
            self._toasts.pop(0).dismiss()
        toast.show()
        toast.raise_()
        self._layout()
        toast.fade_in()
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms if kind != "error" else timeout_ms * 2, toast.dismiss)
        return toast

    def count(self) -> int:
        return len(self._toasts)

    def _forget(self, toast: _Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        try:
            y = self._parent.height() - 24
            for toast in reversed(self._toasts):
                toast.adjustSize()
                y -= toast.height()
                toast.move((self._parent.width() - toast.width()) // 2, y)
                toast.raise_()
                y -= 8
        except RuntimeError:  # window already torn down (shutdown race)
            self._toasts.clear()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._parent and event.type() == QEvent.Type.Resize:
            self._layout()
        return False
