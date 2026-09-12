"""Profile edit dialog: rename / reassign configuration / reassign proxy."""

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
from app.gui.i18n import tr
from app.gui.utils.flags import country_label

if TYPE_CHECKING:
    from app.domain.models.proxy import ProxyWithCheck


class ProfileEditDialog(QDialog):
    def __init__(
        self,
        profile,
        configurations: list,
        proxies: list,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.profile.title", name=profile.name))
        self.setMinimumWidth(480)
        self._profile = profile

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel(tr("dlg.profile.header", id=profile.id, name=profile.name))
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        subtitle = QLabel(tr("dlg.profile.subtitle"))
        subtitle.setObjectName("HintLabel")
        layout.addWidget(subtitle)

        identity = QGroupBox(tr("dlg.group.identity"))
        identity_form = QFormLayout(identity)
        identity_form.setSpacing(10)

        self._name = QLineEdit(profile.name)
        self._name.setPlaceholderText(tr("dlg.profile.name.ph"))
        self._name.setToolTip(tr("dlg.profile.name.tip"))
        self._name.setClearButtonEnabled(True)
        identity_form.addRow(tr("dlg.name"), self._name)

        self._name_error = QLabel("")
        self._name_error.setObjectName("ErrorLabel")
        self._name_error.hide()
        identity_form.addRow("", self._name_error)
        layout.addWidget(identity)

        fingerprint = QGroupBox(tr("dlg.group.fingerprint"))
        fingerprint_form = QFormLayout(fingerprint)
        fingerprint_form.setSpacing(10)

        self._config = QComboBox()
        self._config.setToolTip(tr("dlg.config.tip"))
        for cfg in configurations:
            label = (
                f"#{cfg.id:03d} · {cfg.name} · "
                f"{cfg.platform or '—'} · {cfg.screen_width}×{cfg.screen_height}"
            )
            self._config.addItem(label, cfg.id)
        self._select(self._config, profile.configuration_id)
        fingerprint_form.addRow(tr("dlg.configuration"), self._config)

        config_hint = QLabel(tr("dlg.config.hint", n=len(configurations)))
        config_hint.setObjectName("HintLabel")
        fingerprint_form.addRow("", config_hint)
        layout.addWidget(fingerprint)

        network = QGroupBox(tr("dlg.group.network"))
        network_form = QFormLayout(network)
        network_form.setSpacing(10)

        proxy_row = QHBoxLayout()
        self._proxy = QComboBox()
        self._proxy.setToolTip(tr("dlg.proxy.tip"))
        self._populate_proxies(proxies)
        proxy_row.addWidget(self._proxy, 1)
        network_form.addRow(tr("dlg.proxy"), proxy_row)

        proxy_hint = QLabel(tr("dlg.proxy.hint"))
        proxy_hint.setObjectName("HintLabel")
        network_form.addRow("", proxy_hint)
        layout.addWidget(network)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("PrimaryButton")
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setToolTip(tr("dlg.save.tip"))
        save_btn = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setDefault(True)
        save_btn.setAutoDefault(True)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._name.textChanged.connect(self._validate)
        self._proxy.currentIndexChanged.connect(lambda _index: self._validate())
        self._config.currentIndexChanged.connect(lambda _index: self._validate())
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
        ok = bool(self.name)
        save = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setEnabled(ok)
        if ok:
            self._name_error.hide()
        else:
            self._name_error.setText(tr("dlg.name.empty"))
            self._name_error.show()

    # --------------------------------------------------------------- proxy list

    def _populate_proxies(self, proxies: list) -> None:
        self._proxy.clear()
        self._proxy.addItem(tr("dlg.proxy.none"), None)
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
                    f"{self._status_note(assigned)} · {tr('dlg.proxy.assigned')}"
                )
                self._proxy.addItem(label, self._profile.proxy_id)
                item = self._proxy.model().item(self._proxy.count() - 1)
                item.setEnabled(False)
        self._select(self._proxy, self._profile.proxy_id)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _status_note(row) -> str:
        if row.check_error is not None:
            return tr("dlg.proxy.dead")
        return f"{country_label(row.country_code, row.country)} · {row.latency_ms}ms"

    @staticmethod
    def _select(combo: QComboBox, value: int | None) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
