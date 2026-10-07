"""The single application-wide style sheet.

Widgets never set their own style: they mark themselves with an object name or a
``role`` / ``variant`` / ``tone`` property and this sheet does the rest, so a theme
switch is one ``setStyleSheet`` call. Rules of the look: a white sheet floating on a grey
canvas, flat surfaces split by 1px borders, 10px control radius / 12px cards, shadows only
on the little cards inside table rows and on popovers (painted by hand, never as graphics
effects), one accent used for the primary action, status colours only for status.
"""

from __future__ import annotations

from string import Template

from antidetect.gui.theme.palette import Palette

_QSS = Template(
    """
QWidget { color: $text; font-size: 13px; }
QMainWindow, QWidget#Canvas { background: $window; }
QDialog { background: $surface; }
QStackedWidget, QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QLabel { background: transparent; }
QToolTip {
    background: $inverse; color: $inverse_text; border: none;
    padding: 5px 9px; border-radius: 6px; font-size: 12px;
}

/* ------------------------------------------------------------- typography */
QLabel[role="title"] { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
QLabel[role="h2"] { font-size: 15px; font-weight: 600; }
QLabel[role="h3"] { font-size: 13px; font-weight: 600; }
QLabel[role="subtitle"] { color: $muted; font-size: 13px; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="small"] { color: $muted; font-size: 12px; }
QLabel[role="faint"] { color: $faint; font-size: 12px; }
QLabel[role="danger"] { color: $danger; }
QLabel[role="warning"] { color: $warning; }
QLabel[role="success"] { color: $success; }
QLabel[role="section"] { color: $muted; font-size: 11px; font-weight: 600; letter-spacing: 0.6px; }
QLabel[role="field"] { color: $muted; font-size: 12px; font-weight: 500; }
QLabel[role="pill"] {
    background: $subtle; color: $muted; border-radius: 7px; padding: 2px 9px; font-size: 12px; font-weight: 600;
}
QLabel[role="count"] {
    background: $subtle; color: $muted; border-radius: 9px; padding: 0 11px; font-size: 13px; font-weight: 600;
}
QLabel[role="count"][tone="success"] { background: $success_soft; color: $success; }
QLabel[role="pill"][tone="success"] { background: $success_soft; color: $success; }
QLabel[role="page-title"] { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
QLabel[role="address"] { font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 15px; font-weight: 500; color: $muted; }
QLabel[role="mono"] { font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 12px; color: $muted; }
QLabel[role="path"] { font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 12px; font-weight: 600; }
QLabel[role="method"] {
    font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 11px; font-weight: 700;
    border-radius: 6px; padding: 3px 0; min-width: 52px; max-width: 52px; qproperty-alignment: AlignCenter;
    background: $subtle; color: $muted;
}
QLabel[role="method"][tone="get"] { background: $success_soft; color: $success; }
QLabel[role="method"][tone="post"] { background: $accent_soft; color: $text; }
QLabel[role="method"][tone="patch"] { background: $warning_soft; color: $warning; }
QLabel[role="method"][tone="delete"] { background: $danger_soft; color: $danger; }
QFrame[role="endpoint"] { background: transparent; border: none; border-radius: 10px; }
QFrame[role="endpoint"]:hover { background: $hover; }

/* ------------------------------------------------------------------ sidebar */
QWidget#Sidebar { background: transparent; border: none; }
QFrame#Sheet { background: $surface; border: 1px solid $border; border-radius: 14px; }
QLabel#Brand { font-size: 15px; font-weight: 700; letter-spacing: -0.1px; }
QFrame#SidebarFooter { background: transparent; border: none; }

/* ------------------------------------------------------------------ buttons */
QPushButton {
    padding: 0 14px; min-height: 34px; border-radius: 10px; font-weight: 500;
    border: 1px solid $border_strong; background: $raised; color: $text;
}
QPushButton:hover { background: $hover; border-color: $faint; }
QPushButton:pressed { background: $subtle; }
QPushButton:disabled { color: $faint; border-color: $border; background: $subtle; }
QPushButton:focus { border-color: $accent; }
QPushButton[variant="primary"] { background: $accent; border-color: $accent; color: $accent_text; font-weight: 600; }
QPushButton[variant="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[variant="primary"]:pressed { background: $accent_hover; }
QPushButton[variant="primary"]:disabled { background: $subtle; border-color: $border; color: $faint; }
QPushButton[variant="danger"] { color: $danger; }
QPushButton[variant="danger"]:hover { background: $danger_soft; border-color: $danger; }
QPushButton[variant="danger-solid"] { background: $danger; border-color: $danger; color: $danger_text; font-weight: 600; }
QPushButton[variant="danger-solid"]:hover { background: $danger; border-color: $danger; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; }
QPushButton[variant="ghost"]:hover { background: $subtle; border-color: $subtle; }
QPushButton[variant="link"] {
    border: none; background: transparent; color: $accent; padding: 0 2px; min-height: 22px;
}
QPushButton[variant="link"]:hover { background: transparent; text-decoration: underline; }
QPushButton[variant="soft"] {
    background: $subtle; border: 1px solid $subtle; color: $text; border-radius: 10px;
    padding: 0 12px; font-weight: 500;
}
QPushButton[variant="soft"]:hover { background: $nav_selected; border-color: $nav_selected; }
QPushButton[variant="soft"]:pressed { background: $border; border-color: $border; }
QPushButton[variant="soft"][active="true"] { background: $nav_selected; border-color: $nav_selected; }
QPushButton[variant="soft"]:disabled { background: $subtle; color: $faint; border-color: $subtle; }
QPushButton[variant="soft"]:focus { border-color: $accent; }
/* two sizes only: regular = 34 + 2 x 1 px border = 36 (toolbars, forms), compact = 30 + 2 = 32 (inside a card / row) */
QPushButton[compact="true"] { min-height: 30px; padding: 0 10px; font-size: 12px; border-radius: 8px; }
QPushButton[iconOnly="true"] { padding: 0; min-width: 34px; }
QPushButton[iconOnly="true"][compact="true"] { padding: 0; min-width: 30px; }
QToolButton { border: none; border-radius: 8px; padding: 0; background: transparent; }
QToolButton:hover { background: $subtle; }
QToolButton:pressed { background: $border; }
QToolButton[role="icon"] { min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; }

/* segmented control + underline tabs */
QPushButton[variant="chip"] {
    border: 1px solid $border_strong; border-radius: 9px; padding: 0 12px; min-height: 26px;
    background: transparent; color: $muted; font-weight: 500; font-size: 12px;
}
QPushButton[variant="chip"]:hover { color: $text; background: $subtle; border-color: $border_strong; }
QPushButton[variant="chip"]:checked { background: $nav_selected; color: $text; border-color: $nav_selected; font-weight: 600; }
QPushButton[variant="card"] {
    border: 1px solid $border_strong; border-radius: 12px; padding: 0 16px; min-height: 52px;
    background: $raised; color: $muted; font-weight: 500; text-align: left;
}
QPushButton[variant="card"]:hover { color: $text; border-color: $faint; }
QPushButton[variant="card"]:checked { color: $text; border-color: $accent; background: $accent_soft; font-weight: 600; }
QPushButton[variant="card"]:focus { border-color: $accent; }
QFrame[role="segmented"] { background: $subtle; border: none; border-radius: 10px; }
QPushButton[variant="seg"] {
    border: 1px solid transparent; border-radius: 8px; padding: 0 14px; min-height: 28px;
    background: transparent; color: $muted; font-weight: 500;
}
QPushButton[variant="seg"]:hover { color: $text; background: transparent; border-color: transparent; }
QPushButton[variant="seg"]:checked { background: $raised; color: $text; border-color: $border; font-weight: 600; }
QPushButton[variant="tab"] {
    border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 0 2px;
    min-height: 40px; background: transparent; color: $muted; font-weight: 500;
}
QPushButton[variant="tab"]:hover { color: $text; background: transparent; }
QPushButton[variant="tab"]:checked { color: $text; border-bottom-color: $accent; font-weight: 600; }
QPushButton[variant="tab"][invalid="true"] { color: $danger; }
QFrame[role="tabbar"] { background: transparent; border: none; border-bottom: 1px solid $border; }

/* ------------------------------------------------------------------- inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $raised; border: 1px solid $border_strong; border-radius: 10px;
    padding: 0 12px; selection-background-color: $accent; selection-color: $accent_text;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { min-height: 34px; }
QPlainTextEdit, QTextEdit { padding: 8px 12px; }
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover { border-color: $faint; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus,
QComboBox:on { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
    color: $faint; background: $subtle; border-color: $border;
}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] { border-color: $danger; }
QLineEdit[role="mono"] { font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 12px; }
QLineEdit[role="port"] {
    font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 15px; font-weight: 600;
    background: $subtle; border-color: $subtle; border-radius: 9px; padding: 0 8px; min-height: 30px;
}
QLineEdit[role="port"]:hover { background: $nav_selected; border-color: $nav_selected; }
QLineEdit[role="port"]:focus { background: $raised; border-color: $accent; }
QLineEdit[role="inline"] { background: transparent; border-color: transparent; min-height: 30px; padding: 0 8px; }
QLineEdit[role="inline"]:hover { background: $subtle; border-color: $subtle; }
QLineEdit[role="inline"]:focus { background: $raised; border-color: $accent; }
QLineEdit[role="search"] { padding-left: 4px; background: $subtle; border-color: $subtle; }
QLineEdit[role="search"]:hover { background: $nav_selected; border-color: $nav_selected; }
QLineEdit[role="search"]:focus { background: $raised; border-color: $accent; }
QComboBox { padding-right: 34px; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBoxPrivateContainer { background: $raised; border: 1px solid $border_strong; border-radius: 0; }
QComboBox QAbstractItemView {
    background: $raised; border: none; outline: none; padding: 4px;
    selection-background-color: $accent_soft; selection-color: $text;
}
QComboBox QAbstractItemView::item { min-height: 30px; padding: 0 10px; border-radius: 6px; }
QComboBox QAbstractItemView::item:hover { background: $subtle; color: $text; }
QComboBox QAbstractItemView::item:selected { background: $accent_soft; color: $text; }

/* ------------------------------------------------------------------- views */
QTableView, QListView, QTreeView {
    background: transparent; border: none; outline: 0; gridline-color: transparent;
    selection-background-color: transparent; selection-color: $text;
}
QHeaderView { background: transparent; border: none; }
QTableCornerButton::section { background: transparent; border: none; }
QListView[role="log"] { background: $surface; }

/* -------------------------------------------------------------------- menus */
QMenu {
    background: $raised; border: 1px solid $border_strong; border-radius: 12px; padding: 6px;
}
QMenu::item { padding: 8px 34px 8px 10px; border-radius: 8px; margin: 1px 0; }
QMenu::item:selected { background: $nav_selected; color: $text; }
QMenu::item:disabled { color: $faint; background: transparent; }
QMenu::item:default { color: $danger; font-weight: 400; }
QMenu::item:default:selected { background: $danger_soft; color: $danger; }
QMenu::icon { padding-left: 4px; }
QMenu::separator { height: 1px; background: $border; margin: 5px 10px; }
QMenu::right-arrow { image: none; width: 0; height: 0; }

/* --------------------------------------------------------------- scrollbars */
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $border_strong; border-radius: 3px; min-height: 32px; margin: 0 3px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 4px; min-width: 32px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: $faint; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ------------------------------------------------------------ surfaces etc. */
QProgressBar { background: $subtle; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }
QProgressBar::chunk { background: $accent; border-radius: 2px; }
QFrame[role="card"] { background: $surface; border: 1px solid $border; border-radius: 12px; }
QFrame[role="tile"] { background: $subtle; border: none; border-radius: 12px; }
QFrame[role="divider"] { background: $border; border: none; max-height: 1px; min-height: 1px; }
QFrame[role="callout"] { background: $accent_soft; border: none; border-radius: 10px; }
QFrame[role="callout"][tone="warning"] { background: $warning_soft; }
QFrame[role="callout"][tone="danger"] { background: $danger_soft; }
QFrame[role="callout"][prominent="true"][tone="warning"] { border: 1px solid $warning_edge; }
QLabel[role="callout-title"] { font-weight: 600; }
QFrame[role="callout"][tone="warning"] QLabel[role="callout-title"] { color: $warning; }
QFrame[role="callout"][tone="danger"] QLabel[role="callout-title"] { color: $danger; }
QFrame[role="chip"] { background: $subtle; border: none; border-radius: 6px; }
QFrame#Toast { background: $inverse; border: none; border-radius: 10px; }
QFrame#Toast QLabel { color: $inverse_text; font-weight: 500; }
QFrame#Toast QPushButton[variant="link"] { color: $inverse_text; text-decoration: underline; }
QPlainTextEdit[role="mono"] { font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 12px; }
"""
)


def _mix(foreground: str, background: str, amount: float) -> str:
    """``foreground`` laid over ``background`` at ``amount`` opacity, as a hex colour."""
    fg = [int(foreground[i:i + 2], 16) for i in (1, 3, 5)]
    bg = [int(background[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(f * amount + b * (1 - amount)):02X}" for f, b in zip(fg, bg))


def build_stylesheet(palette: Palette) -> str:
    values = dict(palette.__dict__)
    values["warning_edge"] = _mix(palette.warning, palette.warning_soft, 0.45)  # a hairline, not a heavy frame
    return _QSS.substitute(**values)
