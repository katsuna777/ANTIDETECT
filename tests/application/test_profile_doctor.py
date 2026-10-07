from __future__ import annotations

import pytest

from antidetect.application.fingerprint.generator import ConfigurationGenerator
from antidetect.application.profile_doctor import diagnose, locale_country
from antidetect.domain.errors import ChromiumError
from antidetect.domain.models.browser_configuration import BrowserConfiguration


def _win_cfg(**overrides):
    params = ConfigurationGenerator().generate_from_template("windows-chrome")
    params.update(overrides)
    return BrowserConfiguration(id=2, name="win", **params)


def test_locale_country_parses():
    assert locale_country("en-US") == "US"
    assert locale_country("ru_RU") == "RU"
    assert locale_country("en") is None
    assert locale_country(None) is None


def test_clean_windows_us_setup_is_ok():
    report = diagnose(
        _win_cfg(),
        binary_major=152,
        proxy_country_code="US",
        anonymity="ELITE",
        google_reachable=True,
        has_proxy=True,
    )
    assert report.ok is True
    assert report.blocks == []


def test_geo_mismatch_only_warns():
    """Geo drift is repaired automatically at launch, so the doctor just explains it."""
    report = diagnose(
        _win_cfg(),  # America/New_York + en-US
        binary_major=152,
        proxy_country_code="DE",
        anonymity="ELITE",
        google_reachable=True,
        has_proxy=True,
    )
    codes = {finding.code for finding in report.warns}
    assert {"geo-timezone-mismatch", "geo-locale-mismatch"} <= codes
    assert report.ok is True


def test_transparent_proxy_warns():
    report = diagnose(
        _win_cfg(),
        binary_major=152,
        proxy_country_code="US",
        anonymity="TRANSPARENT",
        google_reachable=True,
        has_proxy=True,
    )
    assert report.ok is True
    assert "proxy-transparent" in {finding.code for finding in report.warns}


def test_google_unreachable_warns():
    report = diagnose(
        _win_cfg(),
        binary_major=152,
        proxy_country_code="US",
        anonymity="ELITE",
        google_reachable=False,
        has_proxy=True,
    )
    assert report.ok is True
    assert "google-unreachable" in {finding.code for finding in report.warns}


def test_binary_version_drift_is_not_a_problem():
    """The UA/Client Hints are rebuilt from the installed browser at launch."""
    assert diagnose(_win_cfg(), binary_major=140).ok is True
    assert diagnose(_win_cfg(), binary_major=None).ok is True
    assert diagnose(_win_cfg(), binary_major=140).blocks == []


def test_missing_configuration_blocks():
    report = diagnose(None, has_proxy=False)
    assert report.ok is False
    assert report.blocks[0].code == "no-configuration"


def test_create_configuration_rejects_legacy_ua(configuration_repo):
    from antidetect.application.fingerprint.generator import ConfigurationGenerator
    from antidetect.application.configuration_service import ConfigurationService

    svc = ConfigurationService(configurations=configuration_repo, generator=ConfigurationGenerator())
    with pytest.raises(ValueError, match="legacy"):
        svc.create_configuration("Old", user_agent="Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36")


def test_profile_doctor_cli(tmp_path, monkeypatch, capsys):

    from antidetect.cli.main import main

    monkeypatch.setenv("ANTIDETECT_DATA_DIR", str(tmp_path / "data"))
    binary = tmp_path / "chrome.sh"
    binary.write_text("#!/bin/sh\ntrap 'exit 0' TERM\nwhile :; do sleep 0.05; done\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("ANTIDETECT_CHROMIUM_PATH", str(binary))
    monkeypatch.setenv("ANTIDETECT_DISABLE_STEALTH", "1")
    assert main(["profile", "create", "Doc"]) == 0
    capsys.readouterr()
    assert main(["profile", "doctor", "1", "--no-probe"]) == 0
    captured = capsys.readouterr()
    assert "DOCTOR profile id=1: OK" in captured.out
    assert main(["profile", "update", "1", "--remove-proxy"]) == 0
    capsys.readouterr()
    # Detach the configuration -> doctor must report BLOCKED and exit 1.
    from antidetect.container import bootstrap

    container = bootstrap()
    try:
        container.profiles.remove_configuration(1)
    finally:
        container.close()
    assert main(["profile", "doctor", "1", "--no-probe"]) == 1
    captured = capsys.readouterr()
    assert "BLOCKED" in captured.out
    assert "no-configuration" in captured.out


def test_start_profile_blocked_by_geo_gate(live_service):
    svc, _db = live_service
    from antidetect.domain.enums.proxy_status import ProxyProtocol
    from antidetect.domain.models.proxy_entry import ProxyEntry

    proxies = svc._proxies
    assert proxies is not None
    proxies.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host="203.0.113.9", port=8080, source="t")]
    )
    proxy = proxies.list()[0]
    profile = svc.create_profile("GeoBlocked", proxy_id=proxy.id)
    # Default config has no timezone/locale, so attach a US config while the
    # stubbed transport layer reports no country -> only warns. Force the
    # mismatch through diagnose severity instead: emulate a DE exit.
    report = svc.diagnose_profile(profile.id, probe_google=False)
    assert report.ok is True  # unknown country warns, does not block
    with pytest.raises(ChromiumError, match="doctor"):
        # Inject a directly contradictory fact set via monkeypatched check.
        import antidetect.application.profile_service as service_module

        original = service_module.diagnose

        def always_block(*args, **kwargs):
            result = original(*args, **kwargs)
            from antidetect.application.profile_doctor import DoctorFinding

            result.blocks.append(
                DoctorFinding("block", "test-block", "forced", "fix it")
            )
            result.ok = False
            return result

        service_module.diagnose = always_block
        try:
            svc.start_profile(profile.id)
        finally:
            service_module.diagnose = original
