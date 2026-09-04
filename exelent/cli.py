"""CLI rdzenia — pełna ścieżka od katalogu do EXE bez GUI.

Istnieje po to, żeby logikę dało się testować i uruchamiać bez okna,
i dlatego, że rdzeń nie zależy od Qt.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from exelent.analysis.project import analyze_project
from exelent.build.backend import CancelToken
from exelent.build.pyinstaller import PyInstallerBackend, log_path_for
from exelent.build.workspace import materialize_workspace
from exelent.diagnostics.patterns import explain_log, filename_of, map_os_error, sort_issues
from exelent.models import BuildPlan, BuildResult, Issue, IssueError, Severity
from exelent.planning import is_cloud_synced, make_plan
from exelent.runtime import Progress, ProgressFn
from exelent.runtime.bootstrap import check_preconditions
from exelent.runtime.env import create_build_env


def _print_progress(update: Progress) -> None:
    print(f"[{update.fraction * 100:5.1f}%] {update.phase}", flush=True)


# Ile paska zajmuje przygotowanie środowiska. Reszta należy do PyInstallera,
# bo to on trwa najdłużej.
ENV_PROGRESS_SHARE = 0.3


class _Progress:
    """Jedna skala 0..1 dla całej drogi, sklejona z dwóch niezależnych.

    `create_build_env` liczy swoje 0..1 i `PyInstallerBackend` swoje — obie
    słusznie, bo żadna nie wie o istnieniu drugiej. Bez sklejenia pasek
    postępu dochodzi do 100% po zainstalowaniu paczek i zaczyna od nowa od
    20% (zmierzone na żywym buildzie), czyli mówi użytkownikowi, że program
    stracił dotychczasową pracę.

    Wartość nigdy nie maleje: PyInstaller wraca do fazy „Analyzing" po
    „Processing module hooks", więc nawet w obrębie jednej skali kolejność
    komunikatów nie jest rosnąca. Cofający się pasek jest gorszy niż stojący.
    """

    def __init__(self, report: ProgressFn) -> None:
        self._report = report
        self._highest = 0.0

    def stage(self, start: float, end: float) -> ProgressFn:
        def report(update: Progress) -> None:
            value = start + (end - start) * min(max(update.fraction, 0.0), 1.0)
            self._highest = max(self._highest, value)
            self._report(replace(update, fraction=self._highest))

        return report


def _packages_failed_issue(failed: Sequence[str]) -> tuple[Issue, ...]:
    """Częściowa instalacja zależności musi dotrzeć do użytkownika.

    `create_build_env` próbuje instalować paczki pojedynczo, gdy instalacja
    hurtowa padnie — jedna zła nazwa nie zabija wtedy całego builda. Cena jest
    taka, że EXE potrafi się zbudować bez biblioteki, której kod używa, i
    wywalić się dopiero u odbiorcy z `ModuleNotFoundError`. Ostrzeżenie z
    nazwami paczek zamienia tamten zagadkowy błąd w informację podaną z góry.
    """
    if not failed:
        return ()
    return (Issue("packages_failed", Severity.WARNING, {"packages": ", ".join(failed)}),)


def _unexpected_issues(exc: BaseException) -> tuple[Issue, ...]:
    """Ostatnia siatka bezpieczenstwa: cokolwiek to bylo, ma byc kodem.

    Wyjatek idzie przez `map_os_error`, a NIE przez `explain_log`. Tamta
    tabela opisuje log PyInstallera i ma w sobie pewne siebie ramie
    antywirusowe, ktore dla artefaktu w `dist` jest sluszne, a dla pliku
    zrodlowego uzytkownika bylo by bledna rada: plik z OneDrive daje przy
    odczycie ten sam WinError 1920, a laik po takiej podpowiedzi wylacza
    antywirusa i nic sie nie zmienia.
    """
    if isinstance(exc, OSError):
        in_cloud = False
        filename = filename_of(exc)
        if filename:
            with suppress(OSError, ValueError):
                in_cloud = is_cloud_synced(Path(filename))
        recognised = map_os_error(exc, in_cloud=in_cloud)
        if recognised:
            return recognised
    return (Issue("unexpected_error", Severity.BLOCKER, {"error": type(exc).__name__}),)


def _existing_log(plan: BuildPlan | None) -> Path | None:
    """Log TEGO builda, o ile powstal.

    `plan` przychodzi tu dopiero, gdy ten przebieg skasowal stary log
    (`_clear_stale_log`) — od tego momentu istnienie pliku znaczy "ten
    przebieg cos zapisal". Wczesniej plan bywa juz policzony, ale log pod ta
    sciezka nalezy jeszcze do POPRZEDNIEGO przebiegu: dolaczony do zgloszenia
    opisywalby zupelnie inna awarie, a zadanie 20 podpina pod `log_path`
    przycisk "Zapisz raport".
    """
    if plan is None:
        return None
    path = log_path_for(plan)
    with suppress(OSError):
        if path.exists():
            return path
    return None


def _clear_stale_log(plan: BuildPlan) -> None:
    with suppress(OSError):
        log_path_for(plan).unlink(missing_ok=True)


def run_build(
    root: Path,
    progress: ProgressFn = _print_progress,
    cancel: CancelToken | None = None,
    **overrides,
) -> BuildResult:
    cancel = cancel or CancelToken()

    # Ostrzezenia analizy (sekrety w kodzie, ciezkie paczki, niepewny plik
    # glowny) sa jedyna droga, ktora CLI moze o nich powiedziec — GUI pokazuje
    # je na ekranie 2, konsola nie ma takiego ekranu. Lista jest mutowalna, bo
    # rosnie po drodze: to, co juz wiadomo, ma przetrwac kazda pozniejsza
    # awarie, lacznie z ta na sciezce BLOCKERa analizy.
    carried: list[Issue] = []
    plan: BuildPlan | None = None
    # Plan, ktorego log NALEZY do tego przebiegu. Osobno od `plan`, bo miedzy
    # policzeniem planu a skasowaniem starego logu jest okno (warunki wstepne),
    # w ktorym pod ta sciezka lezy jeszcze log poprzedniego przebiegu.
    log_owner: BuildPlan | None = None

    def _fail(issues: Sequence[Issue]) -> BuildResult:
        return BuildResult(
            ok=False,
            issues=sort_issues((*carried, *issues)),
            log_path=_existing_log(log_owner),
        )

    # JEDNA granica wyjatkow na CALA droge, nie tylko na sam build. Runda 1
    # domknela build, ale `analyze_project` stoi przed nim i czyta kazdy plik
    # uzytkownika bez straznika — jeden plik z odmowa ACL albo dostepny tylko
    # w chmurze konczyl sie surowym tracebackiem. Tak samo `make_plan` (sonda
    # zapisywalnosci, wywolanie Win32, `TypeError` na literowce w nazwie opcji
    # podanej przez GUI) i `check_preconditions` (`shutil.disk_usage`).
    try:
        analysis = analyze_project(Path(root))
        carried.extend(i for i in analysis.issues if i.severity is not Severity.BLOCKER)

        blockers = tuple(i for i in analysis.issues if i.severity is Severity.BLOCKER)
        if blockers:
            return _fail(blockers)

        # Brak pliku glownego sprawdzamy TUTAJ, a nie lapiac `ValueError` z
        # `make_plan`. Diagnoza po typie wyjatku byla mina: `make_plan` robi
        # dzis sonde zapisywalnosci na wielu kandydatach i wywolanie Win32,
        # wiec kazdy przyszly `ValueError` z tego I/O nazwalby sie
        # "nie znaleziono pliku glownego". Teraz taki blad idzie do ogolnego
        # ramienia i dostaje uczciwe `unexpected_error`.
        if (overrides.get("entry") or analysis.entry) is None:
            return _fail((Issue("no_entry_point", Severity.BLOCKER),))

        plan = make_plan(analysis, **overrides)

        preconditions = check_preconditions(need_network=True)
        if preconditions:
            return _fail(preconditions)

        # Kasowanie starego logu dopiero TUTAJ: od tego miejsca naprawde
        # budujemy, wiec "log istnieje" znaczy "ten przebieg go zapisal".
        # Wczesniej robil to kazdy przebieg, takze taki, ktory odpadal na
        # braku internetu i nie mial czym tamtego logu zastapic.
        _clear_stale_log(plan)
        log_owner = plan

        result = _build(plan, analysis, carried, progress, cancel)
    except IssueError as exc:
        return _fail(exc.issues)
    except Exception as exc:  # noqa: BLE001 - to JEST granica, tu sie konczy stos
        return _fail(_unexpected_issues(exc))

    if result.ok and result.artifact is None:
        # Sprzecznosc, nie sukces: w gore poszedlby `BuildResult`, ktory mowi
        # "udalo sie", a nie ma czego pokazac. Zdejmujemy ja tutaj, zeby
        # warstwa prezentacji nie musiala wymyslac, co z takim czyms zrobic.
        # Reszta wyniku ZOSTAJE: backend zna czas trwania, sciezke logu i
        # czasem wlasne Issue mowiace, dlaczego artefaktu nie ma.
        vanished = Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name})
        return replace(
            result,
            ok=False,
            issues=sort_issues((*carried, *result.issues, vanished)),
        )

    return replace(result, issues=sort_issues((*carried, *result.issues)))


def _was_cancelled(result: BuildResult) -> bool:
    return any(issue.code == "build_cancelled" for issue in result.issues)


def _build(
    plan,
    analysis,
    carried: list[Issue],
    progress: ProgressFn,
    cancel: CancelToken,
) -> BuildResult:
    """Wlasciwy build. Wolane wylacznie spod granicy wyjatkow w `run_build`."""
    materialize_workspace(plan, analysis.converted)

    scale = _Progress(progress)
    env = create_build_env(
        plan.root,
        plan.packages,
        scale.stage(0.0, ENV_PROGRESS_SHARE),
        single_file=plan.single_file,
        total_download_bytes=plan.total_download_bytes,
    )
    carried.extend(_packages_failed_issue(env.failed_packages))

    result = PyInstallerBackend().build(plan, env, scale.stage(ENV_PROGRESS_SHARE, 1.0), cancel)

    if _was_cancelled(result):
        # Log anulowanego builda urywa sie tam, gdzie uzytkownik nacisnal
        # przycisk — w polowie kroku, czesto w polowie zdania. `explain_log`
        # dopasowalby wzorce do tego urwanego tekstu i opisal awarie, ktora
        # nigdy nie nastapila; przerwanie ma zostac przerwaniem.
        return result

    if not result.ok and result.log_path and result.log_path.exists():
        # Swiadomie caly log, bez `tail()`: `explain_log` jest liniowe
        # (~0.017 s/MB, zmierzone w zadaniu 14), a obciecie do ostatnich N
        # linii potrafiloby ukryc blad, ktory padl wczesnie i tylko odbil sie
        # echem na koncu.
        log = result.log_path.read_text(encoding="utf-8", errors="replace")
        return replace(result, issues=(*result.issues, *explain_log(log)))

    return result


def _print_issues(issues: Sequence[Issue], stream) -> None:
    for issue in issues:
        detail = dict(issue.data)
        print(f"  - [{issue.severity.value}] {issue.code} {detail or ''}", file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exelent", description="Zrob EXE z katalogu z kodem")
    parser.add_argument("directory", type=Path, help="katalog z plikami kodu")
    parser.add_argument("--name", dest="exe_name", help="nazwa pliku wynikowego")
    parser.add_argument("--icon", type=Path, help="plik ikony (.png, .jpg lub .ico)")
    parser.add_argument("--out", dest="dest_dir", type=Path, help="katalog docelowy")
    args = parser.parse_args(argv)

    overrides = {k: v for k, v in vars(args).items() if k != "directory" and v is not None}
    result = run_build(args.directory, **overrides)

    if result.ok and result.artifact:
        print(f"\nGotowe: {result.artifact} ({result.size_bytes / 1024**2:.1f} MB)")
        if result.issues:
            print("Uwagi:", file=sys.stderr)
            _print_issues(result.issues, sys.stderr)
        return 0

    # `run_build` zdejmuje ta sprzecznosc u zrodla, ale `main` drukuje to, co
    # dostalo — a "Build nie powiodl sie" przy `ok=True` bylo mina dla kazdego,
    # kto kiedys poda tu wynik z innego miejsca.
    headline = (
        "\nBuild zakonczyl sie bez pliku wynikowego." if result.ok else "\nBuild nie powiodl sie."
    )
    print(headline, file=sys.stderr)
    _print_issues(result.issues, sys.stderr)
    if result.log_path:
        print(f"  log: {result.log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
