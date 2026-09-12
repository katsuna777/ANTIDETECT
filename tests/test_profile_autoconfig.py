from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.application.configuration_generator import ConfigurationGenerator, country_defaults
from app.application.profile_doctor import diagnose
from app.domain.enums.proxy_status import Anonymity, ProxyProtocol, ProxyStatus
from app.domain.models.proxy_check import ProxyCheck
from app.domain.models.proxy_entry import ProxyEntry
from app.infrastructure.database.repositories.proxy_check_repository import (
    SqliteProxyCheckRepository,
)
from app.infrastructure.database.repositories.proxy_repository import (
    SqliteProxyRepository,
)


@pytest.fixture()
def ctx(config, fake_chromium):
    from tests.conftest import build_service

    svc, db = build_service(config, fake_chromium)
    yield svc, db
    for profile in svc.list_profiles():
        if profile.status.value == "RUNNING":
            svc.stop_profile(profile.id)
    db.close()


def _add_proxy(svc, db, host="9.9.9.9", country_code=None, anonymity=Anonymity.ELITE):
    repo = svc._proxies or SqliteProxyRepository(db)
    repo.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host=host, port=8080, source="test")]
    )
    proxy = repo.list()[0]
    if country_code is not None:
        SqliteProxyCheckRepository(db).insert_many(
            [
                ProxyCheck(
                    id=0,
                    proxy_id=proxy.id,
                    checked_at=datetime.now(timezone.utc),
                    status=ProxyStatus.WORKING,
                    latency_ms=50,
                    external_ip="198.51.100.9",
                    country=country_code,
                    country_code=country_code,
                    anonymity=anonymity,
                )
            ]
        )
    return repo.get(proxy.id)


def test_generate_for_country_pins_geo():
    params = ConfigurationGenerator().generate_for_country("DE", platform="windows")
    assert params["locale"] == "de-DE"
    assert params["timezone"] == "Europe/Berlin"
    assert params["language"] == "de"
    assert params["platform"] == "windows"
    assert "Direct3D11" in params["webgl_settings"]["renderer"]


def test_generate_for_country_unknown_raises():
    with pytest.raises(ValueError, match="Unknown country"):
        ConfigurationGenerator().generate_for_country("XX")


def test_country_defaults_cover_doctor_timezones():
    from app.application.profile_doctor import TIMEZONE_COUNTRY

    for code, (language, locale, tz) in {
        k: v for k, v in __import__(
            "app.application.configuration_generator", fromlist=["x"]
        ).COUNTRY_DEFAULTS.items()
    }.items():
        assert TIMEZONE_COUNTRY[tz] == code, tz
        assert locale.rsplit("-", 1)[-1].upper() == code, locale


def test_assign_proxy_generates_matching_config(ctx):
    svc, _db = ctx
    proxy = _add_proxy(svc, _db, country_code="DE")
    profile = svc.create_profile("Auto", proxy_id=proxy.id, auto_config=False)
    assert svc.get_profile_details(profile.id).configuration.locale != "de-DE"

    svc.assign_proxy(profile.id, proxy.id)  # auto_config defaults to True
    details = svc.get_profile_details(profile.id)
    assert details.configuration is not None
    assert details.configuration.locale == "de-DE"
    assert details.configuration.timezone == "Europe/Berlin"
    assert details.configuration.name.startswith("auto-de-")


def test_assign_proxy_reuses_matching_config(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db, country_code="DE")
    first = svc.create_profile("First", proxy_id=proxy.id)
    second = svc.create_profile("Second", proxy_id=proxy.id, auto_config=False)
    svc.assign_proxy(second.id, proxy.id)
    names = [c.name for c in svc._configurations.list()]
    assert names.count("auto-de-windows") == 1
    first_cfg = svc.get_profile_details(first.id).configuration
    second_cfg = svc.get_profile_details(second.id).configuration
    assert first_cfg.id == second_cfg.id


def test_assign_proxy_keeps_already_matching(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db, country_code="US")
    profile = svc.create_profile("Keep", proxy_id=proxy.id, auto_config=False)
    before = svc.get_profile_details(profile.id).configuration.id
    svc.assign_proxy(profile.id, proxy.id)
    # default config has no geo; unknown-match path generates auto-us-windows
    after = svc.get_profile_details(profile.id).configuration
    assert after.locale == "en-US"
    assert after.timezone == "America/New_York"
    assert before != after.id


def test_assign_proxy_unknown_country_keeps_config(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db, country_code=None)  # never checked
    profile = svc.create_profile("Mystery", proxy_id=proxy.id, auto_config=False)
    before = svc.get_profile_details(profile.id).configuration.id
    svc.assign_proxy(profile.id, proxy.id)
    assert svc.get_profile_details(profile.id).configuration.id == before


def test_no_auto_config_opt_out(ctx):
    svc, db = ctx
    proxy = _add_proxy(svc, db, country_code="FR")
    profile = svc.create_profile("Manual", proxy_id=proxy.id, auto_config=False)
    before = svc.get_profile_details(profile.id).configuration.id
    svc.assign_proxy(profile.id, proxy.id, auto_config=False)
    assert svc.get_profile_details(profile.id).configuration.id == before


def test_auto_config_result_passes_doctor():
    from app.application.configuration_generator import ua_chrome_major
    from app.domain.models.browser_configuration import BrowserConfiguration

    params = ConfigurationGenerator().generate_for_country("JP", platform="windows")
    cfg = BrowserConfiguration(id=7, name="auto", **params)
    major = ua_chrome_major(cfg.user_agent or "") or 152
    report = diagnose(
        cfg,
        binary_major=major,
        proxy_country_code="JP",
        anonymity="ELITE",
        google_reachable=True,
        has_proxy=True,
    )
    assert report.ok is True, report.blocks


def test_cli_proxy_set_prints_fingerprint(tmp_path, monkeypatch, capsys):
    from app.cli.cli import main

    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    binary = tmp_path / "chrome.sh"
    binary.write_text("#!/bin/sh\ntrap 'exit 0' TERM\nwhile :; do sleep 0.05; done\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(binary))
    monkeypatch.setenv("ANTIDETECT_DISABLE_STEALTH", "1")
    assert main(["profile", "create", "CliAuto"]) == 0
    capsys.readouterr()
    # Insert a checked DE proxy straight into the CLI database.
    import sqlite3

    conn = sqlite3.connect(tmp_path / "data" / "antidetect.db")
    try:
        cur = conn.execute(
            "INSERT INTO proxies (protocol, host, port, status, created_at, updated_at) "
            "VALUES ('HTTP', '203.0.113.5', 8080, 'WORKING', "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        )
        proxy_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO proxy_checks (proxy_id, checked_at, status, latency_ms, external_ip, country, country_code, anonymity) "
            "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'WORKING', 40, '198.51.100.5', 'Germany', 'DE', 'ELITE')",
            (proxy_id,),
        )
        conn.commit()
    finally:
        conn.close()
    assert main(["profile", "proxy", "1", "--set", str(proxy_id)]) == 0
    captured = capsys.readouterr()
    assert "Fingerprint:" in captured.out
    assert "de-DE" in captured.out
    assert main(["profile", "show", "1"]) == 0
    captured = capsys.readouterr()
    assert "de-DE" in captured.out
    assert "Europe/Berlin" in captured.out
