"""Core build service — the full path from plan to artifact.

GUI and CLI call `execute_build` with a ready plan. The core does not depend on
Qt or the console adapter: CLI provides a plan from analysis, GUI from screen 2.
The build backend (PyInstaller) is injected via a parameter.
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
from exelent.runtime.bootstrap import check_preconditions, uv_path
from exelent.runtime.env import create_build_env
from exelent.runtime.paths import next_build_seq

# How much of the progress bar the environment preparation takes (the rest is PyInstaller).
ENV_PROGRESS_SHARE = 0.3


def _default_progress(update: Progress) -> None:
    pass


class _Progress:
    """0..1 scale composed of two independent stages (env + backend).

    The value never decreases — a regressing bar is worse than a stalled one.
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
    """Converts an unexpected exception into an Issue with a code."""
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
    """Log of THIS build, if one was created."""
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
    """Builds EXACTLY the given plan. Shared core service for GUI and CLI.

    GUI passes a ready plan from screen 2; CLI assembles a plan from analysis
    and calls the same entry point. There is NO re-analysis of sources here —
    the build executes the plan.

    ``backend`` allows injecting an implementation (defaults to PyInstaller).
    ``carried`` carries warnings from earlier stages (analysis).
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
        # B06: the network is unconditionally needed only to download uv.
        # If uv is already cached we allow offline building — a missing
        # network will surface as a concrete package installation error
        # rather than a blanket "no internet" block. A complete uv cache
        # is sufficient to repeat a build without a connection.
        preconditions = check_preconditions(need_network=not uv_path().exists())
        if preconditions:
            return _fail(preconditions)

        log_owner = plan

        result = _build(plan, carried_issues, progress, cancel, backend)
    except IssueError as exc:
        return _fail(exc.issues)
    except Exception as exc:  # noqa: BLE001 - exception boundary
        return _fail(_unexpected_issues(exc))

    if result.ok and result.artifact is None:
        vanished = Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name})
        return replace(
            result,
            ok=False,
            issues=sort_issues((*carried_issues, *result.issues, vanished)),
            plan_id=plan.plan_id,
        )

    return replace(
        result,
        issues=sort_issues((*carried_issues, *result.issues)),
        plan_id=plan.plan_id,
    )


def _build(
    plan: BuildPlan,
    carried: list[Issue],
    progress: ProgressFn,
    cancel: CancelToken,
    backend: BuildBackend,
) -> BuildResult:
    """The actual build — called exclusively from within the exception boundary."""
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
        workspace=workspace,
        manifest_paths=plan.manifest_paths,
        constraint_paths=plan.constraint_paths,
        supplemental_packages=plan.supplemental_packages,
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

    # B06: version mismatch warnings go into the build warning pool.
    carried.extend(env.version_issues)

    result = backend.build(plan, env, scale.stage(ENV_PROGRESS_SHARE, 1.0), cancel)
    # B06: persist resolved versions in the build result.
    result = replace(result, resolved_versions=env.resolved_versions)

    if _was_cancelled(result):
        return result

    if not result.ok and result.log_path and result.log_path.exists():
        log = result.log_path.read_text(encoding="utf-8", errors="replace")
        return replace(result, issues=(*result.issues, *explain_log(log)))

    return result
