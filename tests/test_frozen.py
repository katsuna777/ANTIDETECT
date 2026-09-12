"""Frozen helpers: resource paths, bundled CA bundle, SSL wiring."""

from __future__ import annotations

import os
import sys


def test_ensure_ssl_certs_sets_env_to_real_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    from app import _frozen

    _frozen.ensure_ssl_certs()
    cafile = os.environ.get("SSL_CERT_FILE")
    assert cafile, "SSL_CERT_FILE must point at a CA bundle"
    # In dev it resolves to the installed certifi package; must exist.
    assert os.path.isfile(cafile)


def test_bundled_cafile_prefers_meipass(tmp_path, monkeypatch):
    fake_meipass = tmp_path / "_MEIPASS"
    pem = fake_meipass / "certifi" / "cacert.pem"
    pem.parent.mkdir(parents=True)
    pem.write_text("fake-ca")
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    from app import _frozen

    assert _frozen.bundled_cafile() == str(pem)


def test_ensure_ssl_certs_noop_without_bundle(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    from app import _frozen

    monkeypatch.setattr(_frozen, "bundled_cafile", lambda: None)
    _frozen.ensure_ssl_certs()
    assert "SSL_CERT_FILE" not in os.environ
