"""Most między wątkiem budującym a GUI. Jedyne miejsce styku wątków.

Build trwa od minuty do kilku i nie może zamrozić okna. Cała komunikacja idzie
sygnałami: `_Job` żyje w `QThread`, `BuildWorker` w wątku okna, więc połączenia
są kolejkowane i żadna struktura nie jest dotykana z dwóch stron naraz.
Jedynym obiektem współdzielonym jest `CancelToken` — a on jest do tego
zbudowany (`threading.Event` w środku).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from exelent.build.backend import CancelToken
from exelent.cli import run_build
from exelent.models import BuildPlan, BuildResult, Issue, Severity

# Ile czekamy na zamknięcie wątku po zakończeniu budowania. Wątek w tym
# momencie ma już tylko wyjść z pętli zdarzeń, więc czekanie jest chwilowe;
# limit istnieje po to, żeby okno nie zawisło na zawsze, gdyby nie wyszedł.
_THREAD_QUIT_TIMEOUT_MS = 5000


class _Job(QObject):
    """Właściwa robota, wykonywana w wątku roboczym."""

    progress = Signal(object)
    finished = Signal(object)

    def __init__(self, plan: BuildPlan, cancel: CancelToken) -> None:
        super().__init__()
        self._plan = plan
        self._cancel = cancel

    def run(self) -> None:
        plan = self._plan
        try:
            result = run_build(
                plan.root,
                self.progress.emit,
                self._cancel,
                # To, co użytkownik poprawił na ekranie 2. Bez tego cały tamten
                # ekran byłby dekoracją: build zbudowałby to, co zgadła analiza.
                entry=plan.entry,
                exe_name=plan.exe_name,
                icon=plan.icon,
                dest_dir=plan.dest_dir,
                app_kind=plan.app_kind,
                output_mode=plan.output_mode,
            )
        except Exception as exc:  # noqa: BLE001 - GUI nie moze umrzec przez build
            # `run_build` ma własną granicę wyjątków, więc tu trafia tylko to,
            # co ją ominęło. Kod i klucz danych są TE SAME co w rdzeniu
            # (`cli._unexpected_issues`): katalog opisuje `unexpected_error`
            # parametrem `{error}`, a Issue z innym kluczem nie wywala `t()` —
            # pokazuje laikowi nawias klamrowy w środku zdania.
            result = BuildResult(
                ok=False,
                issues=(
                    Issue("unexpected_error", Severity.BLOCKER, {"error": type(exc).__name__}),
                ),
            )
        self.finished.emit(result)


class BuildWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._token: CancelToken | None = None
        self._thread: QThread | None = None
        self._job: _Job | None = None

    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, plan: BuildPlan) -> None:
        """Rusza build w osobnym wątku.

        Token powstaje TUTAJ, nie raz na życie workera: jeden token na zawsze
        znaczyłby, że po pierwszym anulowaniu każdy kolejny build startuje już
        anulowany i kończy się natychmiast, a nikt nie umiałby powiedzieć
        dlaczego.

        Drugi build w trakcie pierwszego jest odrzucany — spec §3 dopuszcza
        jeden naraz, bo oba korzystają z tego samego cache'u środowisk.
        """
        if self.is_running():
            return
        self._token = CancelToken()
        self._thread = QThread()
        self._job = _Job(plan, self._token)
        self._job.moveToThread(self._thread)
        self._job.progress.connect(self.progress)
        self._job.finished.connect(self._on_done)
        self._thread.started.connect(self._job.run)
        self._thread.start()

    def cancel(self) -> None:
        if self._token is not None:
            self._token.cancel()

    def shutdown(self, timeout_ms: int = _THREAD_QUIT_TIMEOUT_MS) -> bool:
        """Zatrzymuje trwający build i CZEKA na wątek. Do zamykania okna.

        Zwykłe `cancel()` nie wystarcza: zwraca sterowanie natychmiast, a Qt
        niszczy wtedy działający `QThread` (abort) i zostawia proces
        PyInstallera jako sierotę. Referencje kasujemy tylko wtedy, gdy wątek
        NAPRAWDĘ wyszedł — porzucenie działającego wątku byłoby tą samą awarią,
        przed którą ta metoda broni.
        """
        thread = self._thread
        if thread is None:
            return True
        self.cancel()
        thread.quit()
        if not thread.wait(timeout_ms):
            return False
        self._thread = None
        self._job = None
        return True

    def _on_done(self, result: BuildResult) -> None:
        """Sprzątanie wątku, potem sygnał w górę.

        Kolejność ma znaczenie w obie strony: `_thread` znika PRZED czekaniem,
        żeby `is_running()` mówiło prawdę już w slocie `finished` (okno wraca
        wtedy na ekran 1 i wolno mu zacząć następny build), a referencja na
        `_Job` znika DOPIERO po `wait()` — dopóki wątek nie wyszedł z pętli,
        emisja `finished` wciąż jest na jego stosie i skasowanie obiektu w
        środku tej emisji to sięganie po zwolnioną pamięć.
        """
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.quit()
            thread.wait(_THREAD_QUIT_TIMEOUT_MS)
        self._job = None
        self.finished.emit(result)
