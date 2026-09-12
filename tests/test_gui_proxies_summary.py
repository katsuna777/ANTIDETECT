"""Proxies page shows collection counts and source errors in the summary.

Regression test: REFRESH POOL used to report only "Checked 0 · working 0 …"
when every source failed, leaving the user with no explanation.
"""

from __future__ import annotations

import pytest

from app.application.proxy_service import RefreshSummary
from app.gui.widgets.pages.proxies_page import ProxiesPage

pytestmark = pytest.mark.usefixtures("qapp")


def _page(gui_container):
    from app.gui.workers.task_runner import TaskRunner

    return ProxiesPage(gui_container, TaskRunner())


def test_summary_shows_collected_count(gui_container):
    page = _page(gui_container)
    page._apply_check_summary(
        RefreshSummary(
            collected=120, created=100, checked=100,
            working=3, failed=97, dead=10, removed=97,
            elapsed_seconds=12.5,
        )
    )
    assert "collected 120" in page._result.text()
    assert "working 3" in page._result.text()


def test_summary_shows_source_errors(gui_container):
    page = _page(gui_container)
    page._apply_check_summary(
        RefreshSummary(
            collected=0, created=0, checked=0,
            working=0, failed=0, dead=0, removed=0,
            source_errors=["http: <urlopen error [Errno 8] nodename nor servname provided>"],
            elapsed_seconds=1.2,
        )
    )
    text = page._result.text()
    assert "Sources failed" in text
    assert "nodename nor servname" in text
