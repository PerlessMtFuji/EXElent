"""Most miedzy watkiem budujacym a GUI — jedyne miejsce styku watkow.

Testy pilnuja trzech rzeczy, ktorych nie widac po samych sygnalach: ze build
NIE dzieje sie w watku okna, ze anulowanie dociera do JUZ TRWAJACEGO builda,
i ze awaria po tamtej stronie wraca jako wynik, a nie jako smierc programu.
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
    """Fabryka udawanego `run_build`, ktory stoi, dopoki mu nie pozwolimy isc."""
    zwolnij = threading.Event()
    wystartowal = threading.Event()
    widziane = {"wywolania": 0}

    def make(result=None, wait_for_cancel=False):
        def fake(root, progress, cancel, **kwargs):
            widziane["wywolania"] += 1
            widziane["watek"] = threading.get_ident()
            widziane["kwargs"] = kwargs
            widziane["root"] = root
            wystartowal.set()
            if wait_for_cancel:
                for _ in range(1000):
                    if cancel.cancelled:
                        break
                    threading.Event().wait(0.005)
            else:
                zwolnij.wait(timeout=5)
            widziane["anulowany"] = cancel.cancelled
            return result or BuildResult(ok=False)

        monkeypatch.setattr(worker_module, "run_build", fake)
        return widziane

    make.zwolnij = zwolnij
    make.wystartowal = wystartowal
    return make


# --- watek ---


def test_the_build_does_not_run_in_the_gui_thread(worker, qtbot, blocking_build, tmp_path):
    """Cala racja bytu tego modulu. Bez watku okno stoi zamrozone przez
    kilka minut i Windows oznacza je jako "nie odpowiada" — a zaden test
    sygnalow tego nie widzi, bo sygnaly docieraja tak samo."""
    widziane = blocking_build(BuildResult(ok=True))
    blocking_build.zwolnij.set()
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))
    assert widziane["watek"] != threading.main_thread().ident


def test_nothing_is_left_running_after_the_build(worker, qtbot, blocking_build, tmp_path):
    blocking_build(BuildResult(ok=True))
    blocking_build.zwolnij.set()
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))
    assert worker.is_running() is False


# --- sygnaly ---


def test_progress_signals_reach_the_gui(worker, qtbot, monkeypatch, tmp_path):
    def fake_run(root, progress, cancel, **kwargs):
        progress(Progress(phase="analyze", fraction=0.4))
        return BuildResult(ok=True, artifact=tmp_path / "Program.exe", size_bytes=1024)

    monkeypatch.setattr(worker_module, "run_build", fake_run)
    received = []
    worker.progress.connect(lambda update: received.append((update.phase, update.fraction)))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))

    assert ("analyze", 0.4) in received


def test_finished_carries_build_result(worker, qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(
        worker_module,
        "run_build",
        lambda root, progress, cancel, **kw: BuildResult(ok=True, size_bytes=42),
    )
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(_plan(tmp_path))
    assert blocker.args[0].size_bytes == 42


# --- co worker przekazuje rdzeniowi ---


def test_the_users_corrections_reach_the_build(worker, qtbot, blocking_build, tmp_path):
    """Ekran 2 istnieje po to, zeby uzytkownik poprawil zgadniecia analizy.
    Worker, ktory ich nie przekaze, kasuje caly ten ekran po cichu."""
    widziane = blocking_build(BuildResult(ok=True))
    blocking_build.zwolnij.set()
    plan = _plan(tmp_path)
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(plan)
    assert widziane["root"] == plan.root
    assert widziane["kwargs"] == {
        "entry": plan.entry,
        "exe_name": plan.exe_name,
        "icon": plan.icon,
        "dest_dir": plan.dest_dir,
        "app_kind": plan.app_kind,
        "output_mode": plan.output_mode,
        "total_download_bytes": plan.total_download_bytes,
    }


# --- awaria ---


def test_exception_becomes_failed_result_not_a_crash(worker, qtbot, monkeypatch, tmp_path):
    def boom(root, progress, cancel, **kwargs):
        raise RuntimeError("cos poszlo nie tak")

    monkeypatch.setattr(worker_module, "run_build", boom)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(_plan(tmp_path))
    result = blocker.args[0]
    assert result.ok is False and result.issues


def test_the_failure_is_a_sentence_not_a_template(worker, qtbot, monkeypatch, tmp_path):
    """`unexpected_error` istnieje w katalogu od zadania 16 i prosi o `{error}`.
    Issue z innym kluczem danych nie wywala `t()` — pokazuje laikowi nawias
    klamrowy w zdaniu. Cichy blad, wiec pilnowany maszynowo."""

    def boom(root, progress, cancel, **kwargs):
        raise RuntimeError("cos poszlo nie tak")

    monkeypatch.setattr(worker_module, "run_build", boom)
    with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
        worker.start(_plan(tmp_path))
    zdanie = describe(blocker.args[0].issues[0])
    assert "{" not in zdanie and "}" not in zdanie


# --- anulowanie ---


def test_cancel_reaches_a_build_that_is_already_running(worker, qtbot, blocking_build, tmp_path):
    """Prawdziwy scenariusz: przycisk "Anuluj" istnieje dopiero PO starcie.
    Wersja z planu anulowala przed startem, wiec nie sprawdzala niczego poza
    tym, ze token jest przekazany — a token wspoldzielony z trwajacym watkiem
    to jedyne, co tu naprawde dziala."""
    widziane = blocking_build(BuildResult(ok=False), wait_for_cancel=True)
    with qtbot.waitSignal(worker.finished, timeout=10000):
        worker.start(_plan(tmp_path))
        assert blocking_build.wystartowal.wait(timeout=5)
        worker.cancel()
    assert widziane["anulowany"] is True


def test_a_worker_builds_again_after_a_cancelled_build(worker, qtbot, blocking_build, tmp_path):
    """Jeden token na cale zycie workera oznaczalby, ze po anulowaniu KAZDY
    kolejny build startuje juz anulowany — i nikt by tego nie zauwazyl,
    bo build po prostu konczylby sie od razu."""
    widziane = blocking_build(BuildResult(ok=False), wait_for_cancel=True)
    with qtbot.waitSignal(worker.finished, timeout=10000):
        worker.start(_plan(tmp_path))
        assert blocking_build.wystartowal.wait(timeout=5)
        worker.cancel()

    blocking_build.wystartowal.clear()
    blocking_build.zwolnij.set()
    widziane = blocking_build(BuildResult(ok=True))
    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start(_plan(tmp_path))
    assert widziane["anulowany"] is False


def test_a_second_build_is_refused_while_one_runs(worker, qtbot, blocking_build, tmp_path):
    """Spec 3: jednoczesnie moze trwac tylko jeden build — chroni to wspolny
    cache srodowisk. Drugi start podmienilby watek w locie i pierwszy build
    zostalby bez wlasciciela."""
    widziane = blocking_build(BuildResult(ok=True))
    worker.start(_plan(tmp_path))
    assert blocking_build.wystartowal.wait(timeout=5)

    worker.start(_plan(tmp_path))

    with qtbot.waitSignal(worker.finished, timeout=5000):
        blocking_build.zwolnij.set()
    assert widziane["wywolania"] == 1


def test_shutdown_reports_failure_when_the_build_ignores_cancel(
    qtbot, worker, blocking_build, tmp_path
):
    """`closeEvent` opiera na tej odpowiedzi decyzje o twardym zakonczeniu
    programu, wiec porazka musi byc widoczna, a watek — nieporzucony."""
    blocking_build()
    worker.start(_plan(tmp_path))
    assert blocking_build.wystartowal.wait(timeout=5)

    try:
        assert worker.shutdown(timeout_ms=300) is False
        assert worker.is_running() is True
    finally:
        blocking_build.zwolnij.set()
        qtbot.waitUntil(lambda: not worker.is_running(), timeout=15000)
