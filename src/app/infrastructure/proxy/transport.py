"""Proxy transports: a tiny dependency-free request layer.

* ``HttpProxyTransport`` — HTTP(S)-protocol proxies, routed through
  ``urllib.request`` (which handles CONNECT tunneling automatically for
  HTTPS origins).
* ``Socks5Transport`` — a minimal raw SOCKS5 client plus a plain HTTP GET over
  the established socket, so SOCKS5 proxies work without any third-party
  package.

Both bubble up exceptions to the caller; the checker converts them into failed
checks so one broken proxy never breaks the batch.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

from app.domain.enums.proxy_status import ProxyProtocol
from app.domain.models.proxy import Proxy

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Capability probe targets used when deciding whether a proxy is usable for
# real browsing. HTTPS is non-negotiable for HTTP(S)-protocol proxies (CONNECT
# tunnelling) because anti-detect profiles almost always hit HTTPS-only sites;
# a proxy that only forwards plain HTTP makes Chrome spin forever on its search
# page. SOCKS5 tunnels are transparent, so the plain-HTTP target is enough
# there (TLS is done by the browser itself).
HTTPS_CAPABILITY_ENDPOINT = "https://api.ipify.org/"
HTTPS_HEALTH_ENDPOINT = "https://example.com/"
HTTP_CAPABILITY_ENDPOINT = "http://api.ipify.org/"
# Google reachability through the proxy. A proxy can be "working" for generic
# HTTPS yet unable to reach Google (SNI filtering, Google-side ASN blocks);
# launching a Google-login profile through it always ends in the
# "browser is not secure" page, so the doctor gate probes these directly.
GOOGLE_HTTPS_ENDPOINTS = ("https://accounts.google.com/", "https://www.google.com/")
# SOCKS5 transports only speak plain HTTP (TLS belongs to the browser), so the
# same reachability question is asked over plaintext (3xx counts as reached).
GOOGLE_PLAIN_ENDPOINTS = ("http://www.google.com/", "http://accounts.google.com/")


@dataclass
class HttpReply:
    status: int
    headers: Mapping[str, str]
    body: str

    def header(self, key: str) -> str | None:
        for name, value in self.headers.items():
            if name.lower() == key.lower():
                return value
        return None


class DirectTransport:
    """Regular network access, bypassing any proxy (used for the "real" IP and
    for country fallback lookups)."""

    def __init__(self, user_agent: str = USER_AGENT) -> None:
        self._user_agent = user_agent

    def get(self, url: str, timeout: float) -> HttpReply:
        request = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return _reply_from(response)
        except urllib.error.HTTPError as exc:
            return HttpReply(status=exc.code, headers=dict(exc.headers.items()), body="")
        except urllib.error.URLError as exc:
            raise ProxyTransportError(str(exc.reason)) from exc


class HttpProxyTransport:
    """Plain HTTP(S) proxy. The proxy itself is contacted over TCP; HTTPS
    origins are reached through CONNECT tunneling (handled by urllib)."""

    def __init__(
        self,
        host: str,
        port: int,
        protocol: ProxyProtocol = ProxyProtocol.HTTP,
        username: str | None = None,
        password: str | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._host = host
        self._port = port
        if protocol is ProxyProtocol.HTTPS:
            proxy_url = f"https://{host}:{port}"
        else:
            proxy_url = f"http://{host}:{port}"
        if username:
            from urllib.parse import quote

            proxy_url = (
                f"http://{quote(username)}:{quote(password or '')}@{host}:{port}"
            )
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {"http": proxy_url, "https": proxy_url}
            )
        )
        self._user_agent = user_agent

    def get(self, url: str, timeout: float) -> HttpReply:
        request = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return _reply_from(response)
        except urllib.error.HTTPError as exc:
            return HttpReply(status=exc.code, headers=dict(exc.headers.items()), body="")
        except urllib.error.URLError as exc:
            raise ProxyTransportError(str(exc.reason)) from exc


class Socks5Transport:
    """SOCKS5 proxy via a minimal in-house client.

    Only plain ``http://`` URLs are supported over the raw socket (no TLS
    library is pulled in for tunnels). This is sufficient for our check
    endpoints (``ip-api.com``, plaintext IP/echo services); Chromium itself
    ships full TLS-for-SOCKS support when the proxy is eventually used.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None = None,
        password: str | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._user_agent = user_agent

    def get(self, url: str, timeout: float) -> HttpReply:
        parsed = urlparse(url)
        if parsed.scheme not in ("http",):
            raise ProxyTransportError(
                f"SOCKS5 transport supports plain http only, got {parsed.scheme}"
            )
        target_host = parsed.hostname or ""
        target_port = parsed.port or 80
        sock = socks5_connect(
            self._host,
            self._port,
            target_host,
            target_port,
            username=self._username,
            password=self._password,
            timeout=timeout,
        )
        try:
            return _http_get_over_socket(
                sock,
                host=target_host,
                port=target_port,
                path=parsed.path or "/",
                query=parsed.query,
                timeout=timeout,
                user_agent=self._user_agent,
            )
        finally:
            sock.close()


