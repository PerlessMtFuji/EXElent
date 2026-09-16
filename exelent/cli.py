"""CLI — console argument adapter and text output.

Build orchestration lives in `exelent.build.service`; this module is the
console entry point that assembles a plan from analysis and calls the
shared service.
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
    """Full path from DIRECTORY to EXE: analysis, plan, build.

    Convenience for console and tests — callers with a ready plan call `execute_build`.
    ``backend`` allows injecting a backend implementation (default: PyInstaller).
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
        # B07: asset collisions and other plan notes.
        carried.extend(plan.plan_issues)
        plan_blockers = tuple(i for i in plan.plan_issues if i.severity is Severity.BLOCKER)
        if plan_blockers:
            return BuildResult(ok=False, issues=sort_issues((*carried,)))
    except IssueError as exc:
        return BuildResult(ok=False, issues=sort_issues((*carried, *exc.issues)))
    except Exception as exc:  # noqa: BLE001 - exception boundary
        return BuildResult(ok=False, issues=sort_issues((*carried, *_unexpected_issues(exc))))

    return execute_build(plan, progress, cancel, carried=carried, backend=backend)


def _print_issues(issues: Sequence[Issue], stream) -> None:
    for issue in issues:
        detail = dict(issue.data)
        print(f"  - [{issue.severity.value}] {issue.code} {detail or ''}", file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    register_session()
    clean_stale_sessions()
    parser = argparse.ArgumentParser(prog="exelent", description="Build an EXE from a code folder")
    parser.add_argument("directory", type=Path, help="folder containing code files")
    parser.add_argument("--name", dest="exe_name", help="output file name")
    parser.add_argument("--icon", type=Path, help="icon file (.png, .jpg or .ico)")
    parser.add_argument("--out", dest="dest_dir", type=Path, help="destination directory")
    parser.add_argument("--report", type=Path, help="save result and notes as JSON")
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
            # B06: resolved package versions — enable environment reproduction.
            "resolved_versions": {name: version for name, version in result.resolved_versions},
            "verification": result.verification.value,
        }
        try:
            args.report.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"Cannot write report: {exc}", file=sys.stderr)
            return 1

    if result.ok and result.artifact:
        verified = result.verification.value == "passed"
        warned = any(i.severity is Severity.WARNING for i in result.issues)
        if verified and warned:
            outcome = "created with warnings; launch verified"
        elif verified:
            outcome = "created and launch verified"
        elif warned:
            outcome = "created with warnings; launch not verified"
        else:
            outcome = "created; launch not verified"
        print(f"\nDone ({outcome}): {result.artifact} ({result.size_bytes / 1024**2:.1f} MB)")
        if result.issues:
            print("Notes:", file=sys.stderr)
            _print_issues(result.issues, sys.stderr)
        return 0

    headline = (
        "\nBuild finished without an output file." if result.ok else "\nBuild failed."
    )
    print(headline, file=sys.stderr)
    _print_issues(result.issues, sys.stderr)
    if result.log_path:
        print(f"  log: {result.log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
