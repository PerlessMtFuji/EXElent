"""Ile trzeba będzie pobrać — policzone w tle, zanim użytkownik kliknie.

Rozwiązanie zależności woła uv i PyPI, więc nie może biec w wątku okna.
Wątek jest anulowalny i cicho degraduje: brak uv, brak sieci albo błąd PyPI
zostawia pusty plan, a ekran wraca do szacunku z tabeli.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from PySide6.QtCore import QObject, Qt, QThread, Signal

from exelent.build.backend import CancelToken
from exelent.deps.sizes import DownloadPlan, resolve_download_plan
from exelent.runtime.bootstrap import uv_path

_THREAD_QUIT_TIMEOUT_MS = 5000


class _Job(QObject):
    finished = Signal(object)

    def __init__(self, packages: Sequence[str], resolve, cancel: CancelToken) -> None:
        super().__init__()
        self._packages = list(packages)
        self._resolve = resolve
        self._cancel = cancel

    def run(self) -> None:
        try:
            plan = self._resolve(self._packages, self._cancel)
        except Exception:  # noqa: BLE001 - liczba dla uzytkownika nie moze zabic okna
            plan = DownloadPlan()
        self.finished.emit(plan)


class PreflightWorker(QObject):
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._job: _Job | None = None
        self._token: CancelToken | None = None
        self._plan = DownloadPlan()
        # Zdarzenie, a nie `QThread.wait`: wątek roboczy kręci własną pętlę
        # zdarzeń i kończy ją dopiero `quit()` z wątku głównego. Gdyby okno
        # czekało na `QThread.wait`, czekałoby na `quit()`, którego samo nie
        # zdąży zawołać — czyli zawsze do końca limitu.
        self._done = threading.Event()
        self._done.set()

    def plan(self, wait_ms: int = 0) -> DownloadPlan:
        """Ostatni policzony plan. `wait_ms > 0` czeka na trwające liczenie.

        Specyfikacja §9.2 wymaga tego wprost: kliknięcie „Stwórz EXE" ma
        chwilę POCZEKAĆ na wynik, a nie zawiesić okno na zapytaniu sieciowym
        ani po cichu pominąć pytanie o zgodę. Po upływie limitu oddajemy to,
        co jest — pusty plan znaczy „licz z tabeli".
        """
        if wait_ms > 0:
            self._done.wait(wait_ms / 1000)
        return self._plan

    def _resolve(self, packages: Sequence[str], cancel: CancelToken) -> DownloadPlan:
        uv = uv_path()
        if not uv.exists():
            # Preflight NIE pobiera uv. To praca fazy budowania, ktora ma na to
            # wlasny pasek postepu — sciaganie 15 MB w tle ekranu 2, bez slowa
            # do uzytkownika, byloby niespodzianka.
            return DownloadPlan()
        python = uv.parent / "preflight-venv" / "Scripts" / "python.exe"
        return resolve_download_plan(uv=uv, python=python, packages=packages, cancel=cancel)

    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, packages: Sequence[str]) -> None:
        self.stop()
        if not packages:
            self._plan = DownloadPlan()
            self._done.set()
            self.finished.emit(self._plan)
            return
        self._done.clear()
        self._token = CancelToken()
        self._thread = QThread()
        self._job = _Job(packages, self._resolve, self._token)
        self._job.moveToThread(self._thread)
        # DWA połączenia do jednego sygnału, celowo. Bezpośrednie zapisuje
        # wynik jeszcze w wątku roboczym, żeby `plan(wait_ms)` miał na co
        # czekać; kolejkowane sprząta wątek w wątku głównym, bo tylko stamtąd
        # wolno wołać `quit()`/`wait()` na własnym wątku.
        self._job.finished.connect(self._store, Qt.ConnectionType.DirectConnection)
        self._job.finished.connect(self._on_done)
        self._thread.started.connect(self._job.run)
        self._thread.start()

    def _store(self, plan: DownloadPlan) -> None:
        self._plan = plan
        self._done.set()

    def _on_done(self, plan: DownloadPlan) -> None:
        self._plan = plan
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.quit()
            thread.wait(_THREAD_QUIT_TIMEOUT_MS)
        self._job = None
        self.finished.emit(plan)

    def stop(self, timeout_ms: int = _THREAD_QUIT_TIMEOUT_MS) -> bool:
        """Zatrzymuje trwające liczenie i CZEKA na wątek. Mówi, czy wyszedł.

        Qt niszczy działający `QThread` przy wychodzeniu (abort), więc
        `MainWindow.closeEvent` musi to zawołać — tak samo jak robi to dla
        `BuildWorker.shutdown`.

        Anulowanie idzie NAJPIERW, bo samo `quit()` kończy jedynie pętlę
        zdarzeń wątku: robota siedząca w `uv pip install --dry-run` nie ma
        pętli, w której by to zauważyła, i `wait()` zawsze dosiedziałby do
        końca limitu.

        Referencje kasujemy tylko wtedy, gdy wątek NAPRAWDĘ wyszedł.
        Zapomnienie o działającym wątku nie sprawia, że przestaje istnieć —
        sprawia tylko, że nikt już nie wie, że trzeba na niego poczekać, a
        Qt niszczy go przy wychodzeniu z programu.
        """
        thread = self._thread
        if thread is None:
            self._done.set()
            return True
        if self._token is not None:
            self._token.cancel()
        thread.quit()
        stopped = thread.wait(timeout_ms)
        if stopped:
            self._thread = None
            self._job = None
        # Nikt juz nie policzy tego planu — czekajacy ma ruszyc dalej, a nie
        # dosiedziec do konca limitu.
        self._done.set()
        return stopped
