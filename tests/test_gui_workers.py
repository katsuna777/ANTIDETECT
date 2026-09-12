"""Worker pipeline: outcome signals, error relay, progress and concurrency."""

from __future__ import annotations

import time

import pytest

from app.domain.errors import ProfileNotFoundError
from app.gui.workers.task_runner import TaskRunner

pytestmark = pytest.mark.usefixtures("qapp")

from tests.gui_helpers import spin_wait  # noqa: E402


def wait_done(results, count=1, timeout_ms=6000):
    return spin_wait(
        lambda: results.get("finished", 0) >= count,
        timeout_ms=timeout_ms,
    )


def test_worker_emits_result_then_finished():
    runner = TaskRunner()
    results = {"result": None, "progress": None, "finished": 0}

    runner.submit(
        lambda progress: (progress(2, 5), "payload")[1],
        on_result=lambda value: results.update(result=value),
        on_progress=lambda done, total: results.update(progress=(done, total)),
        on_finished=lambda: results.__setitem__("finished", results["finished"] + 1),
    )

    assert wait_done(results, 1)
    assert results["result"] == "payload"
    assert results["progress"] == (2, 5)
    assert results["finished"] == 1
    runner.shutdown()


def test_worker_forwards_antidetect_error():
    runner = TaskRunner()
    results = {"error": None, "finished": 0}

    def explode(progress):
        raise ProfileNotFoundError(404)

    runner.submit(
        explode,
        on_error=lambda exc: results.update(error=exc),
        on_finished=lambda: results.__setitem__("finished", results["finished"] + 1),
    )

    assert wait_done(results, 1)
    assert isinstance(results["error"], ProfileNotFoundError)
    assert results["finished"] == 1
    runner.shutdown()


def test_worker_catches_arbitrary_exceptions():
    runner = TaskRunner()
    results = {"error": None}

    def explode(progress):
        raise RuntimeError("boom")

    runner.submit(explode, on_error=lambda exc: results.update(error=exc))

    assert spin_wait(lambda: results["error"] is not None)
    assert isinstance(results["error"], RuntimeError)
    runner.shutdown()


def test_tasks_run_concurrently():
    """Two ~0.3s tasks must finish together (≈0.3s), not serially (≈0.6s)."""
    runner = TaskRunner()
    results = {"finished": 0, "results": []}
    started = time.monotonic()

    def make_task(tag):
        def run(progress):
            time.sleep(0.3)
            return tag

        return run

    for tag in ("a", "b"):
        runner.submit(
            make_task(tag),
            on_result=lambda value: results["results"].append(value),
            on_finished=lambda: results.__setitem__("finished", results["finished"] + 1),
        )

    assert wait_done(results, 2)
    elapsed = time.monotonic() - started
    assert sorted(results["results"]) == ["a", "b"]
    assert elapsed < 0.55, f"tasks did not overlap: {elapsed:.3f}s"
    runner.shutdown()


def test_active_task_counter_tracks_lifecycle():
    runner = TaskRunner()
    results = {"finished": 0}

    runner.submit(
        lambda progress: None,
        on_finished=lambda: results.__setitem__("finished", results["finished"] + 1),
    )
    assert runner.active_tasks == 1
    assert wait_done(results, 1)
    assert runner.active_tasks == 0
    runner.shutdown()