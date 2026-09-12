"""Proxies live list persists across restarts; profiles buttons wrap."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.enums.proxy_status import ProxyProtocol, ProxyStatus
from app.domain.models.proxy_check import ProxyCheck
from app.domain.models.proxy_entry import ProxyEntry
from app.gui.utils.flow_layout import FlowLayout
from app.gui.widgets.pages.profiles_page import ProfilesPage
from app.gui.widgets.pages.proxies_page import ProxiesPage

pytestmark = pytest.mark.usefixtures("qapp")


def _page(gui_container):
    from app.gui.workers.task_runner import TaskRunner

    return ProxiesPage(gui_container, TaskRunner())


def _seed_pool(gui_container):
    """3 stored proxies: fast WORKING (50ms), slow WORKING (300ms), DEAD."""
    repo = gui_container.proxies._proxies
    checks = gui_container.proxies._checks
    repo.upsert_many(
        [
            ProxyEntry(ProxyProtocol.HTTP, "10.0.0.1", 8080),
            ProxyEntry(ProxyProtocol.HTTP, "10.0.0.2", 8080),
            ProxyEntry(ProxyProtocol.HTTP, "10.0.0.3", 8080),
        ]
    )
    by_host = {proxy.host: proxy.id for proxy in repo.list()}
    now = datetime.now(timezone.utc)
    repo.apply_outcomes(
        [
            (by_host["10.0.0.1"], ProxyStatus.WORKING, 0, now),
            (by_host["10.0.0.2"], ProxyStatus.WORKING, 0, now),
            (by_host["10.0.0.3"], ProxyStatus.DEAD, 3, now),
        ]
    )
    checks.insert_many(
        [
            ProxyCheck(
                id=0, proxy_id=by_host["10.0.0.1"], checked_at=now,
                status=ProxyStatus.WORKING, latency_ms=50,
            ),
            ProxyCheck(
                id=0, proxy_id=by_host["10.0.0.2"], checked_at=now,
                status=ProxyStatus.WORKING, latency_ms=300,
            ),
        ]
    )


def test_reload_repopulates_list_from_store(gui_container):
    _seed_pool(gui_container)
    page = _page(gui_container)
    page._apply_stored_proxies(gui_container.proxies.list_proxies())

    assert page._live.count() == 2
    first = page._live.item(0).text()
    second = page._live.item(1).text()
    assert "10.0.0.1" in first and "50ms" in first
    assert "10.0.0.2" in second and "300ms" in second
    assert "WORKING" in first
    page.close()


def test_dead_proxies_stay_out_of_the_list(gui_container):
    _seed_pool(gui_container)
    page = _page(gui_container)
    page._apply_stored_proxies(gui_container.proxies.list_proxies())

    texts = [page._live.item(i).text() for i in range(page._live.count())]
    assert all("10.0.0.3" not in text for text in texts)
    page.close()


def test_metrics_match_store_after_repopulate(gui_container):
    _seed_pool(gui_container)
    page = _page(gui_container)
    page._apply_stored_proxies(gui_container.proxies.list_proxies())

    assert page._total._value.text() == "3"
    assert page._working._value.text() == "2"
    assert page._dead._value.text() == "1"
    page.close()


def test_stored_list_skipped_while_run_in_flight(gui_container):
    _seed_pool(gui_container)
    page = _page(gui_container)
    page._refresh.setEnabled(False)  # simulate an in-flight run
    page._apply_stored_proxies(gui_container.proxies.list_proxies())

    assert page._live.count() == 0
    page.close()


def test_profiles_buttons_live_in_flow_rows(gui_container):
    from app.gui.workers.task_runner import TaskRunner

    page = ProfilesPage(gui_container, TaskRunner())
    flows = page.findChildren(FlowLayout)
    assert flows, "lifecycle buttons must wrap instead of clipping off-screen"
    for name in ("_new", "_duplicate", "_edit", "_delete", "_start", "_stop", "_restart"):
        assert getattr(page, name) is not None
    page.close()
