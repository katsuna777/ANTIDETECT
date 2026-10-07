from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from antidetect.application.fingerprint.generator import ConfigurationGenerator
from antidetect.application.configuration_service import ConfigurationService
from antidetect.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from antidetect.domain.models.proxy_entry import ProxyEntry
from antidetect.infrastructure.database.connection import Database
from antidetect.infrastructure.database.repositories.profile_repository import (
    SqliteProfileRepository,
)
from tests.conftest import build_service


@pytest.fixture()
def ctx(config, fake_chromium):
    svc, db = build_service(config, fake_chromium)
    configs = ConfigurationService(
        configurations=svc._configurations,
        generator=ConfigurationGenerator(),
    )
    yield svc, configs
    for profile in svc.list_profiles():
        if profile.status.value == "RUNNING":
            svc.stop_profile(profile.id)
    db.close()


def _add_working_proxy(svc):
    svc._proxies.upsert_many(
        [ProxyEntry(protocol=ProxyProtocol.HTTP, host="203.0.113.10", port=8080, source="integration")]
    )
    proxy = svc._proxies.list()[0]
    svc._proxies.apply_outcomes(
        [(proxy.id, ProxyStatus.WORKING, 0, datetime.now(timezone.utc))]
    )
    return svc._proxies.get(proxy.id)


def test_full_acceptance_scenario(ctx, config):
    svc, configs = ctx

    configuration = configs.generate_configuration(template="windows-chrome")
    proxy = _add_working_proxy(svc)
    profile = svc.create_profile(
        "Integration One", configuration_id=configuration.id, proxy_id=proxy.id
    )
    assert profile.configuration_id == configuration.id
    assert profile.proxy_id == proxy.id

    loaded_back = svc.get_profile_details(profile.id)
    assert loaded_back.configuration.id == configuration.id
    assert loaded_back.proxy_check is not None
    assert loaded_back.proxy_check.proxy.status is ProxyStatus.WORKING

    # start + persistent state marker + stop + restart keeps the state.
    profile_dir = Path(profile.profile_path)
    profile_dir.mkdir(parents=True, exist_ok=True)
    marker = profile_dir / "state.txt"
    marker.write_text("state-before-restart", encoding="utf-8")

    started = svc.start_profile(profile.id)
    assert started.pid and started.pid > 0
    assert svc.get_profile(profile.id).status.value == "RUNNING"
    svc.stop_profile(profile.id)

    marker.write_text("state-after-stop", encoding="utf-8")  # persists across restart
    restarted = svc.start_profile(profile.id)
    assert restarted.pid and restarted.pid > 0
    assert svc.get_profile(profile.id).status.value == "RUNNING"
    assert marker.read_text(encoding="utf-8") == "state-after-stop"
    svc.stop_profile(profile.id)

    # The database row survives a fresh connection to the same file.
    fresh_db = Database(config.database_path)
    try:
        reloaded = SqliteProfileRepository(fresh_db).list()
        assert len(reloaded) == 1
        assert reloaded[0].name == "Integration One"
        assert reloaded[0].configuration_id == configuration.id
        assert reloaded[0].proxy_id == proxy.id
    finally:
        fresh_db.close()


def test_profiles_are_storage_isolated(ctx):
    svc, _ = ctx
    first = svc.create_profile("Isolation A")
    second = svc.create_profile("Isolation B")
    assert first.profile_path != second.profile_path

    first_dir = Path(first.profile_path)
    second_dir = Path(second.profile_path)
    first_dir.mkdir(parents=True, exist_ok=True)
    (first_dir / "secret.txt").write_text("A-only", encoding="utf-8")

    svc.start_profile(first.id)
    svc.start_profile(second.id)
    try:
        assert (first_dir / "secret.txt").is_file()
        assert not (second_dir / "secret.txt").exists()
    finally:
        svc.stop_profile(first.id)
        svc.stop_profile(second.id)


def test_duplicate_produces_independent_storage(ctx):
    svc, _ = ctx
    original = svc.create_profile("DupeSource")
    original_dir = Path(original.profile_path)
    original_dir.mkdir(parents=True, exist_ok=True)
    (original_dir / "cookies.sqlite").write_text("cookie-snapshot", encoding="utf-8")

    copy = svc.duplicate_profile(original.id)
    assert copy.id != original.id
    copy_dir = Path(copy.profile_path)
    assert copy_dir.is_dir()
    assert (copy_dir / "cookies.sqlite").read_text(encoding="utf-8") == "cookie-snapshot"

    # Mutating the copy must not affect the original.
    (copy_dir / "cookies.sqlite").write_text("mutated", encoding="utf-8")
    assert (original_dir / "cookies.sqlite").read_text(encoding="utf-8") == "cookie-snapshot"


def test_configuration_survives_restart_and_is_applied(ctx, tmp_path):
    svc, configs = ctx
    configuration = configs.generate_configuration(template="linux-chrome")
    profile = svc.create_profile("Fingerprinted", configuration_id=configuration.id)

    svc.start_profile(profile.id)
    args_text = tmp_path.joinpath("fake_chromium.args").read_text(encoding="utf-8")
    assert configuration.user_agent in args_text
    assert f"--lang={configuration.language_tag}" in args_text
    assert "--accept-lang=" in args_text
    svc.stop_profile(profile.id)

    svc.start_profile(profile.id)
    args_after_restart = tmp_path.joinpath("fake_chromium.args").read_text(encoding="utf-8")
    # The fingerprint survives a restart: same UA / language flags both times
    # (time zone and screen are applied over CDP, not through flags).
    assert configuration.user_agent in args_after_restart
    assert f"--lang={configuration.language_tag}" in args_after_restart
    svc.stop_profile(profile.id)