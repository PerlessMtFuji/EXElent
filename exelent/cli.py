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
from exelent.diagnostics.patterns import explain_log, sort_issues
from exelent.models import BuildPlan, BuildResult, Issue, IssueError, Severity
from exelent.planning import make_plan
from exelent.runtime import ProgressFn
from exelent.runtime.bootstrap import check_preconditions
from exelent.runtime.env import create_build_env


def _print_progress(phase: str, fraction: float) -> None:
    print(f"[{fraction * 100:5.1f}%] {phase}", flush=True)


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


def _os_error_signal(exc: OSError) -> str:
    """Wyjatek systemu w ksztalcie, ktory rozumie `explain_log`.

    Kod bledu Windows niesie gotowa diagnoze — nie ma powodu jej gubic tylko
    dlatego, ze przyszedl z kopiowania katalogu, a nie z logu PyInstallera.
    Tabela wzorcow w `diagnostics/patterns.py` jest pisana dokladnie na te
    napisy ("WinError 32", "Errno 28", "Access is denied").
    """
    parts = [f"[Errno {exc.errno}]" if exc.errno is not None else ""]
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        parts.append(f"[WinError {winerror}]")
    parts.append(str(exc.strerror or exc))
    parts.append(str(exc.filename or ""))
    return " ".join(part for part in parts if part)


def _unexpected_issues(exc: BaseException) -> tuple[Issue, ...]:
    """Ostatnia siatka bezpieczenstwa: cokolwiek to bylo, ma byc kodem."""
    if isinstance(exc, OSError):
        recognised = explain_log(_os_error_signal(exc))
        if recognised:
            return recognised
    return (Issue("unexpected_error", Severity.BLOCKER, {"error": type(exc).__name__}),)


def _existing_log(plan: BuildPlan | None) -> Path | None:
    """Log TEGO builda, o ile powstal.

    Stary log spod tej samej nazwy jest kasowany, gdy tylko plan jest znany
    (`_clear_stale_log`), wiec istnienie pliku znaczy "ten przebieg cos
    zapisal". Bez tego uzytkownik dolaczalby do zgloszenia log poprzedniej,
    zupelnie innej awarii.
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

    def _fail(issues: Sequence[Issue]) -> BuildResult:
        return BuildResult(
            ok=False,
            issues=sort_issues((*carried, *issues)),
            log_path=_existing_log(plan),
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

        try:
            plan = make_plan(analysis, **overrides)
        except ValueError:
            # Nieosiagalne przy dzisiejszym `analyze_project` (brak kodu zawsze
            # daje BLOCKER powyzej), ale `make_plan` jest publiczne i wspolne z
            # GUI. Gdyby ta niepisana umowa kiedys pekla, uzytkownik ma
            # zobaczyc Issue, a nie `ValueError`.
            return _fail((Issue("no_entry_point", Severity.BLOCKER),))

        _clear_stale_log(plan)

        preconditions = check_preconditions(need_network=True)
        if preconditions:
            return _fail(preconditions)

        result = _build(plan, analysis, carried, progress, cancel)
    except IssueError as exc:
        return _fail(exc.issues)
    except Exception as exc:  # noqa: BLE001 - to JEST granica, tu sie konczy stos
        return _fail(_unexpected_issues(exc))

    if result.ok and result.artifact is None:
        # Sprzecznosc, nie sukces: w gore poszedlby `BuildResult`, ktory mowi
        # "udalo sie", a nie ma czego pokazac. Zdejmujemy ja tutaj, zeby
        # warstwa prezentacji nie musiala wymyslac, co z takim czyms zrobic.
        return _fail((Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name}),))

    return replace(result, issues=sort_issues((*carried, *result.issues)))


def _build(
    plan,
    analysis,
    carried: list[Issue],
    progress: ProgressFn,
    cancel: CancelToken,
) -> BuildResult:
    """Wlasciwy build. Wolane wylacznie spod granicy wyjatkow w `run_build`."""
    materialize_workspace(plan, analysis.converted)

    env = create_build_env(plan.root, plan.packages, progress)
    carried.extend(_packages_failed_issue(env.failed_packages))

    result = PyInstallerBackend().build(plan, env, progress, cancel)

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
