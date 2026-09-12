"""Configurations page: generate fingerprints with chosen parameters.

The generator stays in the service layer; this page only picks the knobs —
template, platform and screen resolution (or leaves them random) — then runs
generation through a background worker and lists every stored configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
)

from app.application.profile_doctor import SUPPORTED_TIMEZONES
from app.gui import workers
from app.gui.utils.flow_layout import glued_pair
from app.gui.dialogs.config_dialog import ConfigDialog
from app.gui.dialogs.error_dialog import show_error
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container
    from app.gui.workers.task_runner import TaskRunner

_RANDOM_TEMPLATE = "random"
_RANDOM_PLATFORM = "random"
_RANDOM_SIZE = "random"

_RESOLUTIONS = [
    (_RANDOM_SIZE, None, None),
    ("1920 × 1080", 1920, 1080),
    ("1366 × 768", 1366, 768),
    ("1280 × 720", 1280, 720),
    ("1440 × 900", 1440, 900),
    ("1536 × 864", 1536, 864),
    ("2560 × 1440", 2560, 1440),
    ("3840 × 2160", 3840, 2160),
]


class ConfigurationsPage(PlaceholderPage):
    def __init__(
        self, container: "Container", runner: "TaskRunner", parent=None
    ) -> None:
        super().__init__("Configurations", kicker="SECTION 03")
        self._container = container
        self._runner = runner

        self._total = self.add_metrics("TOTAL")[0]

        self._template = QComboBox()
        self._platform = QComboBox()
        self._platform.addItems(
            [_RANDOM_PLATFORM, "windows", "macos", "linux"]
        )
        self._resolution = QComboBox()
        for label, _, _ in _RESOLUTIONS:
            self._resolution.addItem(label)
        self._timezone_filter = QComboBox()
        self._timezone_filter.setToolTip(
            "Pin the generated fingerprint to this timezone's country "
            "(timezone + locale + language are aligned, so the doctor stays green)"
        )
        self._timezone_filter.addItem("random", None)
        for zone in SUPPORTED_TIMEZONES:
            self._timezone_filter.addItem(zone, zone)
        # The zone names are long ("America/Argentina/Buenos_Aires") — size
        # the box to its short text, not the widest item, so the row stays
        # compact. The popup still shows every full name.
        self._timezone_filter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._timezone_filter.setMinimumContentsLength(14)
        self._generate = QPushButton("GENERATE")
        self._generate.setObjectName("PrimaryButton")
        self._generate.setToolTip("Generate a coherent fingerprint with the knobs on the left")
        self._new = QPushButton("NEW CUSTOM")
        self._new.setToolTip("Create a custom configuration by hand (timezone picker included)")
        self._edit = QPushButton("EDIT")
        self._edit.setToolTip("Edit the selected configuration")
        self._edit.setEnabled(False)
        self._delete = QPushButton("DELETE")
        self._delete.setObjectName("DangerButton")
        self._delete.setToolTip("Delete the selected configuration")
        self._delete.setEnabled(False)
        # Wrapping rows: on narrow windows the knobs flow underneath
        # instead of sliding off-screen (horizontal scroll is disabled).
        # Label + control travel as one glued pair, so a line break never
        # leaves "Timezone" on one line and its box on the next.
        self.add_flow_row(
            glued_pair(QLabel("Template"), self._template),
            glued_pair(QLabel("Platform"), self._platform),
            glued_pair(QLabel("Screen"), self._resolution),
            glued_pair(QLabel("Timezone"), self._timezone_filter),
            self._generate,
        )
        self.add_flow_row(
            self._new,
            self._edit,
            self._delete,
        )
        self.add_widget(
            self.make_hint("Template = base fingerprint · Platform/Screen/Timezone = overrides (random = coherent pick). Timezone pins the whole geo trio, so the doctor stays green.")
        )

        self._list = QListWidget()
        self._list.setObjectName("ConfigList")
        self.add_widget(self._list, 1)

        self._result = QLabel("Idle.")
        self._result.setObjectName("ResultLabel")
        self.add_control_row(self._result)

        self._generate.clicked.connect(self._generate_config)
        self._new.clicked.connect(self._new_config)
        self._edit.clicked.connect(self._edit_config)
        self._delete.clicked.connect(self._delete_config)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self.reload()

    # ------------------------------------------------------------ actions

    def reload(self) -> None:
        self._runner.submit(
            workers.tasks.summary(self._container),
            on_result=self._apply_summary,
            on_error=lambda exc: show_error(self, exc),
        )
        self._runner.submit(
            workers.tasks.list_configurations(self._container),
            on_result=self._apply_configs,
            on_error=lambda exc: show_error(self, exc),
        )
        if self._template.count() <= 1:
            self._runner.submit(
                workers.tasks.list_templates(self._container),
                on_result=self._apply_templates,
                on_error=lambda exc: show_error(self, exc),
            )

    def _generate_config(self) -> None:
        template = self._template.currentData()
        platform = self._platform.currentText()
        if platform == _RANDOM_PLATFORM:
            platform = None
        _, width, height = _RESOLUTIONS[self._resolution.currentIndex()]
        timezone = self._timezone_filter.currentData()

        self._generate.setEnabled(False)
        self._result.setText("Generating a coherent fingerprint…")
        self._runner.submit(
            workers.tasks.generate_configuration_with_size(
                self._container,
                platform=platform,
                template=template,
                screen_width=width,
                screen_height=height,
                timezone=timezone,
            ),
            on_result=self._apply_generated,
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._reload_and_enable(
                [self._generate, self._edit, self._delete]
            ),
        )

    def _new_config(self) -> None:
        dialog = ConfigDialog(parent=self)
        if dialog.exec() != ConfigDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        name = values.pop("name")
        self._result.setText(f"Creating configuration {name!r}…")
        self._runner.submit(
            workers.tasks.create_configuration(self._container, name, **values),
            on_result=lambda cfg: self._result.setText(
                f"Created #{cfg.id} · {cfg.name} · {cfg.timezone or 'no timezone'}"
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self.reload,
        )

    def _edit_config(self) -> None:
        configuration_id = self._selected_id()
        if configuration_id is None:
            return
        self._result.setText(f"Loading configuration #{configuration_id:03d}…")
        self._runner.submit(
            workers.tasks.get_configuration(self._container, configuration_id),
            on_result=self._open_edit_dialog,
            on_error=lambda exc: show_error(self, exc),
        )

    def _open_edit_dialog(self, config: object) -> None:
        dialog = ConfigDialog(config, parent=self)
        if dialog.exec() != ConfigDialog.DialogCode.Accepted:
            self._result.setText("Edit cancelled.")
            return
        values = dialog.values()
        name = values.pop("name")
        self._result.setText(f"Saving configuration #{config.id:03d}…")
        self._runner.submit(
            workers.tasks.update_configuration(
                self._container, config.id, name=name, **values
            ),
            on_result=lambda cfg: self._result.setText(
                f"Updated #{cfg.id} · {cfg.name} · {cfg.timezone or 'no timezone'}"
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self.reload,
        )

    def _delete_config(self) -> None:
        configuration_id = self._selected_id()
        if configuration_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete configuration",
            f"Delete configuration #{configuration_id}?",
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self._delete.setEnabled(False)
        self._result.setText(f"Deleting configuration #{configuration_id:03d}…")
        self._runner.submit(
            workers.tasks.delete_configuration(self._container, configuration_id),
            on_result=lambda _: self._result.setText(
                f"Configuration #{configuration_id:03d} deleted."
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._reload_and_enable([self._delete]),
        )

    def _reload_and_enable(self, widgets: list) -> None:
        """Reload the page and restore the given control buttons.

        The plain ``reload() and …`` idiom silently skips the re-enable because
        ``reload()`` returns ``None``.
        """
        self.reload()
        for widget in widgets:
            widget.setEnabled(True)

    def _sync_buttons(self) -> None:
        selected = self._selected_id() is not None
        self._edit.setEnabled(selected)
        self._delete.setEnabled(selected)

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # ------------------------------------------------------------ results

    def _apply_templates(self, templates: object) -> None:
        self._template.blockSignals(True)
        self._template.clear()
        self._template.addItem("random", None)
        for name in templates or []:
            self._template.addItem(name, name)
        self._template.blockSignals(False)

    def _apply_summary(self, summary: object) -> None:
        self._total.set_value(summary.configurations)

    def _apply_configs(self, configurations: object) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for cfg in configurations or []:
            item = QListWidgetItem(
                f"#{cfg.id:03d} · {cfg.name} · {cfg.platform or '—'} · "
                f"{cfg.screen_width}×{cfg.screen_height} · "
                f"{cfg.language_tag or '—'}"
            )
            item.setData(Qt.ItemDataRole.UserRole, cfg.id)
            self._list.addItem(item)
        self._list.scrollToBottom()
        self._list.blockSignals(False)

    def _apply_generated(self, config: object) -> None:
        platform = config.platform or "—"
        self._result.setText(
            f"Created #{config.id} · {config.name} · {platform} · "
            f"{config.screen_width}×{config.screen_height} · "
            f"{config.language_tag} · {config.timezone or 'no timezone'}"
        )
        self.reload()