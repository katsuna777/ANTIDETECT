"""Proxies page stays responsive on pools of thousands: live rows are
inserted in chunks with repaint disabled and progress widgets are throttled.

Regression test for the frozen .app freezing during REFRESH POOL: every
per-proxy outcome used to trigger a QListWidget relayout (O(n^2)) plus a
full progress repaint, so large pools lagged and appeared to skip proxies.
"""

from __future__ import annotations

import re
import time

import pytest

from app.gui.widgets.pages import proxies_page as proxies_mod
from app.gui.widgets.pages.proxies_page import ProxiesPage
from app.infrastructure.proxy.checker import CheckOutcome
from tests.fakes import make_proxy

pytestmark = pytest.mark.usefixtures("qapp")


def _page(gui_container):
    from app.gui.workers.task_runner import TaskRunner

    return ProxiesPage(gui_container, TaskRunner())


def _latencies(page):
    values = []
    for i in range(page._live.count()):
        match = re.search(r"(\d+)ms", page._live.item(i).text())
        assert match is not None
        values.append(int(match.group(1)))
    return values


def test_live_rows_are_buffered_and_flushed_sorted(gui_container):
    page = _page(gui_container)
    total = 250
    for i in range(total):
        proxy = make_proxy(1000 + i, host=f"10.9.0.{i % 250 + 1}")
        page._append_proxy(
            CheckOutcome(
                proxy=proxy,
                ok=True,
                latency_ms=total - i,
                country="Germany",
                country_code="DE",
            )
        )
    for i in range(50):
        proxy = make_proxy(2000 + i, host=f"10.10.0.{i + 1}")
        page._append_proxy(CheckOutcome(proxy=proxy, ok=False, error="refused"))

    assert page._live_working == total
    assert page._live_dead == 50
    # Two automatic chunk flushes (2 x 100) happened mid-stream.
    assert page._live.count() == 200
    page._flush_pending()
    assert page._live.count() == total
    assert _latencies(page) == sorted(_latencies(page))
    assert _latencies(page)[0] == 1
    assert _latencies(page)[-1] == total


def test_progress_final_update_always_paints(gui_container):
    page = _page(gui_container)
    page._show_progress(7, 100)
    first = page._progress_label.text()
    assert first == "7 / 100 (7%)"
    # A rapid follow-up is throttled away.
    page._show_progress(8, 100)
    assert page._progress_label.text() == first
    # The final update is never throttled.
    page._last_progress_ts = time.monotonic()
    page._show_progress(100, 100)
    assert page._progress_label.text() == "100 / 100 (100%)"


def test_workers_count_is_bounded():
    assert proxies_mod._PROXY_CHECK_WORKERS <= 64
