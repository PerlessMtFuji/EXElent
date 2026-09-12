"""Izolowane środowisko, w którym uruchamiany jest PyInstaller.

uv robi trzy rzeczy: sprowadza przenośnego CPythona (z tkinterem — czego
oficjalny embeddable Python nie ma), tworzy venv i instaluje paczki.
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

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

# Ile czekamy na zakończenie procesu po `kill_tree` i na dołączenie wątku
# czytającego (B10). Te same wartości co w `pyinstaller.py` — kontrakt
# ograniczonego czasu anulowania jest wspólny dla obu backendów.
_KILL_WAIT_SECONDS = 3.0
_READER_JOIN_SECONDS = 1.0


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
    # B06: rozstrzygnięte wersje zainstalowanych paczek (nazwa, wersja).
    # Umożliwia odtworzenie problemu; zapisywane w raporcie builda.
    resolved_versions: tuple[tuple[str, str], ...] = ()
    # B06: ostrzeżenia o niezgodności zadeklarowanych i zainstalowanych wersji.
    version_issues: tuple[Issue, ...] = ()


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
            # B10: po kill_tree potok zamyka się normalnie w ułamku sekundy,
            # ale gdy ubicie zawiodło, `communicate()` bez limitu czeka do
            # końca życia procesu. Ograniczamy to, żeby anulowanie zawsze
            # kończyło się w skończonym czasie.
            try:
                stdout, stderr = process.communicate(timeout=_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            break
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def _stream_uv(
    uv: Path,
    args: Sequence[str],
    on_line: Callable[[str], None],
    *,
    cwd: Path | None = None,
    cancel=None,
) -> tuple[int, str]:
    """Uruchamia uv i oddaje jego stderr linia po linii, na żywo.

    `subprocess.run(capture_output=True)` buforuje całe wyjście do zakończenia
    procesu — przy instalacji trwającej minuty oznaczało to pasek postępu,
    który stoi, a potem skacze na koniec.

    Pełny tekst i tak zbieramy: `explain_log` potrzebuje go w całości, bo błąd
    potrafi paść wcześnie i tylko odbić się echem na końcu.

    `cancel` (cokolwiek z własnością `cancelled`) czyni to czekanie
    przerywalnym: stderr czytamy na osobnym wątku, a pętla główna odpytuje
    token na krótkim timerze i — gdy anulowano — ubija całe drzewo procesów uv
    (pobieranie/rozpakowywanie to jego procesy potomne). Bez tego kilkuminutowe
    pobranie `torch` nie da się przerwać, a zamykane okno czeka aż do końca.

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

    if cancel is None:
        for line in process.stderr:
            collected.append(line.rstrip("\n"))
            on_line(line)
        process.wait()
        return process.returncode, "\n".join(collected)

    output_queue: queue.Queue[str | None] = queue.Queue()

    def _pump(stderr: object) -> None:
        try:
            for line in stderr:  # type: ignore[attr-defined]
                output_queue.put(line)
        finally:
            output_queue.put(None)  # sentinel: stderr closed

    reader = threading.Thread(target=_pump, args=(process.stderr,), daemon=True)
    reader.start()

    while True:
        if cancel.cancelled:
            kill_tree(process.pid)
            break
        try:
            line = output_queue.get(timeout=_CANCEL_POLL_SECONDS)
        except queue.Empty:
            continue
        if line is None:
            break
        collected.append(line.rstrip("\n"))
        on_line(line)

    # B10: po EOF lub kill_tree — skończony czas oczekiwania. Bez limitu
    # `wait` wisząc na procesie, którego nie udało się ubić, blokowałby
    # powrót z anulowania w nieskończoność.
    try:
        process.wait(timeout=_KILL_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    reader.join(timeout=_READER_JOIN_SECONDS)
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


def _check_version_consistency(
    resolved: tuple[tuple[str, str], ...],
    packages: Sequence[str],
) -> tuple[Issue, ...]:
    """B06: sprawdza, czy zainstalowane wersje zgadzają się z deklarowanymi.

    Nie blokuje builda — to ostrzeżenie. Jeśli uv zainstalowało wersję spoza
    zadeklarowanego zakresu (bo np. constraint ją ograniczył, a deklaracja nie
    została zaktualizowana), użytkownik powinien o tym wiedzieć.
    """
    installed = {canonicalize_name(name): ver for name, ver in resolved}
    issues: list[Issue] = []
    for spec in packages:
        try:
            req = Requirement(spec)
        except InvalidRequirement:
            continue
        canon = canonicalize_name(req.name)
        ver = installed.get(canon)
        if ver is None:
            continue
        if req.specifier and not req.specifier.contains(ver, prereleases=True):
            issues.append(
                Issue(
                    "version_mismatch",
                    Severity.WARNING,
                    {"package": req.name, "declared": str(req.specifier), "installed": ver},
                )
            )
    return tuple(issues)


def _raise_if_cancelled(cancel) -> None:
    """Anulowanie na etapie srodowiska konczy build jako PRZERWANY, nie blad.

    Rzucamy IssueError z `build_cancelled` — granica wyjatkow w `execute_build`
    zamienia go na wynik anulowania, dokladnie jak przerwanie w PyInstallerze."""
    if cancel is not None and cancel.cancelled:
        raise IssueError(Issue("build_cancelled", Severity.INFO))


def _freeze_versions(
    uv: Path,
    python: Path,
    *,
    cancel=None,
) -> tuple[tuple[str, str], ...]:
    """B06: odczytuje zainstalowane wersje paczek z venv.

    `uv pip freeze` drukuje linie `name==version`. Parsujemy je do par
    (nazwa, wersja) i sortujemy alfabetycznie. Błąd freeze nie blokuje
    builda — zwracamy pustą krotkę.
    """
    result = run_uv(uv, ["pip", "freeze", "--python", str(python)], cancel=cancel)
    if result.returncode != 0:
        return ()
    versions: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if "==" in line:
            name, _, version = line.partition("==")
            versions.append((name.strip(), version.strip()))
    versions.sort(key=lambda nv: nv[0].lower())
    return tuple(versions)


def create_build_env(
    source: Path,
    packages: Sequence[str],
    progress: ProgressFn,
    *,
    python_version: str = TARGET_PYTHON,
    single_file: Path | None = None,
    total_download_bytes: int = 0,
    cancel=None,
    workspace: Path | None = None,
    manifest_paths: Sequence[str] = (),
    constraint_paths: Sequence[str] = (),
) -> BuildEnv:
    uv = ensure_uv(progress, cancel=cancel)
    _raise_if_cancelled(cancel)
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
        uv, ["python", "install", python_version], on_python_line, cancel=cancel
    )
    _raise_if_cancelled(cancel)

    progress(Progress(phase="create_env", fraction=0.3))
    created = run_uv(uv, ["venv", str(venv), "--python", python_version], cancel=cancel)
    _raise_if_cancelled(cancel)
    if created.returncode != 0:
        raise _env_failure(installed_code, installed_text, created)

    python = venv / "Scripts" / "python.exe"

    progress(Progress(phase="install_packages", fraction=0.5))
    # B05: gdy mamy zachowane manifesty, przekazujemy je do uv przez `-r`,
    # dzięki czemu uv samodzielnie obsługuje pełną semantykę (hashowanie,
    # ścieżki `-r`/`-c`, indeks). PyInstaller jest ZAWSZE potrzebny i nie
    # leży w manifeście, więc dochodzi jako oddzielny spec. Gdy manifestu
    # nie ma, wracamy do listy specyfikacji z analizy.
    wanted = [PYINSTALLER_SPEC, *packages]
    install_args: list[str] = ["pip", "install", "--python", str(python)]
    if manifest_paths and workspace is not None:
        # Manifest + constraint → argumenty `-r`/`-c` zamiast gołych nazw.
        # PyInstaller wchodzi jawnie na początku; reszta przez manifest.
        install_args.append(PYINSTALLER_SPEC)
        for rel in manifest_paths:
            install_args += ["-r", str(workspace / rel)]
        for rel in constraint_paths:
            install_args += ["-c", str(workspace / rel)]
    else:
        install_args.extend(wanted)
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

    returncode, bulk_text = _stream_uv(uv, install_args, on_line, cancel=cancel)
    _raise_if_cancelled(cancel)

    failed: list[str] = []
    if returncode != 0:
        # Instalacja HURTOWA padła. Próba pojedyncza jest tu wyłącznie
        # DIAGNOSTYKĄ — wskazuje paczki, których w ogóle nie da się zainstalować
        # (zła nazwa, brak artefaktu). Jej powodzenie NIE jest dowodem
        # gotowości: gdy każda paczka instaluje się osobno, a cały zestaw nie,
        # to KONFLIKT — pojedyncze instalacje tylko nadpisują nawzajem swoje
        # wersje i zostawiają środowisko niespójne. Taki fallback blokujemy
        # niżej, niosąc pierwotny błąd rozwiązania (B06).
        for spec in wanted:
            _raise_if_cancelled(cancel)
            single = run_uv(uv, ["pip", "install", "--python", str(python), spec], cancel=cancel)
            if single.returncode != 0:
                failed.append(spec)
        if not failed:
            # Zestaw nie ma wspólnego rozwiązania, choć każda paczka wchodzi
            # osobno. Środowisko po pojedynczych instalacjach jest niespójne —
            # nie budujemy z niego EXE. Zatrzymujemy się z pierwotnym błędem.
            raise _requirements_conflict(bulk_text)

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

    # B06: utrwalenie rozstrzygniętych wersji. `uv pip freeze` drukuje
    # zainstalowane paczki w formacie `name==version` — zbieramy je, żeby
    # raport builda pozwalał odtworzyć środowisko i wyjaśnić problem.
    resolved = _freeze_versions(uv, python, cancel=cancel)

    # B06: sprawdzenie spójności zadeklarowanych i zainstalowanych wersji.
    version_issues = _check_version_consistency(resolved, packages)

    return BuildEnv(
        uv=uv,
        venv=venv,
        python=python,
        failed_packages=tuple(failed),
        resolved_versions=resolved,
        version_issues=version_issues,
    )


def _requirements_conflict(bulk_text: str) -> BuildEnvError:
    """Cały zestaw wymagań nie da się rozwiązać razem (sprzeczne piny lub
    zależności przechodnie), choć każda paczka wchodzi osobno. Powstałe po
    pojedynczych instalacjach środowisko jest niespójne i nie jest dowodem
    gotowości — blokujemy build, niosąc pierwotny błąd resolvera przez
    `explain_log`, tak jak przy awarii środowiska (B06)."""
    return BuildEnvError(
        Issue("requirements_conflict", Severity.BLOCKER),
        RuntimeError("uv nie rozwiazalo pelnego zestawu wymagan"),
        extra=explain_log(bulk_text),
    )


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
