"""Downloading Chrome: ask Google, fetch the archive, unpack and check it - one dialog, one progress bar."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QProgressBar, QWidget

from antidetect.domain.errors import DownloadCancelled
from antidetect.gui import workers
from antidetect.gui.components import BaseDialog, label
from antidetect.gui.errors import friendly_error_text
from antidetect.i18n import tr

if TYPE_CHECKING:
    from antidetect.container import Container
    from antidetect.gui.workers import TaskRunner

_BAR_STEPS = 1000


class BrowserDownloadDialog(BaseDialog):
    """Starts by itself when shown and closes by itself when done.

    ``installed`` is what was installed; ``already`` is true when the newest Chrome was already
    here (nothing was downloaded). Either way ``accepted`` means "the app's Chrome is ready".
    """

    def __init__(self, container: "Container", runner: "TaskRunner", parent: QWidget | None = None) -> None:
        super().__init__(tr("browser.dl.title"), tr("browser.dl.checking"), parent=parent, width=500)
        self._container = container
        self._runner = runner
        self.installed = None
        self.already = False
        self.release = None
        self._state = "idle"                 # checking | downloading | installing | error | closed
        self._cancel = threading.Event()
        self._started = False

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 0)
        self.body.addWidget(self._bar)
        self._detail = label("", "small")
        self.body.addWidget(self._detail)
        self._error = label("", "danger", wrap=True)
        self._error.setVisible(False)
        self.body.addWidget(self._error)
        self._note = label(tr("browser.dl.note"), "small", wrap=True)
        self.body.addWidget(self._note)

        self._stop = self.add_footer_button(tr("common.cancel"), None, self.reject)
        self._retry = self.add_footer_button(tr("browser.dl.retry"), "primary", self._start)
        self._retry.setVisible(False)

    # ------------------------------------------------------------------ flow
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._started:
            self._started = True
            QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        self._cancel = threading.Event()
        self._state = "checking"
        self._error.setVisible(False)
        self._retry.setVisible(False)
        self._stop.setText(tr("common.cancel"))
        self._stop.setEnabled(True)
        self._bar.setRange(0, 0)
        self._detail.setText("")
        self.subtitle_label.setText(tr("browser.dl.checking"))
        self._runner.submit(workers.tasks.browser_latest(self._container),
                            on_result=self._got_release, on_error=self._failed)

    def _got_release(self, release) -> None:
        if self._state == "closed":
            return
        self.release = release
        self.subtitle_label.setText(tr("browser.dl.sub", version=release.version))
        if self._container.browsers.is_downloaded(release.version):
            self.already = True
            self._finish()
            return
        self._state = "downloading"
        self._bar.setRange(0, _BAR_STEPS)
        self._bar.setValue(0)
        self._runner.submit(
            workers.tasks.browser_download(self._container, release, self._cancel),
            on_result=self._downloaded, on_error=self._failed, on_progress=self._progress,
        )

    def _progress(self, done: int, total: int) -> None:
        if self._state != "downloading" or total <= 0:
            return
        self._bar.setValue(min(_BAR_STEPS, done * _BAR_STEPS // total))
        self._detail.setText(tr("browser.dl.progress", done=done // 2 ** 20, total=total // 2 ** 20))

    def _downloaded(self, archive) -> None:
        if self._state == "closed":
            return
        self._state = "installing"
        self._stop.setEnabled(False)                 # unpacking is a few seconds and cannot be stopped half way
        self._bar.setRange(0, 0)
        self._detail.setText(tr("browser.dl.installing"))
        self._runner.submit(
            workers.tasks.browser_install(self._container, self.release, archive),
            on_result=self._installed, on_error=self._failed,
        )

    def _installed(self, installed) -> None:
        if self._state == "closed":
            return
        self.installed = installed
        self._finish()

    def _failed(self, exc: object) -> None:
        if self._state == "closed" or isinstance(exc, DownloadCancelled):
            return
        self._state = "error"
        self._bar.setRange(0, _BAR_STEPS)
        self._bar.setValue(0)
        self._detail.setText("")
        self._error.setText(friendly_error_text(exc))
        self._error.setVisible(True)
        self._stop.setText(tr("common.close"))
        self._stop.setEnabled(True)
        self._retry.setVisible(True)

    def _finish(self) -> None:
        self._state = "closed"
        self.accept()

    def reject(self) -> None:
        if self._state == "installing":
            return                                    # too late to stop: it is nearly done
        self._cancel.set()
        self._state = "closed"
        super().reject()
