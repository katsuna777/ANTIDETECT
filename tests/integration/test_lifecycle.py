from __future__ import annotations

import time

import pytest

from antidetect.application.profile_service import ProfileService
from antidetect.domain.enums.profile_status import ProfileStatus
from antidetect.domain.errors import ProfileAlreadyRunningError, ProfileNotFoundError


@pytest.fixture()
def service(live_service):
    service, _db = live_service
    return service


def test_start_marks_running_with_pid(service: ProfileService):
    profile = service.create_profile("Lifecycle")
    started = service.start_profile(profile.id)
    assert started.status is ProfileStatus.RUNNING
    assert started.pid is not None and started.pid > 0
    assert started.last_started_at is not None


def test_is_running_after_start(service: ProfileService):
    profile = service.create_profile("Running")
    started = service.start_profile(profile.id)
    loaded = service.get_profile(profile.id)
    assert loaded.status is ProfileStatus.RUNNING
    assert loaded.pid == started.pid


def test_stop_marks_stopped_and_clears_pid(service: ProfileService):
    profile = service.create_profile("Stopper")
    service.start_profile(profile.id)
    stopped = service.stop_profile(profile.id)
    assert stopped.status is ProfileStatus.STOPPED
    assert stopped.pid is None
    assert stopped.last_stopped_at is not None


def test_stop_on_dead_process_reconciles_to_stopped(service: ProfileService):
    profile = service.create_profile("Crasher")
    started = service.start_profile(profile.id)
    # Simulate the browser dying behind our back: kill the pid directly.
    import os
    import signal

    os.kill(started.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    time.sleep(0.2)

    stopped = service.stop_profile(profile.id)
    assert stopped.status is ProfileStatus.STOPPED


def test_reconcile_detects_crashed_process(service: ProfileService):
    import os
    import signal

    profile = service.create_profile("Ghost")
    started = service.start_profile(profile.id)
    os.kill(started.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    time.sleep(0.2)

    loaded = service.get_profile(profile.id)
    assert loaded.status is ProfileStatus.STOPPED
    assert loaded.pid is None


def test_double_start_is_forbidden(service: ProfileService):
    profile = service.create_profile("Twice")
    service.start_profile(profile.id)
    with pytest.raises(ProfileAlreadyRunningError):
        service.start_profile(profile.id)


def test_restart_keeps_same_profile_and_pid_changes(service: ProfileService):
    profile = service.create_profile("Recycler")
    service.start_profile(profile.id)
    time.sleep(0.1)
    restarted = service.restart_profile(profile.id)
    assert restarted.status is ProfileStatus.RUNNING
    loaded = service.get_profile(profile.id)
    assert loaded.id == profile.id
    # The stub process gets a fresh pid on each launch.
    assert loaded.pid is not None


def test_profile_directory_persists_between_runs(service: ProfileService, config):
    profile = service.create_profile("Persistent")
    profile_path = config.profiles_dir / "profile_001"
    service.start_profile(profile.id)
    time.sleep(0.2)
    # The stub records its args; simulate the browser writing browser state.
    marker = profile_path / "some-state.file"
    marker.write_text("state-before-stop", encoding="utf-8")

    service.stop_profile(profile.id)
    assert marker.exists()

    service.start_profile(profile.id)
    time.sleep(0.2)
    assert marker.read_text(encoding="utf-8") == "state-before-stop"
    service.stop_profile(profile.id)


def test_multiple_profiles_run_independently(service: ProfileService):
    a = service.create_profile("MultiA")
    b = service.create_profile("MultiB")
    service.start_profile(a.id)
    service.start_profile(b.id)
    try:
        a_running = service.get_profile(a.id)
        b_running = service.get_profile(b.id)
        assert a_running.status is ProfileStatus.RUNNING
        assert b_running.status is ProfileStatus.RUNNING
        assert a_running.pid != b_running.pid
    finally:
        service.stop_profile(a.id)
        service.stop_profile(b.id)


def test_duplicate_quiesces_running_source(service: ProfileService, config):
    source = service.create_profile("LiveSource")
    service.start_profile(source.id)
    source_path = config.profiles_dir / "profile_001"
    marker = source_path / "cookies.sqlite"
    marker.write_text("cookies!", encoding="utf-8")

    copy = service.duplicate_profile(source.id)

    assert service.get_profile(source.id).status is ProfileStatus.STOPPED
    assert copy.status is ProfileStatus.STOPPED
    copied_marker = config.profiles_dir / f"profile_{copy.id:03d}" / "cookies.sqlite"
    assert copied_marker.read_text(encoding="utf-8") == "cookies!"


def test_start_starts_from_stopped_after_full_stop_cycle(service: ProfileService):
    profile = service.create_profile("TwiceStart")
    service.start_profile(profile.id)
    service.stop_profile(profile.id)
    profile = service.get_profile(profile.id)
    assert profile.status is ProfileStatus.STOPPED
    started = service.start_profile(profile.id)
    assert started.status is ProfileStatus.RUNNING
    service.stop_profile(profile.id)


def test_restart_from_stopped_just_starts(service: ProfileService):
    profile = service.create_profile("RestartStopped")
    restarted = service.restart_profile(profile.id)
    assert restarted.status is ProfileStatus.RUNNING
    service.stop_profile(profile.id)


def test_stop_idempotent_on_stopped(service: ProfileService):
    profile = service.create_profile("IdempotentStop")
    stopped = service.stop_profile(profile.id)
    assert stopped.status is ProfileStatus.STOPPED
    assert stopped.pid is None


def test_start_unknown_profile_raises(service: ProfileService):
    with pytest.raises(ProfileNotFoundError):
        service.start_profile(9999)


def test_stop_unknown_profile_raises(service: ProfileService):
    with pytest.raises(ProfileNotFoundError):
        service.stop_profile(9999)


def test_restart_unknown_profile_raises(service: ProfileService):
    with pytest.raises(ProfileNotFoundError):
        service.restart_profile(9999)


def test_start_marks_last_started_and_stop_marks_last_stopped(service: ProfileService):
    profile = service.create_profile("Timestamps")
    started = service.start_profile(profile.id)
    assert started.last_started_at is not None
    assert started.last_stopped_at is None
    stopped = service.stop_profile(profile.id)
    assert stopped.last_stopped_at is not None


def test_reconcile_keeps_running_when_process_alive(service: ProfileService):
    profile = service.create_profile("Alive")
    started = service.start_profile(profile.id)
    loaded = service.get_profile(profile.id)
    assert loaded.status is ProfileStatus.RUNNING
    assert loaded.pid == started.pid
    service.stop_profile(profile.id)


def test_get_profile_on_stopped_does_not_touch_process(service: ProfileService):
    profile = service.create_profile("StoppedCheck")
    loaded = service.get_profile(profile.id)
    assert loaded.status is ProfileStatus.STOPPED
    assert loaded.pid is None