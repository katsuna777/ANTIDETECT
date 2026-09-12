"""Real-time proxy streaming and profile create/edit behaviors.

These exercise page-level wiring through the real TaskRunner thread pool on the
offscreen platform, using a stubbed checker that yields instant results.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from app.domain.enums.proxy_status import ProxyStatus
from app.domain.models.proxy import Proxy, ProxyWithCheck
from app.domain.models.proxy_entry import ProxyBatch, ProxyEntry
from app.gui import workers
from app.gui.dialogs.profile_edit_dialog import ProfileEditDialog
from app.gui.main_window import MainWindow
from app.gui.workers.task_runner import TaskRunner
from tests.fakes import CheckOutcome, StubChecker, make_proxy
from tests.gui_helpers import spin_wait

pytestmark = pytest.mark.usefixtures("qapp")


class FakeCollector:
    """Returns a fixed list of candidates after REFRESH POOL wipes the pool."""

    def __init__(self, entries: list[ProxyEntry]) -> None:
        self._entries = entries

    def collect(self, existing_keys=None, default_protocols=None, timeout=None):
        return ProxyBatch(entries=list(self._entries), source_stats=[])


def _seed_proxies(container, count: int) -> list:
    proxies = [
        make_proxy(i, host=f"10.0.0.{i}", port=8080) for i in range(1, count + 1)
    ]
    entries = [
        ProxyEntry(
            protocol=p.protocol,
            host=p.host,
            port=p.port,
            source="test",
        )
        for p in proxies
    ]
    container.proxies._proxies.upsert_many(entries)  # type: ignore[attr-defined]
    # REFRESH POOL wipes the pool and rebuilds it from the collector: the fake
    # collector hands those same entries back so the check pipeline has work.
    container.proxies._collector = FakeCollector(entries)  # type: ignore[attr-defined]
    return proxies


def _working_outcome(proxy) -> CheckOutcome:
    return CheckOutcome(
        proxy=proxy,
        ok=True,
        latency_ms=12,
        country="Russia",
        country_code="RU",
        error=None,
    )


def _row(proxy, *, check_error=None, status=None, latency_ms=15) -> ProxyWithCheck:
    """A ProxyWithCheck read model; status defaults to the proxy's status."""
    return ProxyWithCheck(
        proxy=(
            proxy.replace(status=status) if status is not None else proxy
        ),
        latency_ms=latency_ms,
        country="Russia",
        country_code="RU",
        check_error=check_error,
    )


def test_refresh_streams_new_pool_into_live_list(gui_container, qapp):
    """REFRESH POOL streams every newly collected proxy into the live list in real time."""
    proxies = _seed_proxies(gui_container, 50)
    gui_container.proxies._checker = StubChecker(
        by_id={p.id: _working_outcome(p) for p in proxies}
    )  # type: ignore[attr-defined]

    window = MainWindow(gui_container)
    window.show()
    page = window.page("proxies")
    page._run()

    assert spin_wait(lambda: page._live.count() == 50, timeout_ms=8000)
    texts = [page._live.item(i).text() for i in range(50)]
    assert sum("WORKING" in t for t in texts) == 50
    window.close()


def test_refresh_result_label_reports_summary(gui_container, qapp):
    """After a full batch the result label shows the final counts."""
    proxies = _seed_proxies(gui_container, 5)
    gui_container.proxies._checker = StubChecker(
        by_id={p.id: _working_outcome(p) for p in proxies}
    )  # type: ignore[attr-defined]

    window = MainWindow(gui_container)
    window.show()
    page = window.page("proxies")
    page._run()

    assert spin_wait(
        lambda: "working 5" in page._result.text(), timeout_ms=8000
    )
    window.close()


def test_refresh_drops_dead_proxies(gui_container, qapp):
    """Proxies that fail the fresh check are never streamed and are purged from the database."""
    proxies = _seed_proxies(gui_container, 3)
    outcomes = {p.id: _working_outcome(p) for p in proxies}
    outcomes[2] = CheckOutcome(proxy=proxies[1], ok=False, error="refused")
    gui_container.proxies._checker = StubChecker(by_id=outcomes)  # type: ignore[attr-defined]

    window = MainWindow(gui_container)
    window.show()
    page = window.page("proxies")
    page._run()

    assert spin_wait(lambda: page._live.count() == 2, timeout_ms=8000)
    texts = [page._live.item(i).text() for i in range(2)]
    assert all("WORKING" in t for t in texts)
    window.close()


