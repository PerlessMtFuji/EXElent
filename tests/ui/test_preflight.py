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
    monkeypatch.setattr(worker, "_resolve", lambda packages: called.append(packages))
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
    monkeypatch.setattr(worker, "_resolve", lambda packages: expected)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(["scipy"])
    assert blocker.args[0] == expected


def test_waiting_for_the_plan_has_a_deadline(qtbot, worker, monkeypatch):
    """Spec 9.2: klikniecie "Stworz EXE" ma chwile POCZEKAC na wynik, a nie
    zawiesic okno na zapytaniu sieciowym."""
    import threading
    import time

    release = threading.Event()

    def never_in_time(_packages):
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
    monkeypatch.setattr(worker, "_resolve", lambda packages: time.sleep(0.05) or expected)
    worker.start(["six"])

    assert worker.plan(wait_ms=5000) == expected
