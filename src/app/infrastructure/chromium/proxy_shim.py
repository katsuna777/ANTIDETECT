"""Local proxy shim that injects upstream proxy credentials.

Chromium deliberately ignores the ``user:pass@`` part of a ``--proxy-server``
URI, so a proxy that requires Basic authentication leaves Chrome stuck in an
endless 407 retry (the page spins forever). This module runs a tiny forward
proxy on ``127.0.0.1`` that Chrome talks to without credentials; the shim then
talks to the *real* upstream proxy injecting the stored username/password.

Two modes are implemented:

* HTTP(S) upstream — the shim speaks plain HTTP to Chrome (CONNECT tunneling
  plus absolute-URI requests) and forwards to the upstream proxy with a
  ``Proxy-Authorization: Basic`` header.
* SOCKS5 upstream — the shim is a minimal SOCKS5 server for Chrome (no-auth
  greeting) and performs the user/pass SOCKS5 handshake to the upstream proxy.

The shim is single-bind, per-profile: one listening socket, connections
handled on separate daemon threads, and no credentials are ever logged.
"""

from __future__ import annotations

import base64
import socket
import ssl
import threading

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.models.proxy import Proxy
from app.infrastructure.proxy.transport import socks5_connect

_MAX_HEAD = 65536
_RECV_CHUNK = 4096


class LocalProxyShim:
    """A per-profile forwarding proxy that authenticates to an upstream proxy.

    Call :meth:`start` (binds and begins accepting), use :attr:`proxy_server_url`
    to build the Chromium ``--proxy-server`` flag, and :meth:`close` when the
    profile stops. Exceptions raised during ``start`` mean the shim is not
    usable and ``connect``/``close`` are safe no-ops afterwards.
    """

    def __init__(self, proxy: Proxy, bind_host: str = "127.0.0.1") -> None:
        self._proxy = proxy
        self._bind_host = bind_host
        self._server: socket.socket | None = None
        self._port: int | None = None
        self._threads: list[threading.Thread] = []
        self._closed = False

    # ------------------------------------------------------------- lifecycle

    def start(self) -> "LocalProxyShim":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self._bind_host, 0))
        server.listen(socket.SOMAXCONN)
        server.settimeout(0.5)
        self._server = server
        self._port = int(server.getsockname()[1])
        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()
        self._threads.append(thread)
        return self

    def close(self) -> None:
        self._closed = True
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads.clear()

    @property
    def proxy_server_url(self) -> str:
        """The credential-free ``--proxy-server`` value for Chromium."""
        if self._proxy.protocol is ProxyProtocol.SOCKS5:
            scheme = "socks5"
        else:
            scheme = "http"
        return f"{scheme}://{self._bind_host}:{self._port}"

    # -------------------------------------------------------------- accept

    def _accept_loop(self) -> None:
        while not self._closed:
            try:
                client, _ = self._server.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                return
            client.settimeout(30.0)
            thread = threading.Thread(
                target=self._handle, args=(client,), daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def _handle(self, client: socket.socket) -> None:
        try:
            if self._proxy.protocol is ProxyProtocol.SOCKS5:
                self._serve_socks5(client)
            else:
                self._serve_http(client)
        except (OSError, ValueError):
            pass
        finally:
            _close_socket(client)

    # ------------------------------------------------------------ HTTP mode

    def _serve_http(self, client: socket.socket) -> None:
        head, leftover = _recv_head(client)
        line = head.split(b"\r\n", 1)[0]
        parts = line.split(b" ")
        if len(parts) < 3:
            raise ValueError("malformed request line")
        method, target = parts[0], parts[1]
        if method.upper() == b"CONNECT":
            self._handle_connect(client, target, leftover)
        else:
            self._handle_plain(client, head, leftover)

    def _handle_connect(
        self, client: socket.socket, target: bytes, leftover: bytes
    ) -> None:
        host, _, port = target.decode("latin1").partition(":")
        port = int(port) if port else 443
        upstream = self._open_upstream(host, port)
        try:
            request = (
                f"CONNECT {host}:{port} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
            ).encode() + self._auth_header() + b"\r\n"
            upstream.sendall(request)
            up_head, _ = _recv_head(upstream)
            status = int(up_head.split(b"\r\n", 1)[0].split(b" ")[1])
            if status >= 400:
                client.sendall(up_head + b"\r\n\r\n")
                return
        except (OSError, ValueError, IndexError):
            return
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        if leftover:
            try:
                upstream.sendall(leftover)
            except OSError:
                return
        _splice(client, upstream)

    def _handle_plain(self, client: socket.socket, head: bytes, leftover: bytes) -> None:
        upstream = self._open_upstream("", 0)  # upstream host/port from proxy
        try:
            forwarded = _inject_auth(head, self._auth_header())
            upstream.sendall(forwarded)
            if leftover:
                upstream.sendall(leftover)
        except OSError:
            return
        _splice(client, upstream)

    def _open_upstream(self, _host: str, _port: int) -> socket.socket:
        proxy = self._proxy
        sock = socket.create_connection((proxy.host, proxy.port), timeout=15.0)
        if proxy.protocol is ProxyProtocol.HTTPS:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock, server_hostname=proxy.host)
        return sock

    def _auth_header(self) -> bytes:
        user = self._proxy.username or ""
        pwd = self._proxy.password or ""
        token = base64.b64encode(f"{user}:{pwd}".encode("utf-8"))
        return b"Proxy-Authorization: Basic " + token + b"\r\n"

    # ----------------------------------------------------------- SOCKS5 mode

    def _serve_socks5(self, client: socket.socket) -> None:
        greeting = _recv_exact(client, 2)
        if greeting[0] != 0x05:
            raise ValueError("not SOCKS5")
        nmethods = greeting[1]
        _recv_exact(client, nmethods)
        client.sendall(b"\x05\x00")  # no-auth greeting to Chrome

        request = _recv_exact(client, 4)
        if request[1] != 0x01:  # only CONNECT is supported
            client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        atyp = request[3]
        if atyp == 0x01:
            host = socket.inet_ntoa(_recv_exact(client, 4))
        elif atyp == 0x03:
            length = _recv_exact(client, 1)[0]
            host = _recv_exact(client, length).decode("idna")
        elif atyp == 0x04:
            host = socket.inet_ntop(socket.AF_INET6, _recv_exact(client, 16))
        else:
            raise ValueError(f"unknown address type {atyp}")
        port = int.from_bytes(_recv_exact(client, 2), "big")

        upstream = socks5_connect(
            self._proxy.host,
            self._proxy.port,
            host,
            port,
            username=self._proxy.username,
            password=self._proxy.password,
            timeout=15.0,
        )
        client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        _splice(client, upstream)


# --------------------------------------------------------------------------- #
# Socket helpers
# --------------------------------------------------------------------------- #


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < n:
        chunk = conn.recv(n - len(chunks))
        if not chunk:
            raise OSError("peer closed during read")
        chunks.extend(chunk)
    return bytes(chunks)


def _recv_head(conn: socket.socket, max_size: int = _MAX_HEAD) -> tuple[bytes, bytes]:
    """Read up to the ``\\r\\n\\r\\n`` terminator; return (head, leftover)."""
    marker = b"\r\n\r\n"
    buf = b""
    while marker not in buf:
        chunk = conn.recv(_RECV_CHUNK)
        if not chunk:
            raise OSError("peer closed before head complete")
        buf += chunk
        if len(buf) > max_size:
            raise ValueError("head too large")
    head, leftover = buf.split(marker, 1)
    return head, leftover


def _inject_auth(head: bytes, auth_header: bytes) -> bytes:
    """Add or replace the Proxy-Authorization header in a request head.

    Strips any existing ``Proxy-Authorization`` line (the browser never sends
    one to the local shim, but be defensive) and appends our own header before
    the closing blank line. The request line and every other header survive.
    """
    lines = head.split(b"\r\n")
    kept = [line for line in lines if not line.lower().startswith(b"proxy-authorization:")]
    kept.append(auth_header.rstrip(b"\r\n"))
    return b"\r\n".join(kept) + b"\r\n\r\n"


def _splice(a: socket.socket, b: socket.socket) -> None:
    """Relay bytes between two sockets until one direction ends."""
    stop = threading.Event()

    def pipe(src, dst):
        try:
            while not stop.is_set():
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            stop.set()
            _shutdown_writes(dst)

    t1 = threading.Thread(target=pipe, args=(a, b), daemon=True)
    t2 = threading.Thread(target=pipe, args=(b, a), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=30.0)
    t2.join(timeout=30.0)
    _close_socket(a)
    _close_socket(b)


def _shutdown_writes(conn: socket.socket) -> None:
    try:
        conn.shutdown(socket.SHUT_WR)
    except OSError:
        pass


def _close_socket(conn: socket.socket) -> None:
    try:
        conn.close()
    except OSError:
        pass