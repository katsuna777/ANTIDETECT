"""In-window splash screen 0–100% for the desktop shell.

При запуске окно приложения открывается сразу, а поверх всего контента
лежит этот overlay: проценты 0→100%, тонкая линия прогресса, затем мягкий
fade-out и fade-in контента. Отдельного окна больше нет.

Design: инверсия ``design/`` (фон Ink #000, текст Paper #fff) — сохраняет
монохромную систему 19–86. Никаких градиентов/теней/радиусов по умолчанию;
неон включается двумя константами ``ACCENT_FROM/ACCENT_TO`` ниже.

Использование (app.py)::

    window.show()
    splash = SplashScreen(window)  # overlay ВНУТРИ окна
    splash.start(lambda: attach_fade_in(window.centralWidget(), slide=False))
"""

from __future__ import annotations

import random

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QTimer, Signal, Slot, Qt, Property
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QProgressBar, QSpacerItem, QVBoxLayout, QWidget

from app.gui.utils.theme import INK, PAPER

# --------------------------------------------------------------------------- #
# Токены — меняйте только здесь (hex-коды). По умолчанию строгий монохром.
# Для неона/пастели задайте, например: "#7C5CFF" / "#00E5CC".
# --------------------------------------------------------------------------- #

SPLASH_BG = INK            # фон — Ink из design.md
SPLASH_FG = PAPER          # текст — Paper из design.md
SPLASH_MUTED = "rgba(255, 255, 255, 55%)"
SPLASH_TRACK = "rgba(255, 255, 255, 25%)"
ACCENT_FROM = PAPER        # монохром; для неона подставьте свой hex
ACCENT_TO = PAPER          # монохром; для неона подставьте свой hex

FADE_DELAY_MS = 500        # пауза на 100% перед исчезновением (400–600мс по ТЗ)
FADE_DURATION_MS = 700     # длительность opacity-fade

_STAGES = (
    (12, "Ядро…"),
    (34, "Профили…"),
    (58, "Прокси…"),
    (79, "Chromium…"),
    (93, "Интерфейс…"),
    (100, "Готово"),
)


class _SmoothValue(QObject):
    """Прокси для анимации числа через QPropertyAnimation (60fps, OutCubic)."""

    valueChanged = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._v = 0.0

    def _get(self) -> float:
        return self._v

    def _set(self, v: float) -> None:
        self._v = v
        self.valueChanged.emit(v)

    value = Property(float, _get, _set)


