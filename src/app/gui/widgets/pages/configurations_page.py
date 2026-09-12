"""Configurations page: generate fingerprints with chosen parameters."""

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
from app.gui.i18n import tr
from app.gui.utils.flow_layout import glued_pair
from app.gui.dialogs.config_dialog import ConfigDialog
from app.gui.dialogs.error_dialog import show_error
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container
    from app.gui.workers.task_runner import TaskRunner

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
        super().__init__(tr("configs.title"), kicker=tr("configs.kicker"))
        self._container = container
        self._runner = runner

        self._total = self.add_metrics(tr("metric.total"))[0]

        self._template = QComboBox()
        self._platform = QComboBox()
        self._resolution = QComboBox()
        self._timezone_filter = QComboBox()
        self._generate = QPushButton(tr("configs.generate"))
        self._generate.setObjectName("PrimaryButton")
        self._generate.setToolTip(tr("configs.generate.tip"))
        self._new = QPushButton(tr("configs.new"))
        self._new.setToolTip(tr("configs.new.tip"))
        self._edit = QPushButton(tr("configs.edit"))
        self._edit.setToolTip(tr("configs.edit.tip"))
        self._edit.setEnabled(False)
        self._delete = QPushButton(tr("configs.delete"))
        self._delete.setObjectName("DangerButton")
        self._delete.setToolTip(tr("configs.delete.tip"))
        self._delete.setEnabled(False)
        self._template_label = QLabel(tr("configs.template"))
        self._platform_label = QLabel(tr("configs.platform"))
        self._screen_label = QLabel(tr("configs.screen"))
        self._timezone_label = QLabel(tr("configs.timezone"))
        self.add_flow_row(
            glued_pair(self._template_label, self._template),
            glued_pair(self._platform_label, self._platform),
            glued_pair(self._screen_label, self._resolution),
            glued_pair(self._timezone_label, self._timezone_filter),
            self._generate,
        )
        self.add_flow_row(
            self._new,
            self._edit,
            self._delete,
        )
        self._hint = self.make_hint(tr("configs.hint"))
        self.add_widget(self._hint)

        self._list = QListWidget()
        self._list.setObjectName("ConfigList")
        self.add_widget(self._list, 1)

        self._result = QLabel(tr("configs.idle"))
        self._result.setObjectName("ResultLabel")
        self.add_control_row(self._result)

        self._rebuild_combos(keep=False)
        self._generate.clicked.connect(self._generate_config)
        self._new.clicked.connect(self._new_config)
        self._edit.clicked.connect(self._edit_config)
        self._delete.clicked.connect(self._delete_config)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self.reload()

    # ------------------------------------------------------------ retranslate

    def retranslate(self) -> None:
        self.set_title(tr("configs.title"), tr("configs.kicker"))
        self._total._label.setText(tr("metric.total"))
        self._template_label.setText(tr("configs.template"))
        self._platform_label.setText(tr("configs.platform"))
        self._screen_label.setText(tr("configs.screen"))
        self._timezone_label.setText(tr("configs.timezone"))
        self._rebuild_combos(keep=True)
        self._timezone_filter.setToolTip(tr("configs.timezone.tip"))
        self._generate.setText(tr("configs.generate"))
        self._generate.setToolTip(tr("configs.generate.tip"))
        self._new.setText(tr("configs.new"))
        self._new.setToolTip(tr("configs.new.tip"))
        self._edit.setText(tr("configs.edit"))
        self._edit.setToolTip(tr("configs.edit.tip"))
        self._delete.setText(tr("configs.delete"))
        self._delete.setToolTip(tr("configs.delete.tip"))
        self._hint.setText(tr("configs.hint"))
        if self._result.text() in ("Idle.", "Готов."):
            self._result.setText(tr("configs.idle"))

    def _rebuild_combos(self, keep: bool) -> None:
        tpl_data = self._template.currentData() if keep and self._template.count() else None
        plat_text = self._platform.currentText() if keep and self._platform.count() else None
        res_index = self._resolution.currentIndex() if keep and self._resolution.count() else 0
        tz_data = self._timezone_filter.currentData() if keep and self._timezone_filter.count() else None
        rnd = tr("configs.random")

        self._template.blockSignals(True)
        try:
            self._template.clear()
            self._template.addItem(rnd, None)
            if tpl_data:
                self._template.addItem(str(tpl_data), tpl_data)
        finally:
            self._template.blockSignals(False)
        self._platform.blockSignals(True)
        try:
            self._platform.clear()
            self._platform.addItems([rnd, "windows", "macos", "linux"])
            if plat_text and plat_text != rnd:
                idx = self._platform.findText(plat_text)
                if idx >= 0:
                    self._platform.setCurrentIndex(idx)
        finally:
            self._platform.blockSignals(False)
        self._resolution.blockSignals(True)
        try:
            self._resolution.clear()
            for label, _, _ in _RESOLUTIONS:
                self._resolution.addItem(rnd if label == _RANDOM_SIZE else label)
            if 0 <= res_index < self._resolution.count():
                self._resolution.setCurrentIndex(res_index)
        finally:
            self._resolution.blockSignals(False)
        self._timezone_filter.blockSignals(True)
        try:
            self._timezone_filter.setToolTip(tr("configs.timezone.tip"))
            self._timezone_filter.clear()
            self._timezone_filter.addItem(rnd, None)
            for zone in SUPPORTED_TIMEZONES:
                self._timezone_filter.addItem(zone, zone)
            if tz_data:
                idx = self._timezone_filter.findData(tz_data)
                if idx >= 0:
                    self._timezone_filter.setCurrentIndex(idx)
            self._timezone_filter.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            self._timezone_filter.setMinimumContentsLength(14)
        finally:
            self._timezone_filter.blockSignals(False)

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
        if platform == tr("configs.random"):
            platform = None
        _, width, height = _RESOLUTIONS[self._resolution.currentIndex()]
        timezone = self._timezone_filter.currentData()

        self._generate.setEnabled(False)
        self._result.setText(tr("configs.generating"))
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
        self._result.setText(tr("configs.creating", name=name))
        self._runner.submit(
            workers.tasks.create_configuration(self._container, name, **values),
            on_result=lambda cfg: self._result.setText(
                tr("configs.created", id=cfg.id, name=cfg.name,
                   tz=cfg.timezone or tr("configs.no.timezone"))
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self.reload,
        )

    def _edit_config(self) -> None:
        configuration_id = self._selected_id()
        if configuration_id is None:
            return
        self._result.setText(tr("configs.loading", id=configuration_id))
        self._runner.submit(
            workers.tasks.get_configuration(self._container, configuration_id),
            on_result=self._open_edit_dialog,
            on_error=lambda exc: show_error(self, exc),
        )

    def _open_edit_dialog(self, config: object) -> None:
        dialog = ConfigDialog(config, parent=self)
        if dialog.exec() != ConfigDialog.DialogCode.Accepted:
            self._result.setText(tr("configs.edit.cancelled"))
            return
        values = dialog.values()
        name = values.pop("name")
        self._result.setText(tr("configs.saving", id=config.id))
        self._runner.submit(
            workers.tasks.update_configuration(
                self._container, config.id, name=name, **values
            ),
            on_result=lambda cfg: self._result.setText(
                tr("configs.updated", id=cfg.id, name=cfg.name,
                   tz=cfg.timezone or tr("configs.no.timezone"))
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
            tr("configs.delete.dialog"),
            tr("configs.delete.question", id=configuration_id),
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self._delete.setEnabled(False)
        self._result.setText(tr("configs.deleting", id=configuration_id))
        self._runner.submit(
            workers.tasks.delete_configuration(self._container, configuration_id),
            on_result=lambda _: self._result.setText(
                tr("configs.deleted", id=configuration_id)
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._reload_and_enable([self._delete]),
        )

    def _reload_and_enable(self, widgets: list) -> None:
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
        current = self._template.currentData()
        self._template.blockSignals(True)
        try:
            self._template.clear()
            self._template.addItem(tr("configs.random"), None)
            for name in templates or []:
                self._template.addItem(name, name)
            if current:
                idx = self._template.findData(current)
                if idx >= 0:
                    self._template.setCurrentIndex(idx)
        finally:
            self._template.blockSignals(False)

    def _apply_summary(self, summary: object) -> None:
        self._total.set_value(summary.configurations)

    def _apply_configs(self, configurations: object) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for cfg in configurations or []:
            item = QListWidgetItem(
                f"#{cfg.id:03d} · {cfg.name} · {cfg.platform or tr('configs.no.platform')} · "
                f"{cfg.screen_width}×{cfg.screen_height} · "
                f"{cfg.language_tag or tr('configs.no.lang')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, cfg.id)
            self._list.addItem(item)
        self._list.scrollToBottom()
        self._list.blockSignals(False)

    def _apply_generated(self, config: object) -> None:
        platform = config.platform or tr("configs.no.platform")
        self._result.setText(
            tr("configs.generated", id=config.id, name=config.name, platform=platform,
               w=config.screen_width, h=config.screen_height,
               lang=config.language_tag,
               tz=config.timezone or tr("configs.no.timezone"))
        )
        self.reload()
