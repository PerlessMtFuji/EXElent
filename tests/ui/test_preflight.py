"""Watek liczacy rozmiar pobierania dla ekranu 2.

Ekran nie moze sie zaciac na zapytaniu sieciowym, a jego porazka nie moze
zatrzymac budowania — to tylko liczba dla uzytkownika.
"""

from pathlib import Path

import pytest

from exelent.deps.sizes import DownloadPlan
from exelent.ui.preflight import PreflightWorker


@pytest.fixture
def worker(qtbot):
    w = PreflightWorker()
    yield w
    w.stop()


def test_no_dependencies_means_no_network_call(qtbot, worker, monkeypatch):
    called = []
    monkeypatch.setattr(worker, "_resolve", lambda packages, cancel: called.append(packages))
    with qtbot.waitSignal(worker.finished, timeout=2000) as blocker:
        worker.start([])
    assert called == []
    assert blocker.args[0].would_download == 0


def test_missing_uv_degrades_quietly(qtbot, worker, monkeypatch):
    """Preflight NIE pobiera uv — to praca fazy budowania, z wlasnym paskiem."""
    import exelent.ui.preflight as preflight_module

    monkeypatch.setattr(preflight_module, "uv_path", lambda: Path("nie-ma-mnie.exe"))
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(["scipy"])
    assert blocker.args[0] == DownloadPlan()


def test_result_reaches_the_signal(qtbot, worker, monkeypatch):
    expected = DownloadPlan(specs=("scipy==1.18.1",), would_download=1, total_bytes=36_700_160)
    monkeypatch.setattr(worker, "_resolve", lambda packages, cancel: expected)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(["scipy"])
    assert blocker.args[0] == expected


def test_waiting_for_the_plan_has_a_deadline(qtbot, worker, monkeypatch):
    """Spec 9.2: klikniecie "Stworz EXE" ma chwile POCZEKAC na wynik, a nie
    zawiesic okno na zapytaniu sieciowym."""
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

    assert elapsed < 3.0, "oczekiwanie przekroczylo swoj limit"
    assert plan == DownloadPlan()


def test_waiting_returns_the_real_plan_when_it_arrives_in_time(qtbot, worker, monkeypatch):
    import time

    expected = DownloadPlan(specs=("six==1.17.0",), would_download=1, total_bytes=11053)
    monkeypatch.setattr(worker, "_resolve", lambda packages, cancel: time.sleep(0.05) or expected)
    worker.start(["six"])

    assert worker.plan(wait_ms=5000) == expected


def test_stop_cancels_a_resolve_that_watches_the_token(qtbot, worker, monkeypatch):
    """Wolne liczenie ma sie przerwac, a nie dosiedziec do konca limitu."""
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
    assert elapsed < 3.0, "anulowanie nie doszlo do liczenia"


def test_stop_does_not_abandon_a_thread_that_ignores_the_token(qtbot, worker, monkeypatch):
    """Porzucony watek to `QThread: Destroyed while thread is still running`,
    czyli abort() przy wychodzeniu i proces, ktory zostaje w systemie."""
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
    """`plan(wait_ms)` nie moze dosiedziec do konca limitu po anulowaniu."""
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
    assert plan == DownloadPlan()
    assert elapsed < 2.0
