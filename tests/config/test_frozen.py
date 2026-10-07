"""Frozen helpers: resource paths, bundled CA bundle, SSL wiring."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def test_ensure_ssl_certs_sets_env_to_real_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    from antidetect import runtime as _frozen

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
    from antidetect import runtime as _frozen

    assert _frozen.bundled_cafile() == str(pem)


def test_ensure_ssl_certs_noop_without_bundle(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    from antidetect import runtime as _frozen

    monkeypatch.setattr(_frozen, "bundled_cafile", lambda: None)
    _frozen.ensure_ssl_certs()
    assert "SSL_CERT_FILE" not in os.environ


def test_stealth_payload_is_packaged_where_the_build_specs_put_it():
    """The PyInstaller specs copy payload.js to antidetect/infrastructure/stealth/js/."""
    from antidetect.runtime import resource_path

    path = resource_path("antidetect", "infrastructure", "stealth", "js", "payload.js")
    assert path.is_file() and "(function (CFG)" in path.read_text(encoding="utf-8")
    spec = Path(__file__).resolve().parents[2] / "packaging" / "_spec_common.py"
    text = spec.read_text(encoding="utf-8")
    assert "stealth" in text and "payload.js" in text