class ProxyTransportError(Exception):
    pass


def socks5_connect(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    *,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 8.0,
) -> socket.socket:
    """Establish a TCP connection to ``target`` through an SOCKS5 proxy."""
    sock = socket.create_connection(
        (proxy_host, proxy_port), timeout=timeout
    )
    sock.settimeout(timeout)

    def send(b: bytes) -> None:
        sock.sendall(b)

    def recv_exact(n: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < n:
            chunk = sock.recv(n - len(chunks))
            if not chunk:
                raise ProxyTransportError("SOCKS5: truncated handshake")
            chunks.extend(chunk)
        return bytes(chunks)

    # Greeting: offer NO AUTH + USER/PASS auth.
    send(b"\x05\x02\x00\x02")
    version, method = recv_exact(2)
    if version != 0x05:
        raise ProxyTransportError("SOCKS5: unsupported proxy version")
    if method == 0xFF:
        raise ProxyTransportError("SOCKS5: no acceptable auth method")
    if method == 0x02:  # username/password
        user = (username or "").encode("utf-8")
        pwd = (password or "").encode("utf-8")
        if len(user) > 255 or len(pwd) > 255:
            raise ProxyTransportError("SOCKS5: credentials too long")
        send(b"\x01" + bytes([len(user)]) + user + bytes([len(pwd)]) + pwd)
        auth_version, status = recv_exact(2)
        if auth_version != 0x01 or status != 0x00:
            raise ProxyTransportError("SOCKS5: auth rejected")
    elif method not in (0x00,):
        raise ProxyTransportError(f"SOCKS5: auth method {method} not supported")

    # CONNECT request (domain name address type).
    host_bytes = target_host.encode("idna")
    if len(host_bytes) > 255:
        raise ProxyTransportError("SOCKS5: target hostname too long")
    request = (
        b"\x05\x01\x00\x03"
        + bytes([len(host_bytes)])
        + host_bytes
        + target_port.to_bytes(2, "big")
    )
    send(request)
    _version, reply, _rsv, atyp = recv_exact(4)
    if reply != 0x00:
        raise ProxyTransportError(f"SOCKS5: CONNECT failed (reply={reply})")
    if atyp == 0x01:
        recv_exact(4 + 2)
    elif atyp == 0x03:
        n = recv_exact(1)[0]
        recv_exact(n + 2)
    elif atyp == 0x04:
        recv_exact(16 + 2)
    else:
        raise ProxyTransportError(f"SOCKS5: unknown address type {atyp}")
    return sock


def _http_get_over_socket(
    sock: socket.socket,
    *,
    host: str,
    port: int,
    path: str,
    query: str,
    timeout: float,
    user_agent: str,
) -> HttpReply:
    encoded_q = f"?{query}" if query else ""
    target = f"{path}{encoded_q}"
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: {user_agent}\r\n"
        f"Accept: */*\r\n"
        f"Connection: close\r\n\r\n"
    ).encode("latin-1", errors="replace")
    sock.settimeout(timeout)
    sock.sendall(request)

    data = bytearray()
    while True:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            raise ProxyTransportError("timed out reading response")
        if not chunk:
            break
        data.extend(chunk)

    header_block, separator, body_block = _split_headers(bytes(data))
    if separator is None:
        raise ProxyTransportError("malformed HTTP response from proxy")
    head = header_block.decode("latin-1", errors="replace")
    return _assemble_reply(head, body_block)


