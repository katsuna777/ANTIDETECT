"""Tests for LocalProxyShim: HTTP CONNECT tunneling and SOCKS5 with auth.

Each test spins a real fake *upstream* proxy server on 127.0.0.1, authenticates
the shim against it, and then drives a real client connection through the shim
exactly like Chromium would. This proves the shim forwards data end-to-end and
injects the stored credentials on its upstream side.
"""

from __future__ import annotations

import base64
import socket
import threading


from antidetect.domain.enums.proxy_status import ProxyProtocol
from antidetect.domain.models.proxy import Proxy
from antidetect.infrastructure.chromium.proxy_shim import LocalProxyShim


# --------------------------------------------------------------------------- #
# Fake upstream servers
# --------------------------------------------------------------------------- #


class FakeUpstreamHttp:
    """A tiny HTTP proxy: asserts CONNECT auth then relays raw bytes."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = int(self._sock.getsockname()[1])
        self.received_headers: bytes = b""
        self.accepted_auth: bool | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        conn, _ = self._sock.accept()
        with conn:
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            head, _ = buf.split(b"\r\n\r\n", 1)
            self.received_headers = head
            lowered = head.lower()
            self.accepted_auth = (
                b"proxy-authorization: basic " in lowered
            )
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            # echo back whatever the tunnel carries
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                conn.sendall(chunk)

    def close(self) -> None:
        self._sock.close()


class FakeUpstreamSocks5:
    """A minimal SOCKS5 proxy that requires username/password auth."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port = int(self._sock.getsockname()[1])
        self.auth_ok: bool | None = None
        self.target: tuple[str, int] | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _exact(self, conn: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise OSError("closed")
            buf += chunk
        return buf

    def _run(self) -> None:
        conn, _ = self._sock.accept()
        with conn:
            _ver, nmethods = self._exact(conn, 2)
            self._exact(conn, nmethods)
            conn.sendall(b"\x05\x02")  # pick username/password
            status = self._exact(conn, 2)
            user = self._username.encode()
            pwd = self._password.encode()
            expected = b"\x01" + bytes([len(user)]) + user + bytes([len(pwd)]) + pwd
            self.auth_ok = status + self._exact(conn, len(expected) - 2) == expected
            conn.sendall(b"\x01\x00" if self.auth_ok else b"\x01\x01")

            _ver, _cmd, _rsv, atyp = self._exact(conn, 4)
            if atyp == 0x03:
                length = self._exact(conn, 1)[0]
                host = self._exact(conn, length).decode()
            else:
                host = socket.inet_ntoa(self._exact(conn, 4))
            port = int.from_bytes(self._exact(conn, 2), "big")
            self.target = (host, port)
            conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                conn.sendall(chunk)

    def close(self) -> None:
        self._sock.close()


# --------------------------------------------------------------------------- #
# HTTP CONNECT mode
# --------------------------------------------------------------------------- #


def test_http_connect_tunnel_injects_auth_and_relays():
    upstream = FakeUpstreamHttp()
    proxy = Proxy(
        id=1,
        protocol=ProxyProtocol.HTTP,
        host="127.0.0.1",
        port=upstream.port,
        username="alice",
        password="s3cret",
    )
    shim = LocalProxyShim(proxy).start()
    try:
        assert shim.proxy_server_url.startswith("http://127.0.0.1:")
        client = socket.create_connection(("127.0.0.1", int(shim.proxy_server_url.rsplit(":", 1)[1])), timeout=3)
        try:
            client.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
            response = _read_until(client, b"\r\n\r\n")
            assert response.startswith(b"HTTP/1.1 200")
            client.sendall(b"hello-through-the-tunnel")
            echoed = client.recv(64)
            assert echoed == b"hello-through-the-tunnel"
        finally:
            client.close()
    finally:
        shim.close()
        upstream.close()

    expected_token = base64.b64encode(b"alice:s3cret").decode()
    assert upstream.accepted_auth is True
    assert expected_token in upstream.received_headers.decode()


# --------------------------------------------------------------------------- #
# SOCKS5 mode
# --------------------------------------------------------------------------- #


def test_socks5_tunnel_injects_userpass_auth():
    upstream = FakeUpstreamSocks5(username="bob", password="hunter2")
    proxy = Proxy(
        id=2,
        protocol=ProxyProtocol.SOCKS5,
        host="127.0.0.1",
        port=upstream.port,
        username="bob",
        password="hunter2",
    )
    shim = LocalProxyShim(proxy).start()
    try:
        assert shim.proxy_server_url.startswith("socks5://127.0.0.1:")
        client = socket.create_connection(("127.0.0.1", int(shim.proxy_server_url.rsplit(":", 1)[1])), timeout=3)
        try:
            client.sendall(b"\x05\x01\x00")  # greeting, offer no-auth
            assert client.recv(2) == b"\x05\x00"
            target = b"api.example.com"
            request = (
                b"\x05\x01\x00\x03" + bytes([len(target)]) + target + (443).to_bytes(2, "big")
            )
            client.sendall(request)
            assert client.recv(10) == b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"
            client.sendall(b"ping")
            assert client.recv(4) == b"ping"
        finally:
            client.close()
    finally:
        shim.close()
        upstream.close()

    assert upstream.auth_ok is True
    assert upstream.target == ("api.example.com", 443)


# --------------------------------------------------------------------------- #
# Chrome-flag surface
# --------------------------------------------------------------------------- #


def test_shim_url_matches_protocol_scheme():
    http_proxy = Proxy(id=1, protocol=ProxyProtocol.HTTP, host="h", port=80, username="u")
    socks_proxy = Proxy(id=2, protocol=ProxyProtocol.SOCKS5, host="h", port=1080, username="u")
    assert LocalProxyShim(http_proxy).proxy_server_url.startswith("http://")
    assert LocalProxyShim(socks_proxy).proxy_server_url.startswith("socks5://")


def _read_until(conn: socket.socket, marker: bytes) -> bytes:
    buf = b""
    while marker not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf