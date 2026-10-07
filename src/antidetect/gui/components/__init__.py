"""Reusable widgets. Pages are assembled from these; none of them know about services."""

from antidetect.gui.components.avatar import AvatarBadge, paint_avatar
from antidetect.gui.components.basics import (
    Button,
    Card,
    IconButton,
    IconLabel,
    PageHeader,
    button,
    divider,
    flash,
    label,
    repolish,
    set_role,
)
from antidetect.gui.components.dialog import BaseDialog, ConfirmDialog, ErrorDialog, confirm
from antidetect.gui.components.feedback import Callout, EmptyState, FreeProxyNotice, ToastHost
from antidetect.gui.components.fields import Cards, SearchField, Segmented, Select, Switch, TabBar, TabView
from antidetect.gui.components.menu import StyledMenu
from antidetect.gui.components.rows import SettingGroup, SettingRow

__all__ = [
    "AvatarBadge", "BaseDialog", "Button", "Callout", "Card", "Cards", "ConfirmDialog", "EmptyState", "ErrorDialog",
    "FreeProxyNotice", "IconButton", "IconLabel", "PageHeader", "SearchField", "Segmented", "Select", "SettingGroup", "SettingRow",
    "StyledMenu",
    "Switch", "TabBar", "TabView", "ToastHost", "button", "confirm", "divider", "flash", "label",
    "paint_avatar", "repolish", "set_role",
]
