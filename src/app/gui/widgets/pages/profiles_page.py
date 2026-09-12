"""Profiles page: a real list of profiles with lifecycle + edit actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.gui import workers
from app.gui.dialogs.error_dialog import show_error
from app.gui.dialogs.profile_edit_dialog import ProfileEditDialog
from app.gui.i18n import tr
from app.gui.utils.flags import country_label
from app.gui.utils.preferences import Preferences
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container
    from app.gui.workers.task_runner import TaskRunner


class ProfilesPage(PlaceholderPage):
    def __init__(
        self, container: "Container", runner: "TaskRunner", parent=None
    ) -> None:
        super().__init__(tr("profiles.title"), kicker=tr("profiles.kicker"))
        self._container = container
        self._runner = runner
        self._profiles: list = []
        self._configs: list = []
        self._proxy_rows: list = []
        self._prefs = Preferences(container.settings)

        self._total, self._running = self.add_metrics(
            tr("metric.total"), tr("metric.running")
        )

        self._new = QPushButton(tr("profiles.new"))
        self._new.setObjectName("PrimaryButton")
        self._new.setToolTip(tr("profiles.new.tip"))
        self._duplicate = QPushButton(tr("profiles.duplicate"))
        self._duplicate.setToolTip(tr("profiles.duplicate.tip"))
        self._edit = QPushButton(tr("profiles.edit"))
        self._edit.setToolTip(tr("profiles.edit.tip"))
        self._delete = QPushButton(tr("profiles.delete"))
        self._delete.setObjectName("DangerButton")
        self._delete.setToolTip(tr("profiles.delete.tip"))
        self._start = QPushButton(tr("profiles.start"))
        self._start.setToolTip(tr("profiles.start.tip"))
        self._stop = QPushButton(tr("profiles.stop"))
        self._stop.setToolTip(tr("profiles.stop.tip"))
        self._restart = QPushButton(tr("profiles.restart"))
        self._restart.setToolTip(tr("profiles.restart.tip"))
        self.add_flow_row(
            self._new, self._duplicate, self._edit, self._delete,
            self._start, self._stop, self._restart,
        )
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._create_profile)
        QShortcut(QKeySequence("Delete"), self, activated=self._delete_profile)

        self._list = QListWidget()
        self._list.setObjectName("ProfileList")
        self._list.setToolTip(tr("profiles.list.tip"))
        self.add_widget(self._list, 1)

        self._empty = self.make_empty_state(tr("profiles.empty"))
        self._empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay = QVBoxLayout(self._list)
        overlay.setContentsMargins(0, 0, 0, 0)
        overlay.addWidget(self._empty, 0, Qt.AlignmentFlag.AlignCenter)

        self._hint = self.make_hint(tr("profiles.hint"))
        self.add_widget(self._hint)

        self._result = QLabel(tr("profiles.idle"))
        self._result.setObjectName("ResultLabel")
        self.add_control_row(self._result)

        self._new.clicked.connect(self._create_profile)
        self._duplicate.clicked.connect(self._duplicate_profile)
        self._edit.clicked.connect(self._edit_profile)
        self._delete.clicked.connect(self._delete_profile)
        self._start.clicked.connect(lambda: self._lifecycle("start"))
        self._stop.clicked.connect(lambda: self._lifecycle("stop"))
        self._restart.clicked.connect(lambda: self._lifecycle("restart"))
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda _item: self._edit_profile())
        self._edit_state: dict | None = None

        self._sync_buttons()
        self.reload()

    # ------------------------------------------------------------ retranslate

    def retranslate(self) -> None:
        self.set_title(tr("profiles.title"), tr("profiles.kicker"))
        self._total._label.setText(tr("metric.total"))
        self._running._label.setText(tr("metric.running"))
        self._new.setText(tr("profiles.new"))
        self._new.setToolTip(tr("profiles.new.tip"))
        self._duplicate.setText(tr("profiles.duplicate"))
        self._duplicate.setToolTip(tr("profiles.duplicate.tip"))
        self._edit.setText(tr("profiles.edit"))
        self._edit.setToolTip(tr("profiles.edit.tip"))
        self._delete.setText(tr("profiles.delete"))
        self._delete.setToolTip(tr("profiles.delete.tip"))
        self._start.setText(tr("profiles.start"))
        self._start.setToolTip(tr("profiles.start.tip"))
        self._stop.setText(tr("profiles.stop"))
        self._stop.setToolTip(tr("profiles.stop.tip"))
        self._restart.setText(tr("profiles.restart"))
        self._restart.setToolTip(tr("profiles.restart.tip"))
        self._list.setToolTip(tr("profiles.list.tip"))
        self._empty.setText(tr("profiles.empty"))
        self._hint.setText(tr("profiles.hint"))
        if self._result.text() in ("Idle.", "Готов."):
            self._result.setText(tr("profiles.idle"))
        self._render_list()

    # ------------------------------------------------------------ actions

    def reload(self) -> None:
        self._runner.submit(
            workers.tasks.summary(self._container),
            on_result=self._apply_summary,
            on_error=lambda exc: show_error(self, exc),
        )
        self._runner.submit(
            workers.tasks.list_configurations(self._container),
            on_result=lambda configs: setattr(
                self, "_configs", list(configs or [])
            ),
            on_error=lambda exc: show_error(self, exc),
        )
        self._runner.submit(
            workers.tasks.list_profiles(self._container),
            on_result=self._apply_profiles,
            on_error=lambda exc: show_error(self, exc),
        )
        self._runner.submit(
            workers.tasks.list_proxies(self._container),
            on_result=self._apply_proxy_rows,
            on_error=lambda exc: show_error(self, exc),
        )

    def _create_profile(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, tr("profiles.new.dialog"), tr("profiles.new.name")
        )
        name = (name or "").strip()
        if not ok:
            return
        if not name:
            self._result.setText(tr("profiles.name.empty"))
            return
        if any(p.name.lower() == name.lower() for p in self._profiles):
            self._result.setText(tr("profiles.name.exists", name=name))
            return
        self._new.setEnabled(False)
        self._result.setText(tr("profiles.creating", name=name))
        self._runner.submit(
            workers.tasks.create_profile(self._container, name),
            on_result=lambda profile: self._result.setText(
                tr("profiles.created", id=profile.id, name=profile.name)
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._reload_and_enable([self._new]),
        )

    def _edit_profile(self) -> None:
        profile_id = self._selected_id()
        profile = self._profile_by_id(profile_id) if profile_id else None
        if profile is None:
            return
        self._edit.setEnabled(False)
        self._result.setText(tr("profiles.loading", id=profile.id))
        self._edit_state = {"profile": profile, "configs": None, "proxies": None}

        def _edit_failed(exc: object) -> None:
            self._edit_state = None
            show_error(self, exc)
            self._sync_buttons()

        self._runner.submit(
            workers.tasks.list_configurations(self._container),
            on_result=lambda configs: self._loaded_edit_data(
                configs=list(configs or [])
            ),
            on_error=_edit_failed,
            on_finished=self._sync_edit_loading,
        )
        self._runner.submit(
            workers.tasks.list_proxies(self._container),
            on_result=lambda rows: self._loaded_edit_data(
                proxies=list(rows or [])
            ),
            on_error=_edit_failed,
            on_finished=self._sync_edit_loading,
        )

    def _sync_edit_loading(self) -> None:
        if getattr(self, "_edit_state", None) is not None:
            return
        self._sync_buttons()

    def _loaded_edit_data(self, configs: list | None = None, proxies: list | None = None) -> None:
        state = getattr(self, "_edit_state", None)
        if state is None:
            return
        if configs is not None:
            state["configs"] = configs
        if proxies is not None:
            state["proxies"] = proxies
        if state["configs"] is None or state["proxies"] is None:
            return
        self._configs = state["configs"]
        self._proxy_rows = state["proxies"]
        self._edit_state = None
        profile = state["profile"]
        dialog = ProfileEditDialog(
            profile,
            state["configs"],
            state["proxies"],
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            self._result.setText(tr("profiles.edit.cancelled"))
            self._sync_buttons()
            return
        config_id = dialog.configuration_id
        proxy_id = dialog.proxy_id
        new_name = dialog.name if dialog.name != profile.name else None
        new_config_id = (
            config_id
            if config_id is not None and config_id != profile.configuration_id
            else None
        )
        proxy_changed = proxy_id != profile.proxy_id
        if new_name is None and new_config_id is None and not proxy_changed:
            self._result.setText(tr("profiles.no.changes"))
            self._sync_buttons()
            return
        self._edit.setEnabled(False)
        self._result.setText(tr("profiles.saving", id=profile.id))

        def _save(_progress) -> None:
            if new_name is not None:
                self._container.profiles.update_profile(
                    profile.id, name=new_name, auto_config=False
                )
            if new_config_id is not None:
                self._container.profiles.assign_configuration(
                    profile.id, new_config_id
                )
            if proxy_changed:
                self._container.profiles.assign_proxy(
                    profile.id, proxy_id, auto_config=new_config_id is None
                )
            return None

        self._runner.submit(
            _save,
            on_result=lambda _: self._result.setText(
                tr("profiles.updated", id=profile.id)
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._reload_and_enable([self._edit]),
        )

    def _duplicate_profile(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        self._duplicate.setEnabled(False)
        self._result.setText(tr("profiles.duplicating", id=profile_id))
        self._runner.submit(
            workers.tasks.duplicate_profile(self._container, profile_id),
            on_result=lambda profile: self._result.setText(
                tr("profiles.duplicated", id=profile.id, name=profile.name)
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._reload_and_enable([self._duplicate]),
        )

    def _confirm_destructive(self, title: str, text: str) -> bool:
        if not self._prefs.get_bool(Preferences.KEY_CONFIRM_DESTRUCTIVE, default=True):
            return True
        answer = QMessageBox.question(self, title, text)
        return answer is QMessageBox.StandardButton.Yes

    def _delete_profile(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        profile = self._profile_by_id(profile_id)
        name = profile.name if profile is not None else f"#{profile_id}"
        if not self._confirm_destructive(
            tr("profiles.delete.dialog"),
            tr("profiles.delete.question", id=profile_id, name=name),
        ):
            return
        self._delete.setEnabled(False)
        self._result.setText(tr("profiles.deleting", id=profile_id))
        self._runner.submit(
            workers.tasks.delete_profile(self._container, profile_id),
            on_result=lambda _: self._result.setText(
                tr("profiles.deleted", id=profile_id, name=name)
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=lambda: self._reload_and_enable([self._delete]),
        )

    def _lifecycle(self, action: str) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        task = {
            "start": workers.tasks.start_profile,
            "stop": workers.tasks.stop_profile,
            "restart": workers.tasks.restart_profile,
        }[action](self._container, profile_id)
        group = (self._start, self._stop, self._restart)
        for widget in group:
            widget.setEnabled(False)
        action_ru = {
            "start": tr("profiles.action.start"),
            "stop": tr("profiles.action.stop"),
            "restart": tr("profiles.action.restart"),
        }[action]
        self._result.setText(tr("profiles.actioning", action=action_ru, id=profile_id))
        self._runner.submit(
            task,
            on_result=lambda profile: self._result.setText(
                tr("profiles.status", id=profile.id, status=self._status_text(profile.status))
            ),
            on_error=lambda exc: self._lifecycle_error(action, profile_id, exc),
            on_finished=lambda: (
                self.reload(),
                [w.setEnabled(True) for w in group],
            ),
        )

    @staticmethod
    def _status_text(status) -> str:
        raw = status.value if hasattr(status, "value") else str(status)
        if raw.upper() == "RUNNING":
            return tr("profiles.status.running")
        return raw

    def _lifecycle_error(self, action: str, profile_id: int, exc: object) -> None:
        if action in ("start", "restart"):
            offer = self._autofix_offer(profile_id)
            if offer is not None:
                label, apply = offer
                show_error(self, exc, actions=[(label, apply)])
                return
        show_error(self, exc)

    def _autofix_offer(self, profile_id: int):
        try:
            profile = self._container.profiles.get_profile(profile_id)
            report = self._container.profiles.diagnose_profile(
                profile_id, probe_google=False
            )
        except Exception:
            return None
        if profile is None or profile.configuration_id is None:
            return None
        configuration_id = profile.configuration_id
        codes = {block.code for block in report.blocks}
        if "geo-timezone-mismatch" in codes:
            country = (report.facts.get("proxy_country") or "").upper() or None
            if country:
                return (
                    tr("profiles.fix"),
                    lambda: self._apply_geo_autofix(configuration_id, country),
                )
        if "ua-binary-drift" in codes:
            try:
                major = int(report.facts.get("binary_major"))
            except (TypeError, ValueError):
                major = None
            if major:
                return (
                    tr("profiles.fix"),
                    lambda: self._apply_version_autofix(
                        configuration_id, major
                    ),
                )
        return None

    def _geo_autofix(self, profile_id: int) -> tuple[int, str] | None:
        try:
            profile = self._container.profiles.get_profile(profile_id)
            report = self._container.profiles.diagnose_profile(
                profile_id, probe_google=False
            )
        except Exception:
            return None
        if not any(block.code == "geo-timezone-mismatch" for block in report.blocks):
            return None
        country = (report.facts.get("proxy_country") or "").upper() or None
        configuration_id = profile.configuration_id if profile is not None else None
        if not country or configuration_id is None:
            return None
        return configuration_id, country

    def _apply_geo_autofix(self, configuration_id: int, country: str) -> None:
        self._result.setText(tr("profiles.geo.aligning", id=configuration_id, country=country))
        self._runner.submit(
            workers.tasks.align_configuration_geo(
                self._container, configuration_id, country
            ),
            on_result=lambda cfg: self._result.setText(
                tr("profiles.geo.fixed", tz=cfg.timezone, locale=cfg.locale)
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self.reload,
        )

    def _apply_version_autofix(self, configuration_id: int, major: int) -> None:
        self._result.setText(tr("profiles.ver.regenerating", id=configuration_id, major=major))
        self._runner.submit(
            workers.tasks.align_browser_version(
                self._container, configuration_id, major
            ),
            on_result=lambda cfg: self._result.setText(
                tr("profiles.ver.fixed", major=major)
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self.reload,
        )

    # ------------------------------------------------------------ results

    def _reload_and_enable(self, widgets: list) -> None:
        self.reload()
        for widget in widgets:
            widget.setEnabled(True)

    def _apply_summary(self, summary: object) -> None:
        self._total.set_value(summary.profiles)
        self._running.set_value(summary.running_profiles)

    def _apply_profiles(self, profiles: object) -> None:
        self._profiles = list(profiles or [])
        self._render_list()

    def _apply_proxy_rows(self, rows: object) -> None:
        self._proxy_rows = list(rows or [])
        self._render_list()

    def _render_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        shown = 0
        for profile in self._profiles:
            running = (profile.status.value if hasattr(profile.status, "value") else str(profile.status)).upper() == "RUNNING"
            dot = "●" if running else "○"
            status = self._status_text(profile.status)
            label = (
                f"{dot} {profile.id:03d} · {profile.name} · "
                f"{status} · cfg: {self._config_name(profile.configuration_id)}"
            )
            note = self._proxy_note(profile.proxy_id)
            if note:
                label += f" · {note}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, profile)
            item.setToolTip(tr("profiles.row.edit.tip", name=profile.name))
            self._list.addItem(item)
            shown += 1
        self._list.blockSignals(False)
        self._empty.setVisible(shown == 0)
        self._empty.setText(tr("profiles.empty"))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_selection = self._selected_id() is not None
        for widget in (
            self._duplicate, self._edit, self._delete,
            self._start, self._stop, self._restart,
        ):
            widget.setEnabled(has_selection)

    def _selected_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        profile = item.data(Qt.ItemDataRole.UserRole)
        return profile.id if profile is not None else None

    def _profile_by_id(self, profile_id: int):
        for profile in self._profiles:
            if profile.id == profile_id:
                return profile
        return None

    def _config_name(self, configuration_id: int | None) -> str:
        if configuration_id is None:
            return tr("profiles.row.no.config")
        for cfg in self._configs:
            if cfg.id == configuration_id:
                return cfg.name
        return f"#{configuration_id}"

    def _proxy_note(self, proxy_id: int | None) -> str:
        if proxy_id is None:
            return ""
        for row in self._proxy_rows:
            proxy = getattr(row, "proxy", None)
            if proxy is not None and proxy.id == proxy_id:
                endpoint = getattr(proxy, "host_port", "") or ""
                location = country_label(
                    getattr(row, "country_code", None),
                    getattr(row, "country", None),
                )
                if endpoint:
                    return tr(
                        "profiles.row.proxy.full",
                        id=proxy_id,
                        endpoint=endpoint,
                        location=location,
                    )
                break
        return tr("profiles.row.proxy", id=proxy_id)
