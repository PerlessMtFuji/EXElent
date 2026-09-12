"""Worker analizy w tle — pętla Qt nie zamraża się przy dużych projektach (B11).

Każde żądanie dostaje identyfikator: jeśli użytkownik wybierze nowy folder
zanim poprzednia analiza się skończy, spóźniony wynik jest odrzucany, a nie
wyświetlany na ekranie nowego wyboru.
"""

from __future__ import annotations

import itertools
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from exelent.analysis.project import analyze_project
from exelent.models import Issue, ProjectAnalysis, Severity

_THREAD_QUIT_TIMEOUT_MS = 5000

# Monotoniczny generator identyfikatorów żądań — dwa wywołania `start()`
# nigdy nie dostaną tego samego identyfikatora.
_request_counter = itertools.count(1)


class _AnalysisJob(QObject):
    """Właściwa robota, wykonywana w wątku roboczym."""

    finished = Signal(int, object)  # (request_id, ProjectAnalysis)

    def __init__(self, folder: Path, request_id: int) -> None:
        super().__init__()
        self._folder = folder
        self._request_id = request_id

    def run(self) -> None:
        try:
            result = analyze_project(self._folder)
        except Exception as exc:  # noqa: BLE001 - analiza nie moze zabic okna
            result = ProjectAnalysis(
                root=self._folder,
                scan=__import__("exelent.models", fromlist=["ScanResult"]).ScanResult(
                    root=self._folder
                ),
                issues=(
                    Issue(
                        "unexpected_error",
                        Severity.BLOCKER,
                        {"error": type(exc).__name__},
                    ),
                ),
            )
        self.finished.emit(self._request_id, result)


class AnalysisWorker(QObject):
    """Worker analizy projektu w tle (B11).

    Sygnał `finished` niesie wyłącznie wynik AKTUALNEGO żądania — wynik
    starego żądania (nowy wybór nastąpił w trakcie) jest odrzucany, a nie
    emitowany do ekranu.
    """

    finished = Signal(object)  # ProjectAnalysis

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._job: _AnalysisJob | None = None
        self._current_request: int = 0

    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, folder: Path) -> None:
        """Uruchamia analizę w tle. Poprzednie niedokończone żądanie jest
        cichym anulowaniem — jego wynik zostanie odrzucony po dostarczeniu."""
        self.stop()
        self._current_request = next(_request_counter)
        self._thread = QThread()
        self._job = _AnalysisJob(folder, self._current_request)
        self._job.moveToThread(self._thread)
        self._job.finished.connect(self._on_done)
        self._thread.started.connect(self._job.run)
        self._thread.start()

    def _on_done(self, request_id: int, result: ProjectAnalysis) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.quit()
            thread.wait(_THREAD_QUIT_TIMEOUT_MS)
        self._job = None

        # B11: spóźniony wynik starego żądania — odrzucamy, nie emitujemy.
        if request_id != self._current_request:
            return

        self.finished.emit(result)

    def stop(self, timeout_ms: int = _THREAD_QUIT_TIMEOUT_MS) -> bool:
        """Zatrzymuje trwającą analizę. Do zamykania okna."""
        thread = self._thread
        if thread is None:
            return True
        thread.quit()
        stopped = thread.wait(timeout_ms)
        if stopped:
            self._thread = None
            self._job = None
        return stopped
