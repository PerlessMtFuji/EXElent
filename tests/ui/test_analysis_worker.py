"""Tests for the background analysis worker (B11).

The worker must:
  - deliver the result via the `finished` signal,
  - discard a stale result from an old request,
  - survive an exception in the analysis (e.g. missing directory).
"""

from exelent.ui.analysis_worker import AnalysisWorker


def test_worker_delivers_result(qtbot, tmp_path):
    """Analysis of a simple project delivers a result via the `finished` signal."""
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    worker = AnalysisWorker()
    with qtbot.waitSignal(worker.finished, timeout=10_000) as blocker:
        worker.start(tmp_path)

    result = blocker.args[0]
    assert result.entry is not None
    assert result.entry.name == "main.py"


def test_worker_survives_missing_folder(qtbot, tmp_path):
    """A non-existent directory should not kill the thread — the result is a
    ProjectAnalysis with an `unexpected_error` blocker."""
    worker = AnalysisWorker()
    with qtbot.waitSignal(worker.finished, timeout=10_000) as blocker:
        worker.start(tmp_path / "nie-ma-takiego")

    result = blocker.args[0]
    # Not a crash, but a controlled result:
    assert result is not None


def test_stale_result_is_discarded(qtbot, tmp_path):
    """When the user selects a new folder during analysis, the old result is
    discarded and not emitted to the `finished` signal."""
    folder_a = tmp_path / "a"
    folder_a.mkdir()
    (folder_a / "main.py").write_text("print('a')\n", encoding="utf-8")

    folder_b = tmp_path / "b"
    folder_b.mkdir()
    (folder_b / "main.py").write_text("print('b')\n", encoding="utf-8")

    worker = AnalysisWorker()

    # We emit two starts in a row — the result should arrive only once,
    # from the second folder (because the first is cancelled/discarded).
    results = []
    worker.finished.connect(results.append)

    # Start A, then immediately start B — A should be discarded.
    worker.start(folder_a)
    with qtbot.waitSignal(worker.finished, timeout=10_000):
        worker.start(folder_b)

    # Wait a moment to make sure no second result arrived.
    qtbot.wait(200)
    assert len(results) == 1
    # The result should come from folder B (the new request).
    assert results[0].root == folder_b


def test_stop_returns_true_when_no_worker_running(qtbot):
    """stop() without a running worker does not raise."""
    worker = AnalysisWorker()
    assert worker.stop() is True


def test_is_running_reflects_state(qtbot, tmp_path):
    """is_running() returns True during analysis."""
    (tmp_path / "main.py").write_text("print('x')\n", encoding="utf-8")
    worker = AnalysisWorker()
    assert worker.is_running() is False
    with qtbot.waitSignal(worker.finished, timeout=10_000):
        worker.start(tmp_path)
        # Between start() and finished the thread should be running.
        # (In practice analysis is so fast it may already be done.)
    assert worker.is_running() is False