def _split_headers(raw: bytes) -> tuple[bytes, bytes, bytes]:
    marker = b"\r\n\r\n"
    idx = raw.find(marker)
    if idx == -1:
        marker = b"\n\n"
        idx = raw.find(marker)
        if idx == -1:
            return raw, b"", b""
        return raw[:idx], b"\n\n", raw[idx + 2 :]
    return raw[:idx], marker, raw[idx + 4 :]


def _assemble_reply(head: str, body: bytes) -> HttpReply:
    lines = [line.strip() for line in head.splitlines()]
    if not lines:
        raise ProxyTransportError("empty HTTP status line")
    status_parts = lines[0].split(" ", 2)
    try:
        status = int(status_parts[1])
    except (IndexError, ValueError):
        raise ProxyTransportError(f"bad HTTP status line: {lines[0]!r}")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    if headers.get("transfer-encoding", "").lower() == "chunked":
        body = b"".join(_dechunk(body)) if b"0\r\n" in body else body
    body_text = body.decode("utf-8", errors="replace")
    return HttpReply(status=status, headers=headers, body=body_text)


def _dechunk(data: bytes) -> list[bytes]:
    """Naive chunked-encoding decoder sufficient for small JSON bodies."""
    chunks: list[bytes] = []
    offset = 0
    while offset < len(data):
        idx = data.find(b"\r\n", offset)
        if idx == -1:
            break
        size_line = data[offset:idx].split(b";")[0].strip()
        try:
            size = int(size_line, 16)
        except ValueError:
            break
        start = idx + 2
        if size == 0:
            break
        chunks.append(data[start : start + size])
        offset = start + size + 2
    return chunks


def _reply_from(response) -> HttpReply:
    headers = {k.lower(): v for k, v in response.headers.items()}
    body = response.read().decode("utf-8", errors="replace")
    return HttpReply(status=response.status, headers=headers, body=body)


def build_transport(proxy: Proxy) -> object:
    """Construct the right transport for a stored proxy."""
    if proxy.protocol is ProxyProtocol.SOCKS5:
        return Socks5Transport(
            proxy.host,
            proxy.port,
            username=proxy.username,
            password=proxy.password,
        )
    return HttpProxyTransport(
        proxy.host,
        proxy.port,
        protocol=proxy.protocol,
        username=proxy.username,
        password=proxy.password,
    )


def probe_proxy(
    proxy: Proxy,
    timeout: float = 6.0,
    user_agent: str = USER_AGENT,
) -> bool:
    """End-to-end connectivity probe: can this proxy fetch a real page?

    HTTP(S)-protocol proxies must tunnel HTTPS (CONNECT) to **two different
    hosts** and get an answer from both, so a one-off alive moment (rate limits,
    flaky upstreams) does not let a proxy pass the launch gate only to fail in
    Chrome a second later. The shared timeout budget is split across the
    requests so a dead proxy is rejected within ``timeout``. SOCKS5 proxies are
    probed over plain HTTP since their tunnel is transparent to TLS. Returns
    ``True`` only for a usable proxy.
    """
    if proxy.protocol in (ProxyProtocol.HTTP, ProxyProtocol.HTTPS):
        endpoints = (HTTPS_CAPABILITY_ENDPOINT, HTTPS_HEALTH_ENDPOINT)
    else:
        endpoints = (HTTP_CAPABILITY_ENDPOINT,)
    transport = build_transport(proxy)
    share = timeout / len(endpoints)
    for endpoint in endpoints:
        try:
            reply = transport.get(endpoint, share)
        except Exception:
            return False
        if not 200 <= reply.status < 300:
            return False
    return True


def probe_google(proxy: Proxy, timeout: float = 8.0) -> bool:
    """Can Google be reached *through* this proxy?

    Both 2xx and 3xx count as reached (Google answers logged-out requests
    with redirects). Any exception, timeout or 4xx/5xx means the proxy is
    unusable for Google login and the doctor gate must block the launch.
    """
    if proxy.protocol is ProxyProtocol.SOCKS5:
        endpoints = GOOGLE_PLAIN_ENDPOINTS
    else:
        endpoints = GOOGLE_HTTPS_ENDPOINTS
    transport = build_transport(proxy)
    share = timeout / len(endpoints)
    for endpoint in endpoints:
        try:
            reply = transport.get(endpoint, share)
        except Exception:
            return False
        if not 200 <= reply.status < 400:
            return False
    return True