"""Task factories map cleanly onto the application services.

These factories are plain callables (no Qt), so they are tested synchronously:
invoke ``factory(container)(progress)`` and assert against the domain result.
"""

from __future__ import annotations

import pytest

from app.domain.errors import ProfileNotFoundError, ProxyNotFoundError
from app.gui.models import EntitySummary
from app.gui.workers import tasks
from app.gui.workers.worker import TaskFunction


def _run(task: TaskFunction):
    """Execute a task factory's callable synchronously."""
    return task(lambda done, total: None)


def test_summary_task_reports_empty_counts(gui_container):
    summary = _run(tasks.summary(gui_container))
    assert isinstance(summary, EntitySummary)
    assert summary.profiles == 0
    assert summary.running_profiles == 0
    assert summary.proxies == 0
    assert summary.working_proxies == 0
    # Migration 0001 seeds one 'default' configuration.
    assert summary.configurations == 1


def test_summary_reflects_created_entities(gui_container):
    gui_container.configurations.generate_configuration(
        name="cfg-a", platform="macos"
    )
    gui_container.profiles.create_profile("alpha")

    summary = _run(tasks.summary(gui_container))
    assert summary.profiles == 1
    assert summary.configurations == 2


def test_profile_lifecycle_tasks_raise_domain_errors(gui_container):
    with pytest.raises(ProfileNotFoundError):
        _run(tasks.start_profile(gui_container, 4242))
    with pytest.raises(ProfileNotFoundError):
        _run(tasks.stop_profile(gui_container, 4242))
    with pytest.raises(ProfileNotFoundError):
        _run(tasks.restart_profile(gui_container, 4242))


def test_check_proxy_task_raises_domain_errors(gui_container):
    with pytest.raises(ProxyNotFoundError):
        _run(tasks.check_proxy(gui_container, 4242))


def test_create_profile_task(gui_container):
    profile = _run(tasks.create_profile(gui_container, "newbie"))
    assert profile.id > 0
    assert profile.name == "newbie"
    assert gui_container.profiles.get_profile(profile.id).id == profile.id


def test_update_profile_task_changes_configuration(gui_container):
    profile = gui_container.profiles.create_profile("edit-me")
    cfg = gui_container.configurations.generate_configuration(
        platform="linux"
    )
    updated = _run(
        tasks.update_profile(
            gui_container, profile.id, configuration_id=cfg.id
        )
    )
    assert updated.configuration_id == cfg.id


def test_assign_configuration_and_proxy_tasks(gui_container):
    profile = gui_container.profiles.create_profile("assign-me")
    cfg = gui_container.configurations.generate_configuration(platform="macos")
    proxy = _run(
        tasks.assign_configuration(gui_container, profile.id, cfg.id)
    )
    assert proxy.configuration_id == cfg.id

    proxied = _run(tasks.assign_proxy(gui_container, profile.id, None))
    assert proxied.proxy_id is None


def test_delete_profile_task_removes_row(gui_container):
    profile = gui_container.profiles.create_profile("soon-gone")
    _run(tasks.delete_profile(gui_container, profile.id))
    assert gui_container.profiles.list_profiles() == []


def test_generate_configuration_with_size_task(gui_container):
    config = _run(
        tasks.generate_configuration_with_size(
            gui_container,
            platform="windows",
            screen_width=1280,
            screen_height=800,
        )
    )
    assert config.platform == "windows"
    assert config.screen_width == 1280
    assert config.screen_height == 800


def test_generate_configuration_task_creates_persisted_row(gui_container):
    config = _run(tasks.generate_configuration(gui_container, platform="macos"))
    assert config.id > 0
    assert config.platform == "macos"
    assert gui_container.configurations.get_configuration(config.id).id == config.id


def test_generate_from_template_task(gui_container):
    config = _run(
        tasks.generate_configuration_from_template(gui_container, "linux-chrome")
    )
    assert config.platform == "linux"
    assert config.user_agent and "Linux" in config.user_agent


@pytest.mark.parametrize("collect", [True, False])
def test_refresh_proxies_task_runs(gui_container, monkeypatch, collect):
    """Refresh must accept on_progress and finish cleanly with no proxies."""

    class FakeCollector:
        def collect(self, existing_keys, timeout=None):
            from app.domain.models.proxy_entry import ProxyBatch

            return ProxyBatch()

    monkeypatch.setattr(gui_container.proxies, "_collector", FakeCollector())
    progress_seen: list[tuple[int, int]] = []
    result = tasks.refresh_proxies(gui_container, collect=collect)(
        lambda done, total: progress_seen.append((done, total))
    )
    assert result.checked == 0
    if collect:
        assert result.created == 0


def test_lookup_ip_task_uses_checker(gui_container, monkeypatch):
    checker = gui_container.proxies._checker

    def fake_ensure():
        checker._direct_ip = "203.0.113.7"

    monkeypatch.setattr(checker, "ensure_direct_ip", fake_ensure)
    assert _run(tasks.lookup_ip(gui_container)) == "203.0.113.7"