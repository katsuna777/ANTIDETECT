"""Owns the API server's life: starts it, stops it, moves it to another port.

The GUI and the headless ``antidetect api serve`` both use this, so they behave the same.
"""

from __future__ import annotations

import errno
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from antidetect.api.server import ApiServer
from antidetect.api.service import ApiService
from antidetect.api.settings import ApiKey, ApiSettings

if TYPE_CHECKING:
    from antidetect.container import Container


class ApiStartError(Exception):
    """The server could not start; the message says why in words a user can act on."""

    def __init__(self, message: str, *, port: int, busy: bool = False) -> None:
        super().__init__(message)
        self.port = port
        self.busy = busy          # the port is taken by another program (the GUI words this itself)


@dataclass
class KeyUsage:
    """What one key has done since the app started (kept in memory only)."""

    requests: int = 0
    last_used: float | None = None      # epoch seconds


class ApiManager:
    def __init__(self, container: "Container", on_change: Callable[[], None] | None = None) -> None:
        self._container = container
        self.settings = ApiSettings(container.settings)
        self.service = ApiService(container, on_change=on_change)
        self._server: ApiServer | None = None
        self._usage: dict[str, KeyUsage] = {}
        self._usage_lock = threading.Lock()
        #: why the API is not running although it is switched on (shown in the settings), else ``None``
        self.error: ApiStartError | None = None

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.running

    @property
    def port(self) -> int:
        return self._server.port if self._server is not None and self._server.running else self.settings.port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # ------------------------------------------------------------------ usage
    def _record_use(self, key: ApiKey) -> None:
        with self._usage_lock:
            usage = self._usage.setdefault(key.id, KeyUsage())
            usage.requests += 1
            usage.last_used = time.time()

    def usage(self, key_id: str) -> KeyUsage:
        with self._usage_lock:
            found = self._usage.get(key_id)
            return KeyUsage(found.requests, found.last_used) if found is not None else KeyUsage()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Listen on the configured port. Raises :class:`ApiStartError` when that is not possible."""
        if self.running:
            return
        port = self.settings.port
        server = ApiServer(self.service, self.settings.find, port, log=self._container.logs, on_use=self._record_use)
        try:
            server.start()
        except OSError as exc:
            busy = exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE), 10048, 10013)
            message = (f"Port {port} is already in use. Choose another one." if busy
                       else f"Couldn't start the API on port {port}: {exc.strerror or exc}")
            self.error = ApiStartError(message, port=port, busy=busy)
            raise self.error from exc
        self.error = None
        self._server = server
        self._container.logs.info("api", f"API listening on http://127.0.0.1:{server.port}")

    def stop(self) -> None:
        self.error = None
        server, self._server = self._server, None
        if server is not None:
            server.stop()
            self._container.logs.info("api", "API stopped")

    def restart(self) -> None:
        self.stop()
        self.start()

    # ------------------------------------------------------------------ settings
    def apply(self) -> str | None:
        """Bring the server in line with the saved settings; the error text when it cannot start."""
        if not self.settings.enabled:
            self.stop()
            return None
        try:
            self.start()
        except ApiStartError as exc:
            return str(exc)
        return None

    def set_enabled(self, enabled: bool) -> None:
        """Switch the API on or off. Stays off (and says why) when the port is not available."""
        if not enabled:
            self.settings.set_enabled(False)
            self.stop()
            return
        self.settings.set_enabled(True)
        try:
            self.start()
        except ApiStartError:
            self.settings.set_enabled(False)
            self.error = None            # the user was told right away; nothing is "pending"
            raise

    def set_port(self, port) -> int:
        """Use another port (live when the API is on). Keeps the old one when the new one is busy."""
        previous = self.settings.port
        value = self.settings.set_port(port)       # ValueError for an unusable number
        if value != previous and self.running:
            try:
                self.restart()
            except ApiStartError:
                self.settings.set_port(previous)
                self.start()
                raise
        return value

    def regenerate_token(self) -> str:
        """A new secret for the first key; the old one stops working at once (checked per request)."""
        key = self.settings.keys()[0]
        return self.regenerate_key(key.id).token

    def regenerate_key(self, key_id: str) -> ApiKey:
        key = self.settings.regenerate_key(key_id)
        self._container.logs.info("api", f"API key “{key.name}” regenerated")
        return key

    def add_key(self, name: str) -> ApiKey:
        key = self.settings.add_key(name)
        self._container.logs.info("api", f"API key “{key.name}” created")
        return key

    def rename_key(self, key_id: str, name: str) -> ApiKey:
        return self.settings.rename_key(key_id, name)

    def delete_key(self, key_id: str) -> None:
        key = self.settings.get_key(key_id)
        self.settings.delete_key(key_id)
        with self._usage_lock:
            self._usage.pop(key_id, None)
        self._container.logs.info("api", f"API key “{key.name}” deleted")
