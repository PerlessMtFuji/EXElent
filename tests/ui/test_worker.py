"""Bridge between the build thread and GUI, the sole thread boundary.

These tests cover three facts that signals alone cannot show: the build does
not run on the GUI thread, cancellation reaches an active build, and a worker
failure returns as a result instead of terminating the program.
"""

import threading

import pytest

from exelent.i18n import describe
from exelent.models import AppKind, BuildPlan, BuildResult, OutputMode
from exelent.runtime import Progress
from exelent.ui import worker as worker_module
from exelent.ui.worker import BuildWorker


def _plan(tmp_path):
    return BuildPlan(
        root=tmp_path,
        entry=tmp_path / "main.py",
        app_kind=AppKind.CONSOLE,
        output_mode=OutputMode.ONEFILE,
        exe_name="Program",
        dest_dir=tmp_path / "out",
    )


@pytest.fixture
def worker(qtbot):
    w = BuildWorker()
    yield w
    if w.is_running():
        w.cancel()
        qtbot.waitUntil(lambda: not w.is_running(), timeout=5000)


@pytest.fixture
def blocking_build(monkeypatch):
    """Create a fake `execute_build` that waits until the test releases it."""
    release = threading.Event()
    started = threading.Event()
    observed = {"calls": 0}

    def make(result=None, wait_for_cancel=False):
        def fake(plan, progress, cancel, *, carried=()):
            observed["calls"] += 1
            observed["thread"] = threading.get_ident()
            observed["plan"] = plan
            observed["carried"] = tuple(carried)
            started.set()
            if wait_for_cancel:
                for _ in range(1000):
                    if cancel.cancelled:
                        break
                    threading.Event().wait(0.005)
            else:
                release.wait(timeout=5)
            observed["cancelled"] = cancel.cancelled
            return result or BuildResult(ok=False)

        monkeypatch.setattr(worker_module, "execute_build", fake)
        return observed

    make.release = release
    make.started = started
    return make


# --- thread ---


def test_the_build_does_not_run_in_the_gui_thread(worker, qtbot, blocking_build, tmp_path):
    """The module exists to keep lengthy builds off the GUI thread.

    Otherwise the window freezes for minutes and Windows marks it as not
    responding, while signal-only tests still appear to pass.
    """
    observed = blocking_build(BuildResult(ok=True))
    blocking_build.release.set()
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))
    assert observed["thread"] != threading.main_thread().ident


def test_nothing_is_left_running_after_the_build(worker, qtbot, blocking_build, tmp_path):
    blocking_build(BuildResult(ok=True))
    blocking_build.release.set()
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))
    assert worker.is_running() is False


# --- signals ---


def test_progress_signals_reach_the_gui(worker, qtbot, monkeypatch, tmp_path):
    def fake_run(plan, progress, cancel, **kwargs):
        progress(Progress(phase="analyze", fraction=0.4))
        return BuildResult(ok=True, artifact=tmp_path / "Program.exe", size_bytes=1024)

    monkeypatch.setattr(worker_module, "execute_build", fake_run)
    received = []
    worker.progress.connect(lambda update: received.append((update.phase, update.fraction)))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))

    assert ("analyze", 0.4) in received


def test_finished_carries_build_result(worker, qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(
        worker_module,
        "execute_build",
        lambda plan, progress, cancel, **kw: BuildResult(ok=True, size_bytes=42),
    )
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(_plan(tmp_path))
    assert blocker.args[0].size_bytes == 42


# --- values passed from the worker to the core ---


def test_the_ready_plan_is_built_verbatim(worker, qtbot, blocking_build, tmp_path):
    """The worker builds the exact plan that the user reviewed on screen 2.

    Calling `run_build(plan.root, ...)` would analyze the directory again and
    lose single-file selection, packaging all of Downloads for `Downloads/x.py`.
    """
    observed = blocking_build(BuildResult(ok=True))
    blocking_build.release.set()
    plan = _plan(tmp_path)
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(plan)
    assert observed["plan"] is plan  # same plan, not reconstructed from analysis


def test_analysis_warnings_are_carried_to_the_build(worker, qtbot, blocking_build, tmp_path):
    """Analysis warnings from screen 2 must reach the result screen.

    The worker therefore passes them through to `execute_build`.
    """
    from exelent.models import Issue, Severity

    observed = blocking_build(BuildResult(ok=True))
    blocking_build.release.set()
    carried = (Issue("secret_in_code", Severity.WARNING),)
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path), carried)
    assert observed["carried"] == carried


# --- failure ---


def test_exception_becomes_failed_result_not_a_crash(worker, qtbot, monkeypatch, tmp_path):
    def boom(plan, progress, cancel, **kwargs):
        raise RuntimeError("something went wrong")

    monkeypatch.setattr(worker_module, "execute_build", boom)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(_plan(tmp_path))
    result = blocker.args[0]
    assert result.ok is False and result.issues


def test_the_failure_is_a_sentence_not_a_template(worker, qtbot, monkeypatch, tmp_path):
    """`unexpected_error` expects an `{error}` value in the catalog.

    An Issue using a different data key leaves braces in the user-facing
    sentence instead of breaking `t()`, so a test guards this quiet failure.
    """

    def boom(plan, progress, cancel, **kwargs):
        raise RuntimeError("something went wrong")

    monkeypatch.setattr(worker_module, "execute_build", boom)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(_plan(tmp_path))
    sentence = describe(blocker.args[0].issues[0])
    assert "{" not in sentence and "}" not in sentence


# --- cancellation ---


def test_cancel_reaches_a_build_that_is_already_running(worker, qtbot, blocking_build, tmp_path):
    """The Cancel button exists only after the build has started.

    Cancelling before start would prove only that a token is passed. This test
    proves the active thread shares and observes that token.
    """
    observed = blocking_build(BuildResult(ok=False), wait_for_cancel=True)
    with qtbot.waitSignal(worker.finished, timeout=10000):
        worker.start(_plan(tmp_path))
        assert blocking_build.started.wait(timeout=5)
        worker.cancel()
    assert observed["cancelled"] is True


def test_a_worker_builds_again_after_a_cancelled_build(worker, qtbot, blocking_build, tmp_path):
    """A worker-lifetime token would start every later build as cancelled."""
    observed = blocking_build(BuildResult(ok=False), wait_for_cancel=True)
    with qtbot.waitSignal(worker.finished, timeout=10000):
        worker.start(_plan(tmp_path))
        assert blocking_build.started.wait(timeout=5)
        worker.cancel()

    blocking_build.started.clear()
    blocking_build.release.set()
    observed = blocking_build(BuildResult(ok=True))
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))
    assert observed["cancelled"] is False


def test_a_second_build_is_refused_while_one_runs(worker, qtbot, blocking_build, tmp_path):
    """Spec 3 permits only one active build to protect the shared env cache.

    A second start would replace the live thread and orphan the first build.
    """
    observed = blocking_build(BuildResult(ok=True))
    worker.start(_plan(tmp_path))
    assert blocking_build.started.wait(timeout=5)

    worker.start(_plan(tmp_path))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        blocking_build.release.set()
    assert observed["calls"] == 1


def test_shutdown_reports_failure_when_the_build_ignores_cancel(
    qtbot, worker, blocking_build, tmp_path
):
    """`closeEvent` uses this answer to decide whether to terminate forcefully.

    Failure must remain visible and the thread must remain owned.
    """
    blocking_build()
    worker.start(_plan(tmp_path))
    assert blocking_build.started.wait(timeout=5)

    try:
        assert worker.shutdown(timeout_ms=300) is False
        assert worker.is_running() is True
    finally:
        blocking_build.release.set()
        qtbot.waitUntil(lambda: not worker.is_running(), timeout=15000)
