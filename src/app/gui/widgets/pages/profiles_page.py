"""Profiles page: a real list of profiles with lifecycle + edit actions.

Layout after the UX audit (keeps the 19–86 ledger system):

* one primary action (NEW, filled) + lifecycle group + dashed danger DELETE;
* double-click / Enter edits, Delete key asks for confirmation;
* empty state explains the next step instead of showing a blank list.
"""

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
)

from app.gui import workers
from app.gui.dialogs.error_dialog import show_error
from app.gui.dialogs.profile_edit_dialog import ProfileEditDialog
from app.gui.utils.preferences import Preferences
from app.gui.widgets.placeholder_page import PlaceholderPage

if TYPE_CHECKING:
    from app.di import Container
    from app.gui.workers.task_runner import TaskRunner


class ProfilesPage(PlaceholderPage):
    def __init__(
        self, container: "Container", runner: "TaskRunner", parent=None
    ) -> None:
        super().__init__("Profiles", kicker="SECTION 01")
        self._container = container
        self._runner = runner
        self._profiles: list = []
        self._configs: list = []
        self._proxy_rows: list = []
        self._prefs = Preferences(container.settings)

        self._total, self._running = self.add_metrics("TOTAL", "RUNNING")

        self._new = QPushButton("NEW")
        self._new.setObjectName("PrimaryButton")
        self._new.setToolTip("Create profile (Ctrl+N)")
        self._duplicate = QPushButton("DUPLICATE")
        self._duplicate.setToolTip("Clone the selected profile with its browser state")
        self._edit = QPushButton("EDIT")
        self._edit.setToolTip("Edit name / configuration / proxy (Enter)")
        self._delete = QPushButton("DELETE")
        self._delete.setObjectName("DangerButton")
        self._delete.setToolTip("Delete profile with its browser data (Del)")
        self._start = QPushButton("START")
        self._start.setToolTip("Launch Chromium for the selected profile")
        self._stop = QPushButton("STOP")
        self._stop.setToolTip("Stop the running Chromium process")
        self._restart = QPushButton("RESTART")
        self._restart.setToolTip("Stop and start again")
        self.add_control_row(
            self._new, self._duplicate, self._edit, self._delete,
            self._start, self._stop, self._restart,
        )
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._create_profile)
        QShortcut(QKeySequence("Delete"), self, activated=self._delete_profile)

        self._list = QListWidget()
        self._list.setObjectName("ProfileList")
        self._list.setToolTip("Double-click a row to edit it")
        self.add_widget(self._list, 1)

        self._empty = self.make_empty_state(
            "No profiles yet — press NEW to create the first one."
        )
        self._empty.hide()
        self.add_widget(self._empty)

        self.add_widget(
            self.make_hint("Tip: double-click a row to edit · Enter edits · Del deletes.")
        )

        self._result = QLabel("Idle.")
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

    def _create_profile(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "New profile", "Name:")
        name = (name or "").strip()
        if not ok:
            return
        if not name:
            self._result.setText("Name is empty — profile not created.")
            return
        if any(p.name.lower() == name.lower() for p in self._profiles):
            self._result.setText(f"A profile named '{name}' already exists.")
            return
        self._new.setEnabled(False)
        self._result.setText(f"Creating profile '{name}'…")
        self._runner.submit(
            workers.tasks.create_profile(self._container, name),
            on_result=lambda profile: self._result.setText(
                f"Profile #{profile.id:03d} '{profile.name}' created."
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
        self._result.setText(f"Loading profile #{profile.id:03d}…")
        self._edit_state = {"profile": profile, "configs": None, "proxies": None}
        self._runner.submit(
            workers.tasks.list_configurations(self._container),
            on_result=lambda configs: self._loaded_edit_data(
                configs=list(configs or [])
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self._sync_buttons,
        )
        self._runner.submit(
            workers.tasks.list_proxies(self._container),
            on_result=lambda rows: self._loaded_edit_data(
                proxies=list(rows or [])
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self._sync_buttons,
        )

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
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            self._result.setText("Edit cancelled.")
            return
        config_id = dialog.configuration_id
        proxy_id = dialog.proxy_id
        changed = False
        if dialog.name and dialog.name != profile.name:
            self._runner.submit(
                workers.tasks.update_profile(
                    self._container, profile.id, name=dialog.name
                ),
                on_error=lambda exc: show_error(self, exc),
            )
            changed = True
        if config_id is not None and config_id != profile.configuration_id:
            self._runner.submit(
                workers.tasks.assign_configuration(
                    self._container, profile.id, config_id
                ),
                on_error=lambda exc: show_error(self, exc),
            )
            changed = True
        if proxy_id != profile.proxy_id:
            self._runner.submit(
                workers.tasks.assign_proxy(
                    self._container, profile.id, proxy_id
                ),
                on_error=lambda exc: show_error(self, exc),
            )
            changed = True
        if changed:
            self._result.setText(f"Profile #{profile.id:03d} updated.")
            self.reload()
        else:
            self._result.setText("No changes.")

    def _duplicate_profile(self) -> None:
        profile_id = self._selected_id()
        if profile_id is None:
            return
        self._duplicate.setEnabled(False)
        self._result.setText(f"Duplicating profile #{profile_id:03d}…")
        self._runner.submit(
            workers.tasks.duplicate_profile(self._container, profile_id),
            on_result=lambda profile: self._result.setText(
                f"Profile #{profile.id:03d} '{profile.name}' duplicated."
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
            "Delete profile",
            f"Delete profile #{profile_id:03d} · {name} and its browser data?",
        ):
            return
        self._delete.setEnabled(False)
        self._result.setText(f"Deleting profile #{profile_id:03d}…")
        self._runner.submit(
            workers.tasks.delete_profile(self._container, profile_id),
            on_result=lambda _: self._result.setText(
                f"Profile #{profile_id:03d} · {name} deleted."
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
        button = {
            "start": self._start,
            "stop": self._stop,
            "restart": self._restart,
        }[action]
        group = (self._start, self._stop, self._restart)
        for widget in group:
            widget.setEnabled(False)
        self._result.setText(f"{action.title()}ting profile {profile_id}…")
        self._runner.submit(
            task,
            on_result=lambda profile: self._result.setText(
                f"Profile {profile.id} · {profile.status.value}"
            ),
            on_error=lambda exc: self._lifecycle_error(action, profile_id, exc),
            on_finished=lambda: (
                self.reload(),
                [w.setEnabled(True) for w in group],
            ),
        )

    def _lifecycle_error(self, action: str, profile_id: int, exc: object) -> None:
        """Start/restart failure: offer one-click auto-fixes when available.

        * ``geo-timezone-mismatch`` -> "Fix timezone automatically" (aligns
          the configuration to the proxy exit country);
        * ``ua-binary-drift`` -> "Regenerate for Chrome/<installed>
          automatically" (rebuilds UA + Client Hints for the binary).
        Anything else stays a plain error dialog.
        """
        if action in ("start", "restart"):
            offer = self._autofix_offer(profile_id)
            if offer is not None:
                label, apply = offer
                show_error(self, exc, actions=[(label, apply)])
                return
        show_error(self, exc)

    def _autofix_offer(self, profile_id: int):
        """(button_label, apply_callback) for a blocked launch, or None."""
        try:
            profile = self._container.profiles.get_profile(profile_id)
            report = self._container.profiles.diagnose_profile(
                profile_id, probe_google=False
            )
        except Exception:  # noqa: BLE001 - diagnostics must never hide the error
            return None
        if profile is None or profile.configuration_id is None:
            return None
        configuration_id = profile.configuration_id
        codes = {block.code for block in report.blocks}
        if "geo-timezone-mismatch" in codes:
            country = (report.facts.get("proxy_country") or "").upper() or None
            if country:
                return (
                    "Fix timezone automatically",
                    lambda: self._apply_geo_autofix(configuration_id, country),
                )
        if "ua-binary-drift" in codes:
            try:
                major = int(report.facts.get("binary_major"))
            except (TypeError, ValueError):
                major = None
            if major:
                return (
                    f"Regenerate for Chrome/{major} automatically",
                    lambda: self._apply_version_autofix(
                        configuration_id, major
                    ),
                )
        return None

    def _geo_autofix(self, profile_id: int) -> tuple[int, str] | None:
        """(configuration_id, proxy_country) for a timezone-blocked profile.

        Returns None when the failure is anything else (or the facts needed
        for the fix are unavailable) — then the dialog stays a plain error.
        """
        try:
            profile = self._container.profiles.get_profile(profile_id)
            report = self._container.profiles.diagnose_profile(
                profile_id, probe_google=False
            )
        except Exception:  # noqa: BLE001 - diagnostics must never hide the error
            return None
        if not any(block.code == "geo-timezone-mismatch" for block in report.blocks):
            return None
        country = (report.facts.get("proxy_country") or "").upper() or None
        configuration_id = profile.configuration_id if profile is not None else None
        if not country or configuration_id is None:
            return None
        return configuration_id, country

    def _apply_geo_autofix(self, configuration_id: int, country: str) -> None:
        self._result.setText(
            f"Aligning configuration #{configuration_id:03d} to {country}…"
        )
        self._runner.submit(
            workers.tasks.align_configuration_geo(
                self._container, configuration_id, country
            ),
            on_result=lambda cfg: self._result.setText(
                f"Timezone auto-fixed to {cfg.timezone} ({cfg.locale}). "
                "Start the profile again."
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self.reload,
        )

    def _apply_version_autofix(self, configuration_id: int, major: int) -> None:
        self._result.setText(
            f"Regenerating configuration #{configuration_id:03d} "
            f"for Chrome/{major}…"
        )
        self._runner.submit(
            workers.tasks.align_browser_version(
                self._container, configuration_id, major
            ),
            on_result=lambda cfg: self._result.setText(
                f"Browser version auto-fixed to Chrome/{major}. "
                "Start the profile again."
            ),
            on_error=lambda exc: show_error(self, exc),
            on_finished=self.reload,
        )

    # ------------------------------------------------------------ results

    def _reload_and_enable(self, widgets: list) -> None:
        """Reload the page and restore the given control buttons.

        Used as an ``on_finished`` hook; the plain ``reload() and …`` idiom
        silently skips the re-enable because ``reload()`` returns ``None``.
        """
        self.reload()
        for widget in widgets:
            widget.setEnabled(True)

    def _apply_summary(self, summary: object) -> None:
        self._total.set_value(summary.profiles)
        self._running.set_value(summary.running_profiles)

    def _apply_profiles(self, profiles: object) -> None:
        self._profiles = list(profiles or [])
        self._render_list()

    def _render_list(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        shown = 0
        for profile in self._profiles:
            running = (profile.status.value if hasattr(profile.status, "value") else str(profile.status)).upper() == "RUNNING"
            dot = "●" if running else "○"
            label = (
                f"{dot} {profile.id:03d} · {profile.name} · "
                f"{profile.status.value} · cfg: {self._config_name(profile.configuration_id)}"
            )
            note = self._proxy_note(profile.proxy_id)
            if note:
                label += f" · {note}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, profile)
            item.setToolTip(f"Double-click to edit {profile.name}")
            self._list.addItem(item)
            shown += 1
        self._list.blockSignals(False)
        self._empty.setVisible(shown == 0)
        self._empty.setText("No profiles yet — press NEW to create the first one.")
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
            return "—"
        for cfg in self._configs:
            if cfg.id == configuration_id:
                return cfg.name
        return f"#{configuration_id}"

    @staticmethod
    def _proxy_note(proxy_id: int | None) -> str:
        if proxy_id is None:
            return ""
        return f"proxy #{proxy_id}"