def test_stop_check_marks_event_and_disables_button(gui_container, qapp):
    """STOP flags any in-flight batch and disables itself until it finishes."""
    window = MainWindow(gui_container)
    window.show()
    page = window.page("proxies")

    import threading

    stop = threading.Event()
    page._stop_event = stop
    page._stop.setEnabled(True)
    page._stop_check()
    assert stop.is_set()
    assert not page._stop.isEnabled()
    assert page._result.text().startswith("Stopping")

    page._stop_event = None
    window.close()


def test_configurations_delete_button_removes_selected(gui_container, qapp):
    """DELETE removes the selected configuration and re-lists the pool."""
    from PySide6.QtWidgets import QMessageBox

    before = len(gui_container.configurations.list_configurations())
    gui_container.configurations.generate_configuration(platform="linux")

    window = MainWindow(gui_container)
    window.show()
    page = window.page("configurations")
    assert spin_wait(
        lambda: page._list.count() == before + 1, timeout_ms=8000
    )
    assert not page._delete.isEnabled()
    page._list.setCurrentItem(page._list.item(0))
    assert page._delete.isEnabled()
    # Bypass the confirmation dialog and drive the deletion path directly.
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        page._delete_config()
    finally:
        QMessageBox.question = original

    assert spin_wait(
        lambda: page._list.count() == before, timeout_ms=8000
    )
    assert len(gui_container.configurations.list_configurations()) == before
    window.close()


def test_profile_create_and_assign_configuration(gui_container, qapp):
    """Creating a profile and assigning a config persists through services."""
    runner = TaskRunner()
    results: dict = {}
    runner.submit(
        workers.tasks.create_profile(gui_container, "one"),
        on_result=lambda p: results.update(profile=p),
    )
    assert spin_wait(lambda: "profile" in results, timeout_ms=8000)
    profile = results["profile"]

    cfg = gui_container.configurations.generate_configuration(platform="linux")
    cfg_results: dict = {}
    runner.submit(
        workers.tasks.assign_configuration(gui_container, profile.id, cfg.id),
        on_result=lambda p: cfg_results.update(updated=p),
    )
    assert spin_wait(lambda: "updated" in cfg_results, timeout_ms=8000)
    assert cfg_results["updated"].configuration_id == cfg.id
    runner.shutdown()


# --------------------------------------------------------------------------- #
# Regression: profiles page button state + edit dialog behaviors
# --------------------------------------------------------------------------- #


def test_profile_create_keeps_new_button_enabled(gui_container, qapp):
    """NEW must stay usable after a create; the old `reload() and …` hook
    short-circuited on reload()'s None return and disabled the button forever."""
    window = MainWindow(gui_container)
    window.show()
    page = window.page("profiles")

    original = QInputDialog.getText
    QInputDialog.getText = staticmethod(lambda *a, **k: ("gamma", True))
    try:
        page._create_profile()
    finally:
        QInputDialog.getText = original

    assert spin_wait(lambda: "created" in page._result.text(), timeout_ms=8000)
    assert spin_wait(lambda: page._new.isEnabled(), timeout_ms=8000)
    assert "gamma" in page._result.text()
    window.close()


def test_profile_delete_re_enables_and_reports_single_profile(gui_container, qapp):
    """DELETE must re-enable after the row is gone and the result label must
    name exactly one padded profile id, never a bare quantity."""
    window = MainWindow(gui_container)
    window.show()
    page = window.page("profiles")

    created = []
    for name in ("one", "two"):
        result: dict = {}
        window._runner.submit(
            workers.tasks.create_profile(gui_container, name),
            on_result=lambda p, r=result: r.update(profile=p),
        )
        assert spin_wait(lambda r=result: "profile" in r, timeout_ms=8000)
        created.append(result["profile"])

    page.reload()
    assert spin_wait(lambda: page._list.count() == 2, timeout_ms=8000)
    page._list.setCurrentRow(0)
    target = page._selected_id()

    original = QMessageBox.question
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    try:
        page._delete_profile()
    finally:
        QMessageBox.question = original

    assert spin_wait(lambda: page._result.text().endswith(" deleted."), timeout_ms=8000)
    assert spin_wait(lambda: page._list.count() == 1, timeout_ms=8000)
    assert f"#{target:03d}" in page._result.text()
    # Buttons re-enable once the list settles, and stay usable with a selection.
    assert spin_wait(lambda: page._new.isEnabled(), timeout_ms=8000)
    assert not page._delete.isEnabled()  # no row selected after the reload
    page._list.setCurrentRow(0)
    assert page._delete.isEnabled()
    window.close()


