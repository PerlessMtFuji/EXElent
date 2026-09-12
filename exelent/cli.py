"""CLI — adapter argumentów konsolowych i wyniku tekstowego.

Orkiestracja budowania mieszka w `exelent.build.service`; ten moduł jest
wejściem konsolowym, które składa plan z analizy i woła wspólną usługę.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from exelent.analysis.project import analyze_project
from exelent.build.backend import CancelToken
from exelent.build.service import _unexpected_issues, execute_build
from exelent.diagnostics.patterns import sort_issues
from exelent.models import BuildResult, Issue, IssueError, Severity
from exelent.planning import make_plan
from exelent.runtime import Progress, ProgressFn
from exelent.runtime.paths import clean_stale_sessions, register_session


def _print_progress(update: Progress) -> None:
    print(f"[{update.fraction * 100:5.1f}%] {update.phase}", flush=True)


def run_build(
    root: Path,
    progress: ProgressFn = _print_progress,
    cancel: CancelToken | None = None,
    *,
    backend=None,
    **overrides,
) -> BuildResult:
    """Pełna droga z KATALOGU do EXE: analiza, plan, build.

    Wygoda dla konsoli i testów — kto ma gotowy plan, woła `execute_build`.
    ``backend`` pozwala wstrzyknąć implementację backendu (domyślnie PyInstaller).
    """
    cancel = cancel or CancelToken()
    carried: list[Issue] = []

    try:
        analysis = analyze_project(Path(root))
        carried.extend(i for i in analysis.issues if i.severity is not Severity.BLOCKER)

        blockers = tuple(i for i in analysis.issues if i.severity is Severity.BLOCKER)
        if blockers:
            return BuildResult(ok=False, issues=sort_issues((*carried, *blockers)))

        if (overrides.get("entry") or analysis.entry) is None:
            return BuildResult(
                ok=False,
                issues=sort_issues((*carried, Issue("no_entry_point", Severity.BLOCKER))),
            )

        plan = make_plan(analysis, **overrides)
        # B07: kolizje zasobów i inne uwagi planu.
        carried.extend(plan.plan_issues)
        plan_blockers = tuple(i for i in plan.plan_issues if i.severity is Severity.BLOCKER)
        if plan_blockers:
            return BuildResult(ok=False, issues=sort_issues((*carried,)))
    except IssueError as exc:
        return BuildResult(ok=False, issues=sort_issues((*carried, *exc.issues)))
    except Exception as exc:  # noqa: BLE001 - granica wyjątków
        return BuildResult(ok=False, issues=sort_issues((*carried, *_unexpected_issues(exc))))

    return execute_build(plan, progress, cancel, carried=carried, backend=backend)


def _print_issues(issues: Sequence[Issue], stream) -> None:
    for issue in issues:
        detail = dict(issue.data)
        print(f"  - [{issue.severity.value}] {issue.code} {detail or ''}", file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    register_session()
    clean_stale_sessions()
    parser = argparse.ArgumentParser(prog="exelent", description="Zrob EXE z katalogu z kodem")
    parser.add_argument("directory", type=Path, help="katalog z plikami kodu")
    parser.add_argument("--name", dest="exe_name", help="nazwa pliku wynikowego")
    parser.add_argument("--icon", type=Path, help="plik ikony (.png, .jpg lub .ico)")
    parser.add_argument("--out", dest="dest_dir", type=Path, help="katalog docelowy")
    parser.add_argument("--report", type=Path, help="zapisz wynik i uwagi jako JSON")
    args = parser.parse_args(argv)

    overrides = {
        k: v for k, v in vars(args).items() if k not in {"directory", "report"} and v is not None
    }
    result = run_build(args.directory, **overrides)

    if args.report is not None:
        payload = {
            "ok": result.ok,
            "artifact": str(result.artifact) if result.artifact else None,
            "executable_path": str(result.executable_path) if result.executable_path else None,
            "size_bytes": result.size_bytes,
            "log_path": str(result.log_path) if result.log_path else None,
            "issues": [
                {"code": i.code, "severity": i.severity.value, "data": dict(i.data)}
                for i in result.issues
            ],
        }
        try:
            args.report.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"Nie mozna zapisac raportu: {exc}", file=sys.stderr)
            return 1

    if result.ok and result.artifact:
        print(f"\nGotowe: {result.artifact} ({result.size_bytes / 1024**2:.1f} MB)")
        if result.issues:
            print("Uwagi:", file=sys.stderr)
            _print_issues(result.issues, sys.stderr)
        return 0

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