class SplashScreen(QWidget):
    """Overlay 0→100% поверх контента окна с нелинейным шагом и fade-out.

    С родителем — overlay внутри окна (следит за ресайзом родителя).
    Без родителя — отдельное полноэкранное окно (демо/тесты).
    """

    finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        if parent is None:
            super().__init__(
                None,
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Dialog,
            )
        else:
            # Обычный child-виджет: лежит поверх контента окна, не окно само.
            super().__init__(parent)
            self.move(0, 0)
            self.resize(parent.size())
            parent.installEventFilter(self)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("SplashScreen")
        if parent is None:
            self.showFullScreen()

        self._value = 0.0
        self._smooth = _SmoothValue(self)
        self._smooth.valueChanged.connect(self._render)
        self._anim = QPropertyAnimation(self._smooth, b"value", self)
        # ПЛАВНОСТЬ: OutCubic == cubic-bezier(0.22,1,0.36,1) — затухание к концу
        self._anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self._anim.setDuration(180)

        self.setStyleSheet(
            f"#SplashScreen {{ background: {SPLASH_BG}; }}"
            # Без font-size: размер цифр задаёт _fit_to_window через QFont
            # (stylesheet перебил бы его), здесь только цвет и hairline-начертание.
            f"#SplashPercent {{ color: {SPLASH_FG}; font-weight: 200; }}"
            f"#SplashKicker, #SplashStage, #SplashCount {{ color: {SPLASH_MUTED}; font-size: 11px; }}"
            f"#SplashHairline {{ background: {SPLASH_TRACK}; border: none; min-height: 1px; max-height: 1px; }}"
            f"QProgressBar {{ background: {SPLASH_TRACK}; border: none; min-height: 2px; max-height: 2px; text-align: center; }}"
            f"QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_FROM}, stop:1 {ACCENT_TO}); }}"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(0)
        layout.setContentsMargins(24, 24, 24, 24)

        kicker = QLabel("ANTIDETECT")
        kicker.setObjectName("SplashKicker")
        kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(kicker)

        # Фиксированная ширина цифр = аналог tabular-nums,
        # цифры не «прыгают» при смене значений. Размер — в масштаб окна
        # (см. _fit_to_window: замер через QFontMetrics, влезает всегда).
        self._percent = QLabel("  0 %")
        self._percent.setObjectName("SplashPercent")
        self._percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._percent.setMinimumWidth(0)
        self._percent.setWordWrap(False)
        layout.addWidget(self._percent)

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)  # x10 для гладкости (0.1% шаг)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedWidth(min(420, self.width() or 420))
        self._gap_bar = QSpacerItem(0, 28)
        layout.addItem(self._gap_bar)
        layout.addWidget(self._bar, alignment=Qt.AlignmentFlag.AlignCenter)

        self._stage = QLabel("Инициализация…")
        self._stage.setObjectName("SplashStage")
        self._stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gap_stage = QSpacerItem(0, 14)
        layout.addItem(self._gap_stage)
        layout.addWidget(self._stage)

        self._count = QLabel("0 / 100")
        self._count.setObjectName("SplashCount")
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._count)

        rule = QFrame()
        rule.setObjectName("SplashHairline")
        self._gap_rule = QSpacerItem(0, 26)
        layout.addItem(self._gap_rule)
        layout.addWidget(rule, alignment=Qt.AlignmentFlag.AlignCenter)
        self._rule = rule
        self._fit_to_window()  # первичный масштаб цифр/линии под окно

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)

        self._last_n = -1  # последний отрисованный целый процент
        self._fade = None

        self._on_done = None

    # ------------------------------------------------------------ public API

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Overlay всегда покрывает всё окно, даже при ресайзе.
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self.resize(self.parent().size())
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_to_window()

    def _fit_to_window(self) -> None:
        """Масштаб цифр и линии под размер окна — без перекрытий и обрезки.

        Старая формула (55% меньшей стороны, пол 72px) на низких окнах давала
        цифры выше доступной высоты: центрированный layout обрезал их сверху
        и снизу. Теперь размер подбирается замером: стартуем с тех же 55% и
        уменьшаем, пока самая широкая строка ("100 %") не влезет и по ширине,
        и по высоте. Вертикальные gaps и ширина бара тоже масштабируются от
        высоты/ширины окна.
        """
        w, h = max(1, self.width()), max(1, self.height())
        layout = self.layout()

        # Вертикальные отступы: сжимаются на низких экранах (0.3–1.0).
        vscale = min(1.0, max(0.3, h / 800.0))
        self._gap_bar.changeSize(0, max(6, int(28 * vscale)))
        self._gap_stage.changeSize(0, max(4, int(14 * vscale)))
        self._gap_rule.changeSize(0, max(6, int(26 * vscale)))
        layout.invalidate()

        # Бюджет под цифры: всё окно минус поля layout, kicker, бар,
        # stage/count, gaps и линейка. Замеряем реальными метриками строк.
        chrome = (
            48  # layout margins top+bottom
            + self._gap_bar.sizeHint().height()
            + self._gap_stage.sizeHint().height()
            + self._gap_rule.sizeHint().height()
            + 20  # kicker
            + 2  # progress bar
            + 18  # stage
            + 18  # count
            + 1  # hairline rule
            + 8  # slack
        )
        w_budget = max(60, w - 48 - 16)
        h_budget = max(40, h - chrome)

        # Размер — инлайн-стилем: глобальный `* { font-size: 14px }` из темы
        # перебил бы и QFont, и правило без специфичности; инлайн важнее.
        px = max(24, min(900, int(min(w, h) * 0.55)))
        probe = QFont(self._percent.font())
        probe.setWeight(QFont.Weight.ExtraLight)
        while px > 24:
            probe.setPixelSize(px)
            metrics = QFontMetrics(probe)
            if (
                metrics.horizontalAdvance("100 %") <= w_budget
                and metrics.height() <= h_budget
            ):
                break
            px = max(24, int(px * 0.9))
        self._percent.setStyleSheet(f"font-size: {px}px;")
        # Линия прогресса — 55% ширины окна, с полами под маленькие экраны.
        bw = max(160, min(560, int(w * 0.55)))
        self._bar.setFixedWidth(bw)
        self._rule.setFixedWidth(bw)

    def start(self, on_done=None) -> None:
        """Показать сплэш поверх окна и запустить нелинейный прогресс."""
        self._on_done = on_done
        if self.parent() is not None:
            self.move(0, 0)
            self.resize(self.parent().size())
        self.show()
        self.raise_()
        QTimer.singleShot(150, self._tick)

    @property
    def progress(self) -> float:
        return self._value

    # --------------------------------------------------------------- stepping

    @Slot()
    def _tick(self) -> None:
        if self._value >= 100.0:
            self._finish()
            return
        remaining = 100.0 - self._value
        # НЕЛИНЕЙНЫЙ ШАГ: 8–22% от остатка + мягкое замедление у финиша.
        # Весь цикл ~4с: быстро в начале, рывками в конце (как модули).
        chunk = remaining * random.uniform(0.08, 0.22)
        chunk = max(1.2, min(chunk, 12.0))
        if self._value > 85:
            chunk *= 0.6
        if self._value > 96:
            chunk *= 0.55
        target = min(100.0, self._value + chunk)
        # ПЛАВНОСТЬ: едем к target через OutCubic-анимацию, а не скачком
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(target)
        self._anim.start()
        self._value = target
        if self._value >= 100.0:
            # даём анимации дойти до 100, затем finish
            QTimer.singleShot(200, self._finish)
        else:
            QTimer.singleShot(int(random.uniform(70, 180)), self._tick)

    @Slot(float)
    def _render(self, v: float) -> None:
        n = int(v)
        # Текст — только при смене целого числа: иначе ~60 перерисовок
        # в секунду мажут глифы друг на друга.
        if n != self._last_n:
            self._last_n = n
            # Формат с фиксированной шириной — цифры не прыгают (tabular-nums)
            self._percent.setText(f"{n:3d} %")
            self._count.setText(f"{n} / 100")
            for bound, label in _STAGES:
                if n <= bound:
                    self._stage.setText(label)
                    break
        self._bar.setValue(int(v * 10))

    @Slot()
    def _finish(self) -> None:
        self._tick_timer.stop()
        self._render(100.0)
        # Пауза 400–600мс на 100%, затем fade через opacity
        QTimer.singleShot(FADE_DELAY_MS, self._fade_out)

    @Slot()
    def _fade_out(self) -> None:
        # QGraphicsOpacityEffect на child-overlay macOS не компостит
        # (overlay становится невидимым), поэтому гаснем иначе: снапшот
        # overlay в borderless top-level поверх окна + windowOpacity,
        # которую честно анимирует композитор ОС.
        top = QLabel()
        top.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        top.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        top.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        top.setPixmap(self.grab())
        top.setScaledContents(True)
        top.setFixedSize(self.size())
        top.move(self.mapToGlobal(QPoint(0, 0)))
        top.setWindowOpacity(1.0)
        top.show()
        self.hide()  # настоящий overlay прячем сразу, дальше гаснет снапшот

        self._fade = QPropertyAnimation(top, b"windowOpacity", top)
        self._fade.setDuration(FADE_DURATION_MS)
        # ПЛАВНОСТЬ: OutCubic == cubic-bezier(0.22,1,0.36,1)
        self._fade.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(top.close)
        self._fade.finished.connect(self._on_fade_finished)
        self._fade.start()

    @Slot()
    def _on_fade_finished(self) -> None:
        self.finished.emit()
        if self._on_done is not None:
            cb, self._on_done = self._on_done, None
            cb()
        self.deleteLater()


def attach_fade_in(widget: QWidget, duration_ms: int = 800, shift_px: int = 18, slide: bool = True) -> None:
    """Лёгкое появление контента: fade-in (+ slide-up, отключается для виджетов в layout)."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    # ПЛАВНОСТЬ: тот же OutCubic — появление замедляется к концу
    anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
    # Эффект снимаем по окончании: виджет остаётся обычным, без оверхеда
    # и без риска артефактов композитинга.
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    if not slide:
        return
    # slide-up: мягкий подъём на shift_px через геометрию (только для окон —
    # виджеты внутри layout двигать нельзя, layout вернёт их на место)
    geo = widget.geometry()
    slide_anim = QPropertyAnimation(widget, b"pos", widget)
    slide_anim.setDuration(duration_ms)
    slide_anim.setStartValue(geo.topLeft() + QPoint(0, shift_px))
    slide_anim.setEndValue(geo.topLeft())
    slide_anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
    slide_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
