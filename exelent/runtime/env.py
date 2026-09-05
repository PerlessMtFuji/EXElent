"""Izolowane środowisko, w którym uruchamiany jest PyInstaller.

uv robi trzy rzeczy: sprowadza przenośnego CPythona (z tkinterem — czego
oficjalny embeddable Python nie ma), tworzy venv i instaluje paczki.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from exelent.constants import PYINSTALLER_SPEC, TARGET_PYTHON
from exelent.diagnostics.patterns import explain_log
from exelent.models import Issue, IssueError, Severity
from exelent.runtime import Progress, ProgressFn
from exelent.runtime.bootstrap import ensure_uv
from exelent.runtime.paths import work_dir_for
from exelent.runtime.procs import CREATE_NO_WINDOW, kill_tree
from exelent.runtime.uvlog import DOWNLOAD_DONE, DOWNLOAD_START, PREPARED, parse_line

# Jak często sprawdzamy token przy anulowalnym wywołaniu uv. Wystarczająco
# gęsto, żeby zamykane okno nie czekało zauważalnie, i wystarczająco rzadko,
# żeby nie kręcić procesorem przez całą kilkuminutową instalację.
_CANCEL_POLL_SECONDS = 0.1


class BuildEnvError(IssueError):
    """Srodowisko builda nie powstalo.

    Bez tego wyjatku `create_build_env` oddawalo `BuildEnv` wygladajace na
    zdrowe, a awaria wychodzila cztery ramki dalej jako `FileNotFoundError
    [WinError 2]` z `Popen` — czyli w miejscu, ktore o przyczynie nie wie nic.
    """


@dataclass(frozen=True)
class BuildEnv:
    uv: Path
    venv: Path
    python: Path
    failed_packages: tuple[str, ...] = field(default_factory=tuple)


def run_uv(
    uv: Path, args: Sequence[str], *, cwd: Path | None = None, cancel=None
) -> subprocess.CompletedProcess[str]:
    """Uruchamia uv i czeka na wynik.

    `cancel` (cokolwiek z własnością `cancelled`) czyni to czekanie
    przerywalnym. Bez tego preflight liczący rozmiar pobierania nie ma jak
    zareagować na zamknięcie okna: `subprocess.run` wraca dopiero z uv, a Qt
    po swoim limicie niszczy wtedy działający wątek — czyli `abort()`
    i proces, który zostaje w systemie.
    """
    if cancel is None:
        return subprocess.run(
            [str(uv), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd else None,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    return _run_uv_cancellable(uv, args, cwd=cwd, cancel=cancel)


def _run_uv_cancellable(
    uv: Path, args: Sequence[str], *, cwd: Path | None, cancel
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        [str(uv), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        creationflags=CREATE_NO_WINDOW,
    )
    while True:
        try:
            stdout, stderr = process.communicate(timeout=_CANCEL_POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            if not cancel.cancelled:
                continue
            # uv sam uruchamia procesy potomne (pobieranie, rozpakowywanie),
            # więc samo `kill()` na nim zostawiłoby je osierocone.
            kill_tree(process.pid)
            stdout, stderr = process.communicate()
            break
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def _stream_uv(
    uv: Path,
    args: Sequence[str],
    on_line: Callable[[str], None],
    *,
    cwd: Path | None = None,
) -> tuple[int, str]:
    """Uruchamia uv i oddaje jego stderr linia po linii, na żywo.

    `subprocess.run(capture_output=True)` buforuje całe wyjście do zakończenia
    procesu — przy instalacji trwającej minuty oznaczało to pasek postępu,
    który stoi, a potem skacze na koniec.

    Pełny tekst i tak zbieramy: `explain_log` potrzebuje go w całości, bo błąd
    potrafi paść wcześnie i tylko odbić się echem na końcu.

    `--color never` to tania polisa. Zmierzone wyjście na potoku nie zawierało
    sekwencji ANSI, ale regex, który się o nie przewróci, psuje pasek w sposób
    trudny do zauważenia.

    `CREATE_NO_WINDOW` zostaje: bez niej użytkownikowi GUI mignie czarne okno
    konsoli przy każdym wywołaniu uv.
    """
    collected: list[str] = []
    process = subprocess.Popen(
        [str(uv), *args, "--color", "never"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        creationflags=CREATE_NO_WINDOW,
    )
    assert process.stderr is not None
    for line in process.stderr:
        collected.append(line.rstrip("\n"))
        on_line(line)
    process.wait()
    return process.returncode, "\n".join(collected)


class _DownloadTally:
    """Ile już pobrano, jak szybko i ile zostało.

    uv na potoku raportuje ZAKOŃCZENIE pobrania, nie bajty w locie, więc
    licznik rósłby skokami — przy paczce wielkości `torch` byłby to jeden skok
    po kilkunastu minutach stania. Dlatego w obrębie paczek trwających
    interpolujemy po zaobserwowanej prędkości, z przycięciem na 95% ich
    rozmiaru: pasek, który dobił do końca i stoi, kłamie bardziej niż pasek
    stojący w 95%.

    Suma pochodzi z PyPI, a nie z linii uv — ZMIERZONE: uv nie drukuje
    `Downloading` dla małych paczek, więc suma z linii byłaby zaniżona i pasek
    nigdy nie dobiłby do końca.
    """

    _INFLIGHT_CAP = 0.95
    _SMOOTHING = 0.3

    def __init__(self, total_bytes: int) -> None:
        self._total = total_bytes
        self._done = 0
        self._sizes: dict[str, int] = {}
        self._inflight: dict[str, float] = {}
        self._speed = 0.0
        self._started = time.monotonic()

    def reset(self, total_bytes: int) -> None:
        """Nowa suma dla nowego pobrania.

        Instalacja interpretera poznaje swoj rozmiar dopiero z linii uv, wiec
        licznik musi umiec przyjac sume PO utworzeniu. Wolanie `__init__`
        wprost byloby tym samym, tylko bez nazwy.
        """
        self._total = total_bytes
        self._done = 0
        self._sizes.clear()
        self._inflight.clear()
        self._speed = 0.0
        self._started = time.monotonic()

    def start(self, name: str, size_bytes: int) -> None:
        self._sizes[name] = size_bytes
        self._inflight[name] = time.monotonic()

    def finish(self, name: str) -> None:
        self._done += self._sizes.get(name, 0)
        self._inflight.pop(name, None)
        self._tick()

    def complete(self) -> None:
        """`Prepared N packages` — wszystkie pobrania skończone, cokolwiek
        naliczyliśmy po drodze."""
        self._done = self._total
        self._inflight.clear()

    def _tick(self) -> None:
        elapsed = time.monotonic() - self._started
        if elapsed <= 0:
            return
        instant = self._done / elapsed
        # Srednia wykladnicza: zerwane lacze ma byc widac jako spadek, a nie
        # jako stala sprzed minuty.
        self._speed = (
            instant
            if self._speed == 0.0
            else (self._SMOOTHING * instant + (1 - self._SMOOTHING) * self._speed)
        )

    def snapshot(self) -> tuple[int, int, float, float | None]:
        done = float(self._done)
        if self._speed > 0:
            for name, started in self._inflight.items():
                guessed = self._speed * (time.monotonic() - started)
                done += min(guessed, self._sizes.get(name, 0) * self._INFLIGHT_CAP)
        done = min(int(done), self._total) if self._total else int(done)
        remaining = max(self._total - done, 0)
        eta = remaining / self._speed if self._speed > 0 and self._total else None
        return done, self._total, self._speed, eta


def create_build_env(
    source: Path,
    packages: Sequence[str],
    progress: ProgressFn,
    *,
    python_version: str = TARGET_PYTHON,
    single_file: Path | None = None,
    total_download_bytes: int = 0,
) -> BuildEnv:
    uv = ensure_uv(progress)
    work = work_dir_for(source, single_file)
    venv = work / "venv"
    venv.parent.mkdir(parents=True, exist_ok=True)

    python_tally = _DownloadTally(0)

    def on_python_line(line: str) -> None:
        event = parse_line(line)
        if event is None:
            return
        if event.kind == DOWNLOAD_START:
            # Interpreter jest jednym pobraniem i uv podaje jego rozmiar
            # wprost — suma bierze się więc z tej linii, nie z PyPI.
            python_tally.reset(event.size_bytes)
            python_tally.start(event.name, event.size_bytes)
        elif event.kind == DOWNLOAD_DONE:
            python_tally.finish(event.name)
        done, total, speed, eta = python_tally.snapshot()
        progress(
            Progress(
                phase="install_python",
                fraction=0.3 * (done / total) if total else 0.0,
                done_bytes=done,
                total_bytes=total,
                speed_bps=speed,
                eta_s=eta,
            )
        )

    progress(Progress(phase="install_python", fraction=0.0))
    installed_code, installed_text = _stream_uv(
        uv, ["python", "install", python_version], on_python_line
    )

    progress(Progress(phase="create_env", fraction=0.3))
    created = run_uv(uv, ["venv", str(venv), "--python", python_version])
    if created.returncode != 0:
        raise _env_failure(installed_code, installed_text, created)

    python = venv / "Scripts" / "python.exe"

    progress(Progress(phase="install_packages", fraction=0.5))
    wanted = [PYINSTALLER_SPEC, *packages]
    tally = _DownloadTally(total_download_bytes)

    def on_line(line: str) -> None:
        event = parse_line(line)
        if event is None:
            return
        if event.kind == DOWNLOAD_START:
            tally.start(event.name, event.size_bytes)
        elif event.kind == DOWNLOAD_DONE:
            tally.finish(event.name)
        elif event.kind == PREPARED:
            tally.complete()
        done, total, speed, eta = tally.snapshot()
        fraction = 0.5 + 0.5 * (done / total) if total else 0.5
        progress(
            Progress(
                phase="install_packages",
                fraction=fraction,
                done_bytes=done,
                total_bytes=total,
                speed_bps=speed,
                eta_s=eta,
            )
        )

    returncode, _text = _stream_uv(
        uv, ["pip", "install", "--python", str(python), *wanted], on_line
    )

    failed: list[str] = []
    if returncode != 0:
        # Instalacja hurtowa padła — próbujemy pojedynczo, żeby jedna zła
        # nazwa paczki nie zabiła całego builda.
        for spec in wanted:
            single = run_uv(uv, ["pip", "install", "--python", str(python), spec])
            if single.returncode != 0:
                failed.append(spec)

    done, total, speed, _eta = tally.snapshot()
    progress(
        Progress(
            phase="install_packages",
            fraction=1.0,
            done_bytes=total or done,
            total_bytes=total,
            speed_bps=speed,
        )
    )
    return BuildEnv(uv=uv, venv=venv, python=python, failed_packages=tuple(failed))


def _env_failure(
    installed_code: int,
    installed_text: str,
    created: subprocess.CompletedProcess[str],
) -> BuildEnvError:
    """Zamienia porazke uv w Issue — z winnym krokiem i rozpoznana przyczyna.

    Winny jest krok PIERWSZY z tych, ktore padly: gdy interpreter nie zjechal
    na dysk, venv nie mial z czego powstac, a wskazanie "tworzenie srodowiska"
    wyslaloby uzytkownika w zla strone.

    Niezerowy kod z samego `uv python install` NIE jest tu powodem do
    przerwania — uv zwraca go takze wtedy, gdy zgodny Python juz jest w
    systemie, a venv powstaje wtedy bez problemu.

    Strumien bledow uv przechodzi przez `explain_log`, bo dokladnie te
    przyczyny z sekcji 8 specyfikacji (proxy z podmienionym certyfikatem,
    zapelniony dysk) sa tam nazwane wprost. Sam tekst uv nigdy nie trafia do
    uzytkownika: jest po angielsku i w zargonie narzedzia.
    """
    step = "install_python" if installed_code != 0 else "create_env"
    stderr = (created.stderr or "") + "\n" + (installed_text or "")
    cause = explain_log(stderr)
    return BuildEnvError(
        Issue("env_setup_failed", Severity.BLOCKER, {"step": step}),
        RuntimeError(f"uv zwrocilo {created.returncode}"),
        extra=cause,
    )
