"""Bundled GUI assets (app icon)."""

from antidetect.runtime import resource_path

APP_ICON_PATH = resource_path("antidetect", "gui", "resources", "icon.png")      # window / dock icon
APP_MARK_PATH = resource_path("antidetect", "gui", "resources", "icon-128.png")   # in-app logo (cheap to decode)