def test_profile_edit_dialog_allows_rename(gui_container):
    """The edit dialog exposes the name as editable text, not a frozen label."""
    profile = gui_container.profiles.create_profile("rename-me")
    dialog = ProfileEditDialog(
        profile, gui_container.configurations.list_configurations(), []
    )
    assert dialog._name.isEnabled()
    dialog._name.setText("  renamed  ")
    assert dialog.name == "renamed"
    dialog.deleteLater()


def test_profile_edit_dialog_hides_failed_latest_check_proxies(gui_container):
    """Proxies whose latest check failed must not be offered, even when the
    resilient status field still says WORKING (it lags behind by design)."""
    proxy_good = make_proxy(1, host="10.0.0.1")
    proxy_failed = make_proxy(2, host="10.0.0.2", status="WORKING")
    profile = gui_container.profiles.create_profile("select-proxy")

    rows = [
        _row(proxy_good, status=ProxyStatus.WORKING, latency_ms=11),
        _row(proxy_failed, check_error="refused", status=ProxyStatus.WORKING),
    ]
    dialog = ProfileEditDialog(profile, [], rows)
    data = [dialog._proxy.itemData(i) for i in range(dialog._proxy.count())]
    assert dialog._proxy.findData(1) >= 0
    assert dialog._proxy.findData(2) < 0
    dialog.deleteLater()


def test_profile_edit_dialog_keeps_assigned_proxy_locked(gui_container):
    """A dead assigned proxy stays visible but disabled so saving an unrelated
    edit never silently clears the assignment."""
    from app.domain.enums.proxy_status import ProxyProtocol

    gui_container.proxies._proxies.upsert_many([  # type: ignore[attr-defined]
        ProxyEntry(protocol=ProxyProtocol.HTTP, host="10.0.0.3", port=8080, source="test"),
    ])
    stored = gui_container.proxies.list_proxies()[0].proxy
    profile = gui_container.profiles.create_profile(
        "assigned", proxy_id=stored.id
    )

    rows = [_row(stored, check_error="refused", status=ProxyStatus.WORKING)]
    dialog = ProfileEditDialog(profile, [], rows)
    idx = dialog._proxy.findData(stored.id)
    assert idx >= 0
    item = dialog._proxy.model().item(idx)
    assert not item.isEnabled()
    assert dialog._proxy.currentData() == stored.id
    dialog.deleteLater()


def test_proxies_metric_strip_resets_and_streams_live(gui_container, qapp):
    """TOTAL / WORKING / DEAD reset at the start of a check and update on each
    streamed result instead of freezing on the previous database snapshot."""

    class SlowChecker(StubChecker):
        def check_all(
            self, proxies, workers=None, timeout=None, on_progress=None,
            on_proxy=None, stop_event=None,
        ):
            results = [
                CheckOutcome(
                    proxy=p, ok=(p.id % 2 == 0), latency_ms=10,
                    country="RU", country_code="RU",
                )
                for p in proxies
            ]
            for outcome in results:
                if stop_event is not None and stop_event.is_set():
                    break
                time.sleep(0.1)
                if on_proxy is not None:
                    on_proxy(outcome)
            return results

    _seed_proxies(gui_container, 3)
    gui_container.proxies._checker = SlowChecker(by_id={})  # type: ignore[attr-defined]
    window = MainWindow(gui_container)
    window.show()
    page = window.page("proxies")
    page._run()

    # Start of the run: strip reset to zero.
    assert page._working._value.text() == "0"
    assert page._dead._value.text() == "0"
    # First streamed result already moves the strip.
    assert spin_wait(
        lambda: page._working._value.text() == "1", timeout_ms=8000
    )
    # Final database summary agrees with the live stream.
    assert spin_wait(
        lambda: "working 1" in page._result.text(), timeout_ms=8000
    )
    window.close()