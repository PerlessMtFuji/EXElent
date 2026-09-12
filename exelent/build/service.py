"""Usługa rdzenia budowania — pełna droga od planu do artefaktu.

GUI i CLI wołają `execute_build` z gotowym planem. Rdzeń nie zależy od Qt
ani od adaptera konsolowego: CLI dostarcza plan z analizy, GUI z ekranu 2.
Backend budujący (PyInstaller) jest wstrzykiwany przez parametr.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from exelent.build.backend import BuildBackend, CancelToken
from exelent.build.pyinstaller import PyInstallerBackend, log_path_for
from exelent.build.validate import validate_target_syntax
from exelent.build.workspace import materialize_workspace
from exelent.diagnostics.patterns import explain_log, filename_of, map_os_error, sort_issues
from exelent.models import BuildPlan, BuildResult, Issue, IssueError, Severity
from exelent.planning import is_cloud_synced
from exelent.runtime import Progress, ProgressFn
from exelent.runtime.bootstrap import check_preconditions
from exelent.runtime.env import create_build_env
from exelent.runtime.paths import next_build_seq

# Ile paska postępu zajmuje przygotowanie środowiska (reszta — PyInstaller).
ENV_PROGRESS_SHARE = 0.3


def _default_progress(update: Progress) -> None:
    pass


class _Progress:
    """Skala 0..1 sklejona z dwóch niezależnych (env + backend).

    Wartość nigdy nie maleje — cofający się pasek jest gorszy niż stojący.
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


def _unexpected_issues(exc: BaseException) -> tuple[Issue, ...]:
    """Zamienia nieoczekiwany wyjątek na Issue z kodem."""
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
    """Log TEGO builda, o ile powstał."""
    if plan is None:
        return None
    path = log_path_for(plan)
    with suppress(OSError):
        if path.exists():
            return path
    return None


def _was_cancelled(result: BuildResult) -> bool:
    return any(issue.code == "build_cancelled" for issue in result.issues)


def execute_build(
    plan: BuildPlan,
    progress: ProgressFn = _default_progress,
    cancel: CancelToken | None = None,
    *,
    carried: Sequence[Issue] = (),
    backend: BuildBackend | None = None,
) -> BuildResult:
    """Buduje DOKŁADNIE podany plan. Wspólna usługa rdzenia dla GUI i CLI.

    GUI przekazuje gotowy plan z ekranu 2; CLI składa plan z analizy i woła
    to samo. Tu NIE MA ponownej analizy źródeł — build wykonuje plan.

    ``backend`` pozwala wstrzyknąć implementację (domyślnie PyInstaller).
    ``carried`` to ostrzeżenia z wcześniejszych etapów (analiza).
    """
    cancel = cancel or CancelToken()
    next_build_seq()
    carried_issues: list[Issue] = list(carried)
    backend = backend or PyInstallerBackend()
    log_owner: BuildPlan | None = None

    def _fail(issues: Sequence[Issue]) -> BuildResult:
        return BuildResult(
            ok=False,
            issues=sort_issues((*carried_issues, *issues)),
            log_path=_existing_log(log_owner),
        )

    try:
        preconditions = check_preconditions(need_network=True)
        if preconditions:
            return _fail(preconditions)

        log_owner = plan

        result = _build(plan, carried_issues, progress, cancel, backend)
    except IssueError as exc:
        return _fail(exc.issues)
    except Exception as exc:  # noqa: BLE001 - granica wyjątków
        return _fail(_unexpected_issues(exc))

    if result.ok and result.artifact is None:
        vanished = Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name})
        return replace(
            result,
            ok=False,
            issues=sort_issues((*carried_issues, *result.issues, vanished)),
        )

    return replace(result, issues=sort_issues((*carried_issues, *result.issues)))


def _build(
    plan: BuildPlan,
    carried: list[Issue],
    progress: ProgressFn,
    cancel: CancelToken,
    backend: BuildBackend,
) -> BuildResult:
    """Właściwy build — wołane wyłącznie spod granicy wyjątków."""
    if cancel.cancelled:
        return BuildResult(ok=False, issues=(Issue("build_cancelled", Severity.INFO),))

    workspace = materialize_workspace(plan, cancel=cancel)

    if cancel.cancelled:
        return BuildResult(ok=False, issues=(Issue("build_cancelled", Severity.INFO),))

    scale = _Progress(progress)
    env = create_build_env(
        plan.root,
        plan.packages,
        scale.stage(0.0, ENV_PROGRESS_SHARE),
        python_version=plan.python_version,
        single_file=plan.single_file,
        total_download_bytes=plan.total_download_bytes,
        cancel=cancel,
    )
    if env.failed_packages:
        return BuildResult(
            ok=False,
            issues=(
                Issue(
                    "required_package_failed",
                    Severity.BLOCKER,
                    {"packages": ", ".join(env.failed_packages)},
                ),
            ),
        )

    syntax_issue = validate_target_syntax(
        env.python, workspace, python_version=plan.python_version, cancel=cancel
    )
    if syntax_issue is not None:
        return BuildResult(ok=False, issues=(syntax_issue,))

    result = backend.build(plan, env, scale.stage(ENV_PROGRESS_SHARE, 1.0), cancel)

    if _was_cancelled(result):
        return result

    if not result.ok and result.log_path and result.log_path.exists():
        log = result.log_path.read_text(encoding="utf-8", errors="replace")
        return replace(result, issues=(*result.issues, *explain_log(log)))

    return result
