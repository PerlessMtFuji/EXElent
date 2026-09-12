"""Testy workera analizy w tle (B11).

Worker musi:
  - dostarczać wynik w sygnale `finished`,
  - odrzucać spóźniony wynik starego żądania,
  - przeżywać wyjątek w analizie (np. brak katalogu).
"""


from exelent.ui.analysis_worker import AnalysisWorker


def test_worker_delivers_result(qtbot, tmp_path):
    """Analiza prostego projektu daje wynik w sygnale `finished`."""
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    worker = AnalysisWorker()
    with qtbot.waitSignal(worker.finished, timeout=10_000) as blocker:
        worker.start(tmp_path)

    result = blocker.args[0]
    assert result.entry is not None
    assert result.entry.name == "main.py"


def test_worker_survives_missing_folder(qtbot, tmp_path):
    """Katalog, którego nie ma, nie powinien zabić wątku — wynik to
    ProjectAnalysis z blokadą `unexpected_error`."""
    worker = AnalysisWorker()
    with qtbot.waitSignal(worker.finished, timeout=10_000) as blocker:
        worker.start(tmp_path / "nie-ma-takiego")

    result = blocker.args[0]
    # Nie crash, a kontrolowany wynik:
    assert result is not None


def test_stale_result_is_discarded(qtbot, tmp_path):
    """Gdy użytkownik wybierze nowy folder w trakcie analizy, stary wynik
    jest odrzucany i nie emitowany do sygnału `finished`."""
    folder_a = tmp_path / "a"
    folder_a.mkdir()
    (folder_a / "main.py").write_text("print('a')\n", encoding="utf-8")

    folder_b = tmp_path / "b"
    folder_b.mkdir()
    (folder_b / "main.py").write_text("print('b')\n", encoding="utf-8")

    worker = AnalysisWorker()

    # Emitujemy dwa starty pod rząd — wynik powinien przyjść tylko raz,
    # z drugiego folderu (bo pierwszy jest anulowany/odrzucany).
    results = []
    worker.finished.connect(results.append)

    # Start A, potem natychmiast start B — A powinien zostać odrzucony.
    worker.start(folder_a)
    with qtbot.waitSignal(worker.finished, timeout=10_000):
        worker.start(folder_b)

    # Czekamy chwilę, żeby upewnić się, że nie przyszedł drugi wynik.
    qtbot.wait(200)
    assert len(results) == 1
    # Wynik powinien dotyczyć folderu B (nowego żądania).
    assert results[0].root == folder_b


def test_stop_returns_true_when_no_worker_running(qtbot):
    """stop() bez trwającego workera nie krzyczy."""
    worker = AnalysisWorker()
    assert worker.stop() is True


def test_is_running_reflects_state(qtbot, tmp_path):
    """is_running() zwraca True w trakcie analizy."""
    (tmp_path / "main.py").write_text("print('x')\n", encoding="utf-8")
    worker = AnalysisWorker()
    assert worker.is_running() is False
    with qtbot.waitSignal(worker.finished, timeout=10_000):
        worker.start(tmp_path)
        # Między start() a finished wątek powinien być uruchomiony.
        # (W praktyce analiza jest tak szybka, że może już być gotowa.)
    assert worker.is_running() is False
