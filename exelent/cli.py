"""CLI rdzenia — pełna ścieżka od katalogu do EXE bez GUI.

Istnieje po to, żeby logikę dało się testować i uruchamiać bez okna,
i dlatego, że rdzeń nie zależy od Qt.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from exelent.analysis.project import analyze_project
from exelent.build.backend import CancelToken
from exelent.build.pyinstaller import PyInstallerBackend
from exelent.build.workspace import materialize_workspace
from exelent.diagnostics.patterns import explain_log
from exelent.models import BuildResult, Issue, Severity
from exelent.planning import make_plan
from exelent.runtime import ProgressFn
from exelent.runtime.bootstrap import UvDownloadError, check_preconditions
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


def run_build(
    root: Path,
    progress: ProgressFn = _print_progress,
    cancel: CancelToken | None = None,
    **overrides,
) -> BuildResult:
    cancel = cancel or CancelToken()
    analysis = analyze_project(Path(root))

    blockers = tuple(i for i in analysis.issues if i.severity is Severity.BLOCKER)
    if blockers:
        return BuildResult(ok=False, issues=blockers)

    # Ostrzeżenia analizy (sekrety w kodzie, ciężkie paczki, niepewny plik
    # główny) są jedyną drogą, którą CLI może o nich powiedzieć — GUI pokazuje
    # je na ekranie 2, konsola nie ma takiego ekranu.
    carried = tuple(i for i in analysis.issues if i.severity is not Severity.BLOCKER)

    try:
        plan = make_plan(analysis, **overrides)
    except ValueError:
        # Nieosiągalne przy dzisiejszym `analyze_project` (brak kodu zawsze
        # daje BLOCKER powyżej), ale `make_plan` jest publiczne i wspólne z
        # GUI. Gdyby ta niepisana umowa kiedyś pękła, użytkownik ma zobaczyć
        # Issue, a nie traceback.
        return BuildResult(ok=False, issues=(*carried, Issue("no_entry_point", Severity.BLOCKER)))

    preconditions = check_preconditions(need_network=True)
    if preconditions:
        return BuildResult(ok=False, issues=(*carried, *preconditions))

    materialize_workspace(plan, analysis.converted)

    try:
        env = create_build_env(plan.root, plan.packages, progress)
    except UvDownloadError as exc:
        # `ensure_uv` niesie gotowe Issue właśnie po to — bez tego nieudane
        # pobranie uv kończy się tracebackiem na twarzy laika.
        return BuildResult(ok=False, issues=(*carried, exc.issue))

    carried += _packages_failed_issue(env.failed_packages)
    result = PyInstallerBackend().build(plan, env, progress, cancel)

    if not result.ok and result.log_path and result.log_path.exists():
        # Świadomie cały log, bez `tail()`: `explain_log` jest liniowe
        # (~0.017 s/MB, zmierzone w zadaniu 14), a obcięcie do ostatnich N
        # linii potrafiłoby ukryć błąd, który padł wcześnie i tylko odbił się
        # echem na końcu.
        log = result.log_path.read_text(encoding="utf-8", errors="replace")
        return replace(result, issues=(*carried, *result.issues, *explain_log(log)))

    return replace(result, issues=(*carried, *result.issues))


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

    print("\nBuild nie powiodl sie.", file=sys.stderr)
    _print_issues(result.issues, sys.stderr)
    if result.log_path:
        print(f"  log: {result.log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
