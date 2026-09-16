"""Worker that calculates download size for screen 2.

The screen must not freeze on a network request, and its failure must not
block the build — it is only a number for the user.
"""

from pathlib import Path

import pytest

from exelent.deps.sizes import DownloadPlan
from exelent.ui.preflight import PreflightWorker, preflight_key


@pytest.fixture
def worker(qtbot):
    w = PreflightWorker()
    yield w
    w.stop()


def test_no_project_dependencies_still_checks_the_build_tool(qtbot, worker, monkeypatch):
    called = []
    monkeypatch.setattr(
        worker,
        "_resolve",
        lambda packages, cancel: called.append(packages) or DownloadPlan(),
    )
    with qtbot.waitSignal(worker.finished, timeout=2000) as blocker:
        worker.start([])
    assert called == [[]]
    assert blocker.args[0].would_download == 0


def test_missing_uv_degrades_quietly(qtbot, worker, monkeypatch):
    """Preflight does NOT download uv — that is the build phase's job, with its own progress bar."""
    import exelent.ui.preflight as preflight_module

    monkeypatch.setattr(preflight_module, "uv_path", lambda: Path("missing.exe"))
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(["scipy"])
    plan = blocker.args[0]
    assert plan.would_download == 0
    assert plan.status == "missing_uv"


def test_result_reaches_the_signal(qtbot, worker, monkeypatch):
    expected = DownloadPlan(
        specs=("scipy==1.18.1",), would_download=1, total_bytes=36_700_160, status="complete"
    )
    monkeypatch.setattr(worker, "_resolve", lambda packages, cancel: expected)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(["scipy"])
    assert blocker.args[0] == DownloadPlan(
        specs=expected.specs,
        would_download=expected.would_download,
        total_bytes=expected.total_bytes,
        status=expected.status,
        request_key=preflight_key(["scipy"]),
    )


def test_waiting_for_the_plan_has_a_deadline(qtbot, worker, monkeypatch):
    """Spec 9.2: clicking "Create EXE" should briefly WAIT for the result, not
    freeze the window on a network request."""
    import threading
    import time

    release = threading.Event()

    def never_in_time(_packages, _cancel):
        release.wait(10)
        return DownloadPlan()

    monkeypatch.setattr(worker, "_resolve", never_in_time)
    worker.start(["scipy"])
    started = time.monotonic()

    plan = worker.plan(wait_ms=300)
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 3.0, "wait exceeded its bound"
    # B12: a plan being calculated has status "pending", not "empty".
    assert plan.would_download == 0


def test_waiting_returns_the_real_plan_when_it_arrives_in_time(qtbot, worker, monkeypatch):
    import time

    expected = DownloadPlan(specs=("six==1.17.0",), would_download=1, total_bytes=11053)
    monkeypatch.setattr(worker, "_resolve", lambda packages, cancel: time.sleep(0.05) or expected)
    worker.start(["six"])

    actual = worker.plan(wait_ms=5000)
    assert actual.total_bytes == expected.total_bytes
    assert actual.request_key == preflight_key(["six"])


def test_plan_matches_only_the_same_packages_and_target(qtbot, worker, monkeypatch):
    monkeypatch.setattr(worker, "_resolve", lambda _p, _c: DownloadPlan())
    worker.start(["six", "Requests>=2"])
    qtbot.waitUntil(lambda: not worker.is_running(), timeout=5000)

    assert worker.matches(["requests>=2", "six"], "3.12") is True
    assert worker.matches(["six"], "3.12") is False
    assert worker.matches(["requests>=2", "six"], "3.13") is False


def test_new_request_waits_for_an_old_thread_that_did_not_stop(qtbot, worker, monkeypatch):
    import threading

    release = threading.Event()
    calls = []

    def resolve(packages, _cancel):
        calls.append(tuple(packages))
        if packages == ["old"]:
            release.wait(10)
        return DownloadPlan(specs=(f"{packages[0]}==1",), status="complete")

    monkeypatch.setattr(worker, "_resolve", resolve)
    worker.start(["old"])
    qtbot.waitUntil(lambda: calls == [("old",)], timeout=5000)

    # Shortened timeout forces queuing instead of dropping the QThread reference.
    original_stop = worker.stop
    monkeypatch.setattr(worker, "stop", lambda: original_stop(timeout_ms=20))
    worker.start(["new"])
    assert worker.is_running() is True
    assert worker.plan().status == "pending"

    release.set()
    qtbot.waitUntil(lambda: calls == [("old",), ("new",)], timeout=5000)
    qtbot.waitUntil(lambda: not worker.is_running(), timeout=5000)
    assert worker.plan().specs == ("new==1",)


def test_stop_cancels_a_resolve_that_watches_the_token(qtbot, worker, monkeypatch):
    """Slow computation should be interrupted, not left to run until the deadline."""
    import threading
    import time

    started = threading.Event()

    def watching(_packages, cancel):
        started.set()
        for _ in range(4000):
            if cancel.cancelled:
                break
            time.sleep(0.005)
        return DownloadPlan()

    monkeypatch.setattr(worker, "_resolve", watching)
    worker.start(["scipy"])
    assert started.wait(timeout=5)

    began = time.monotonic()
    stopped = worker.stop()
    elapsed = time.monotonic() - began

    assert stopped is True
    assert worker.is_running() is False
    assert elapsed < 3.0, "cancellation did not reach calculation"


def test_stop_does_not_abandon_a_thread_that_ignores_the_token(qtbot, worker, monkeypatch):
    """An abandoned thread causes `QThread: Destroyed while thread is still running`,
    i.e. abort() on exit and a process left behind in the system."""
    import threading

    release = threading.Event()

    def deaf(_packages, _cancel):
        release.wait(30)
        return DownloadPlan()

    monkeypatch.setattr(worker, "_resolve", deaf)
    worker.start(["scipy"])

    try:
        assert worker.stop(timeout_ms=300) is False
        assert worker.is_running() is True
    finally:
        release.set()
        qtbot.waitUntil(lambda: not worker.is_running(), timeout=15000)


def test_stop_releases_whoever_waits_for_the_plan(qtbot, worker, monkeypatch):
    """`plan(wait_ms)` must not sit until the deadline after cancellation."""
    import threading
    import time

    release = threading.Event()
    monkeypatch.setattr(worker, "_resolve", lambda _p, _c: release.wait(30) or DownloadPlan())
    worker.start(["scipy"])
    worker.stop(timeout_ms=300)

    began = time.monotonic()
    plan = worker.plan(wait_ms=5000)
    elapsed = time.monotonic() - began

    release.set()
    qtbot.waitUntil(lambda: not worker.is_running(), timeout=15000)
    # B12: after stop() the plan has status "pending" (it didn't finish computing).
    assert plan.would_download == 0
    assert elapsed < 2.0
