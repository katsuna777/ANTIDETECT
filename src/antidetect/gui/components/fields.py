"""Form controls: search field, select, switch, segmented control, tabs."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from antidetect.gui.theme import bus, current_palette
from antidetect.gui.theme import icons as ic


class SearchField(QLineEdit):
    """A line edit with a leading magnifier and a clear button."""

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "search")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._action = self.addAction(ic.icon("search", "#888888"), QLineEdit.ActionPosition.LeadingPosition)
        self._refresh_icon()
        bus.changed.connect(self._refresh_icon)

    def _refresh_icon(self) -> None:
        self._action.setIcon(ic.icon("search", current_palette().faint, size=16))


class Select(QComboBox):
    """A combo box with a chevron and a styled popup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        view = QListView()
        view.setUniformItemSizes(True)         # every item is the same height: lay out the visible ones, not all of them
        self.setView(view)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus | Qt.FocusPolicy.WheelFocus)
        self.setMaxVisibleItems(12)

    def wheelEvent(self, event) -> None:  # noqa: N802 - never change the value by scrolling past it
        event.ignore()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        pal = current_palette()
        pixmap = ic.pixmap("chevron-down", pal.faint if not self.isEnabled() else pal.muted, 16)
        painter = QPainter(self)
        painter.drawPixmap(self.width() - 26, (self.height() - 16) // 2, pixmap)

    def fit_to_width(self, characters: int) -> None:
        """Keep the width independent of what is listed: Qt otherwise measures every item on each style change."""
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(characters)

    def select_data(self, data) -> bool:
        index = self.findData(data)
        if index >= 0:
            self.setCurrentIndex(index)
        return index >= 0


class Switch(QAbstractButton):
    """An on/off toggle. Draws itself; the caption belongs to the row around it."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._offset = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(40, 22)

    def _animate(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if not self.isVisible():
            self._offset = target
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_anim(self, value) -> None:
        self._offset = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        pal = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        track = QColor(pal.border_strong)
        on = QColor(pal.accent)
        mix = self._offset
        color = QColor(
            int(track.red() + (on.red() - track.red()) * mix),
            int(track.green() + (on.green() - track.green()) * mix),
            int(track.blue() + (on.blue() - track.blue()) * mix),
        )
        if not self.isEnabled():
            color.setAlphaF(0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        diameter = rect.height() - 4
        x = rect.left() + 2 + (rect.width() - diameter - 4) * self._offset
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, rect.top() + 2, diameter, diameter))
        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(pal.accent), 1.5))
            painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 11, 11)


class _ButtonRow(QFrame):
    """Shared machinery of Segmented and TabBar: exclusive, keyed, text-updatable buttons."""

    changed = Signal(str)

    def __init__(self, variant: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._variant = variant
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._icons: dict[str, str] = {}
        self._layout = QHBoxLayout(self)
        self._value: str | None = None
        bus.changed.connect(self._refresh_icons)

    def _add(self, key: str, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("variant", self._variant)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._group.addButton(btn)
        self._buttons[key] = btn
        btn.clicked.connect(lambda _=False, k=key: self._clicked(k))
        self._layout.addWidget(btn)
        return btn

    def _clicked(self, key: str) -> None:
        if key != self._value:
            self._value = key
            self.changed.emit(key)

    def value(self) -> str | None:
        return self._value

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]

    def buttons(self) -> dict[str, QPushButton]:
        return self._buttons

    def set_value(self, key: str, *, emit: bool = False) -> None:
        btn = self._buttons.get(key)
        if btn is None:
            return
        btn.setChecked(True)
        if emit:
            self._clicked(key)
        else:
            self._value = key

    def set_text(self, key: str, text: str) -> None:
        self._buttons[key].setText(text)

    def set_icon(self, key: str, name: str, *, size: int = 16, gap: int = 6) -> None:
        """A glyph before the label: muted, brighter under the pointer and when the button is the chosen one."""
        self._icons[key] = name
        button = self._buttons[key]
        button.setIconSize(QSize(size + gap, size))     # the engine draws the glyph at the left of its slot: the rest is the gap
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        pal = current_palette()
        for key, name in self._icons.items():
            self._buttons[key].setIcon(ic.icon(name, pal.muted, hover=pal.text, on=pal.text, size=16))


class Segmented(_ButtonRow):
    """A pill-shaped single-choice control: ``Segmented([("light", "Light"), ...])``."""

    def __init__(self, options: list[tuple[str, str]], value: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__("seg", parent)
        self.setProperty("role", "segmented")
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        for key, text in options:
            self._add(key, text)
        if value is None and options:
            value = options[0][0]
        if value is not None:
            self.set_value(value)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class Cards(_ButtonRow):
    """A single choice as a row of equal cards, each with a glyph: ``Cards([("macos", "macOS", "command"), ...])``."""

    def __init__(self, options: list[tuple[str, str, str]], value: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__("card", parent)
        self.setProperty("role", "cards")
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        for key, text, glyph in options:
            button = self._add(key, text)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._layout.setStretchFactor(button, 1)
            self.set_icon(key, glyph, size=20, gap=8)
        if value is None and options:
            value = options[0][0]
        if value is not None:
            self.set_value(value)


class TabBar(_ButtonRow):
    """Underline tabs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("tab", parent)
        self.setProperty("role", "tabbar")
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(24)
        self._layout.addStretch(1)

    def add_tab(self, key: str, text: str, icon: str | None = None) -> None:
        btn = self._add(key, text)
        self._layout.removeWidget(btn)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        if icon:
            self.set_icon(key, icon)
        if self._value is None:
            self.set_value(key)


class TabView(QWidget):
    """A tab bar over a stack of pages."""

    currentChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.bar = TabBar()
        self.stack = QStackedWidget()
        col.addWidget(self.bar)
        col.addWidget(self.stack, 1)
        self._pages: dict[str, QWidget] = {}
        self.bar.changed.connect(self._on_changed)

    def add_tab(self, key: str, text: str, page: QWidget, icon: str | None = None) -> None:
        self._pages[key] = page
        self.stack.addWidget(page)
        self.bar.add_tab(key, text, icon)
        if len(self._pages) == 1:
            self.stack.setCurrentWidget(page)

    def set_current(self, key: str) -> None:
        if key in self._pages:
            self.bar.set_value(key)
            self.stack.setCurrentWidget(self._pages[key])

    def current(self) -> str | None:
        return self.bar.value()

    def _on_changed(self, key: str) -> None:
        self.stack.setCurrentWidget(self._pages[key])
        self.currentChanged.emit(key)
