"""Profile edit dialog: rename / reassign configuration / reassign proxy.

Stays a pure QDialog: it only prepares user choices. The actual persistence
runs through ``ProfileService.update_profile`` on a background worker.

UX notes (audit fixes):
* fields are grouped (Identity / Fingerprint / Network) instead of one flat
  form — the eye scans one decision at a time;
* every field has a placeholder + tooltip + inline hint, so first-time users
  never guess what "Configuration" means;
* the name is validated live: empty names disable Save and show an inline
  error instead of silently ignoring the dialog (previously ``name`` was
  returned stripped but the dialog never told the user why nothing happened).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from app.domain.enums.proxy_status import ProxyStatus
from app.gui.utils.flags import country_label

if TYPE_CHECKING:
    from app.domain.models.proxy import ProxyWithCheck

_NO_PROXY = "— no proxy —"


class ProfileEditDialog(QDialog):
    def __init__(
        self,
        profile,
        configurations: list,
        proxies: list,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit profile · {profile.name}")
        self.setMinimumWidth(480)
        self._profile = profile

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel(f"Edit #{profile.id:03d} · {profile.name}")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        subtitle = QLabel("Only changed fields are saved — the rest stays untouched.")
        subtitle.setObjectName("HintLabel")
        layout.addWidget(subtitle)

        # --- Group 1: identity -------------------------------------------------
        identity = QGroupBox("1 · Identity")
        identity_form = QFormLayout(identity)
        identity_form.setSpacing(10)

        self._name = QLineEdit(profile.name)
        self._name.setPlaceholderText("e.g. shop-01 · minimum 1 character")
        self._name.setToolTip("Profile name — shown in the list and used for the data dir.")
        self._name.setClearButtonEnabled(True)
        identity_form.addRow("Name *", self._name)

        self._name_error = QLabel("")
        self._name_error.setObjectName("ErrorLabel")
        self._name_error.hide()
        identity_form.addRow("", self._name_error)
        layout.addWidget(identity)

        # --- Group 2: fingerprint ----------------------------------------------
        fingerprint = QGroupBox("2 · Fingerprint")
        fingerprint_form = QFormLayout(fingerprint)
        fingerprint_form.setSpacing(10)

        self._config = QComboBox()
        self._config.setToolTip("Browser fingerprint (OS, screen, locale). Generate new ones on the Configurations tab.")
        for cfg in configurations:
            label = (
                f"#{cfg.id:03d} · {cfg.name} · "
                f"{cfg.platform or '—'} · {cfg.screen_width}×{cfg.screen_height}"
            )
            self._config.addItem(label, cfg.id)
        self._select(self._config, profile.configuration_id)
        fingerprint_form.addRow("Configuration", self._config)

        config_hint = QLabel(f"{len(configurations)} stored · change applies on next launch")
        config_hint.setObjectName("HintLabel")
        fingerprint_form.addRow("", config_hint)
        layout.addWidget(fingerprint)

        # --- Group 3: network ---------------------------------------------------
        network = QGroupBox("3 · Network")
        network_form = QFormLayout(network)
        network_form.setSpacing(10)

        proxy_row = QHBoxLayout()
        self._proxy = QComboBox()
        self._proxy.setToolTip("Only WORKING proxies are offered. A dead assignment stays visible but locked so you never clear it by accident.")
        self._populate_proxies(proxies)
        proxy_row.addWidget(self._proxy, 1)
        network_form.addRow("Proxy", proxy_row)

        proxy_hint = QLabel("working-only list · dead assignment is kept locked")
        proxy_hint.setObjectName("HintLabel")
        network_form.addRow("", proxy_hint)
        layout.addWidget(network)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("PrimaryButton")
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setToolTip("Save only the fields you changed (Enter)")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._name.textChanged.connect(self._validate)
        self._validate()

    # ------------------------------------------------------------ values

    @property
    def name(self) -> str:
        return self._name.text().strip()

    @property
    def configuration_id(self) -> int | None:
        return self._config.currentData()

    @property
    def proxy_id(self) -> int | None:
        return self._proxy.currentData()

    # ------------------------------------------------------------ validation

    def _validate(self) -> None:
        """Live validation: empty name blocks Save with an inline message."""
        ok = bool(self.name)
        save = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setEnabled(ok)
        if ok:
            self._name_error.hide()
        else:
            self._name_error.setText("Name cannot be empty — give the profile a name.")
            self._name_error.show()

    # --------------------------------------------------------------- proxy list

    def _populate_proxies(self, proxies: list) -> None:
        self._proxy.clear()
        self._proxy.addItem(_NO_PROXY, None)
        for row in proxies:
            proxy = row.proxy
            if proxy.status is not ProxyStatus.WORKING:
                continue
            if row.check_error is not None:
                continue
            label = (
                f"{proxy.id:05d} · {proxy.host_port} · "
                f"{country_label(row.country_code, row.country)} · "
                f"{row.latency_ms}ms"
            )
            self._proxy.addItem(label, proxy.id)
        # Keep the profile's current assignment visible but locked so saving an
        # unrelated edit never silently clears a proxy that just died.
        if (
            self._profile.proxy_id is not None
            and self._proxy.findData(self._profile.proxy_id) < 0
        ):
            assigned = next(
                (r for r in proxies if r.proxy.id == self._profile.proxy_id),
                None,
            )
            if assigned is not None:
                proxy = assigned.proxy
                label = (
                    f"{proxy.id:05d} · {proxy.host_port} · "
                    f"{self._status_note(assigned)} · (assigned)"
                )
                self._proxy.addItem(label, self._profile.proxy_id)
                item = self._proxy.model().item(self._proxy.count() - 1)
                item.setEnabled(False)
        self._select(self._proxy, self._profile.proxy_id)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _status_note(row) -> str:
        if row.check_error is not None:
            return "dead"
        return f"{country_label(row.country_code, row.country)} · {row.latency_ms}ms"

    @staticmethod
    def _select(combo: QComboBox, value: int | None) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
