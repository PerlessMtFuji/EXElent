"""Isolated environment in which PyInstaller runs.

uv does three things: fetches a portable CPython (with tkinter — which the
official embeddable Python lacks), creates a venv and installs packages.
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

# How often we check the token during a cancellable uv call. Frequent enough
# that closing the window does not wait noticeably, and rare enough not to
# spin the CPU for the entire multi-minute installation.
_CANCEL_POLL_SECONDS = 0.1

# How long we wait for the process to exit after `kill_tree` and for the
# reader thread to join (B10). Same values as in `pyinstaller.py` — the
# bounded-cancellation-time contract is shared by both backends.
_KILL_WAIT_SECONDS = 3.0
_READER_JOIN_SECONDS = 1.0


class BuildEnvError(IssueError):
    """The build environment could not be created.

    Without this exception, `create_build_env` returned a seemingly healthy
    `BuildEnv`, and the failure surfaced four stack frames later as
    `FileNotFoundError [WinError 2]` from `Popen` — at a point that knows
    nothing about the cause.
    """


@dataclass(frozen=True)
class BuildEnv:
    uv: Path
    venv: Path
    python: Path
    failed_packages: tuple[str, ...] = field(default_factory=tuple)
    # B06: resolved versions of installed packages (name, version).
    # Enables reproduction of the problem; stored in the build report.
    resolved_versions: tuple[tuple[str, str], ...] = ()
    # B06: warnings about declared and installed version mismatches.
    version_issues: tuple[Issue, ...] = ()


def run_uv(
    uv: Path, args: Sequence[str], *, cwd: Path | None = None, cancel=None
) -> subprocess.CompletedProcess[str]:
    """Run uv and wait for the result.

    `cancel` (anything with a `cancelled` property) makes the wait
    interruptible. Without it, the preflight calculating download size cannot
    react when the window closes: `subprocess.run` returns only after uv, while
    Qt destroys the running thread after its deadline — calling `abort()` and
    leaving the process behind in the system.
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
            # uv spawns child processes itself (download, extraction), so
            # calling `kill()` on uv alone would leave them orphaned.
            kill_tree(process.pid)
            # B10: after kill_tree the pipe normally closes in a fraction of a
            # second, but if termination fails, an unbounded `communicate()`
            # waits for the process lifetime. Bound it so cancellation always
            # completes in finite time.
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
    """Run uv and stream its stderr line by line in real time.

    `subprocess.run(capture_output=True)` buffers all output until the process
    exits — for an installation lasting minutes, that meant a progress bar
    that stayed still and then jumped to the end.

    We still collect the full text: `explain_log` needs all of it because an
    error may occur early and only be echoed at the end.

    `cancel` (anything with a `cancelled` property) makes the wait
    interruptible: stderr is read on a separate thread, while the main loop
    polls the token on a short timer and — when cancelled — terminates uv's
    entire process tree (download/extraction are child processes). Without
    this, a multi-minute `torch` download cannot be interrupted and a closing
    window waits until it finishes.

    `--color never` is cheap insurance. The measured piped output contained no
    ANSI sequences, but a regex tripped up by them would break the progress
    bar in a way that is hard to notice.

    `CREATE_NO_WINDOW` stays: without it, a black console window flashes for
    GUI users on every uv invocation.
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

    # B10: after EOF or kill_tree — a finite wait. Without a timeout, `wait`
    # on a process that could not be terminated would block cancellation
    # forever.
    try:
        process.wait(timeout=_KILL_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    reader.join(timeout=_READER_JOIN_SECONDS)
    return process.returncode, "\n".join(collected)


class _DownloadTally:
    """How much has been downloaded, how fast, and how much remains.

    On a pipe, uv reports download COMPLETION rather than bytes in flight, so
    the counter would grow in jumps — for a package the size of `torch`, that
    would be one jump after many minutes of no movement. For active packages
    we therefore interpolate using the observed speed, capped at 95% of their
    size: a bar that reaches the end and stalls is more misleading than one
    that stalls at 95%.

    The total comes from PyPI rather than uv output — MEASURED: uv does not
    print `Downloading` for small packages, so a line-derived total would be
    understated and the bar would never reach the end.
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
        """Set a new total for a new download.

        The interpreter installation learns its size only from a uv line, so
        the counter must accept a total AFTER construction. Calling `__init__`
        directly would do the same thing without conveying the intent.
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
        """`Prepared N packages` — all downloads are complete, regardless of
        what was counted along the way."""
        self._done = self._total
        self._inflight.clear()

    def _tick(self) -> None:
        elapsed = time.monotonic() - self._started
        if elapsed <= 0:
            return
        instant = self._done / elapsed
        # Exponential average: a broken connection should show as a drop,
        # rather than a constant value from a minute ago.
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
    """B06: check whether installed versions match their declarations.

    This does not block the build — it is a warning. If uv installed a version
    outside the declared range (for example because a constraint narrowed it
    while the declaration was not updated), the user should know.
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
    """Cancellation during environment setup ends the build as CANCELLED, not failed.

    Raise IssueError with `build_cancelled` — the exception boundary in
    `execute_build` converts it into a cancellation result, just like an
    interruption in PyInstaller."""
    if cancel is not None and cancel.cancelled:
        raise IssueError(Issue("build_cancelled", Severity.INFO))


def _freeze_versions(
    uv: Path,
    python: Path,
    *,
    cancel=None,
) -> tuple[tuple[str, str], ...]:
    """B06: read installed package versions from the venv.

    `uv pip freeze` prints `name==version` lines. Parse them into (name,
    version) pairs and sort them alphabetically. A freeze failure does not
    block the build — return an empty tuple.
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
    supplemental_packages: Sequence[str] = (),
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
            # The interpreter is one download and uv reports its size directly,
            # so the total comes from this line rather than PyPI.
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
    # B05: when preserved manifests are available, pass them to uv via `-r`,
    # letting uv handle their full semantics itself (hashes, `-r`/`-c` paths,
    # indexes). PyInstaller is ALWAYS required and is not in the manifest, so
    # it is added as a separate spec. Imports detected outside the manifest are
    # also added explicitly. Without a manifest, fall back to the full list of
    # specifications from analysis.
    wanted = [PYINSTALLER_SPEC, *packages]
    install_args: list[str] = ["pip", "install", "--python", str(python)]
    if manifest_paths and workspace is not None:
        # The manifest and constraints preserve the requirement source's
        # semantics, while imports omitted from the manifest still participate
        # in the same resolution.
        install_args.extend((PYINSTALLER_SPEC, *supplemental_packages))
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
        # The BULK installation failed. Individual attempts are DIAGNOSTIC only
        # — they identify packages that cannot be installed at all (wrong name,
        # missing artifact). Their success does NOT prove readiness: when every
        # package installs alone but the full set does not, that is a CONFLICT
        # — individual installations merely overwrite one another's versions
        # and leave the environment inconsistent. The fallback is blocked
        # below while preserving the original resolution error (B06).
        for spec in wanted:
            _raise_if_cancelled(cancel)
            single = run_uv(uv, ["pip", "install", "--python", str(python), spec], cancel=cancel)
            if single.returncode != 0:
                failed.append(spec)
        if not failed:
            # The set has no common solution even though every package installs
            # separately. The environment after individual installs is
            # inconsistent, so do not build an EXE from it. Stop with the
            # original error.
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

    # B06: record resolved versions. `uv pip freeze` prints installed packages
    # as `name==version`; collect them so the build report can reproduce the
    # environment and explain the problem.
    resolved = _freeze_versions(uv, python, cancel=cancel)

    # B06: verify consistency between declared and installed versions.
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
    """The complete requirement set cannot be resolved together (conflicting
    pins or transitive dependencies), even though every package installs on
    its own. The environment produced by individual installations is
    inconsistent and does not prove readiness — block the build and carry the
    resolver's original error through `explain_log`, just like an environment
    setup failure (B06)."""
    return BuildEnvError(
        Issue("requirements_conflict", Severity.BLOCKER),
        RuntimeError("uv could not resolve the complete requirement set"),
        extra=explain_log(bulk_text),
    )


def _env_failure(
    installed_code: int,
    installed_text: str,
    created: subprocess.CompletedProcess[str],
) -> BuildEnvError:
    """Convert a uv failure into an Issue with the failed step and known cause.

    The culprit is the FIRST failed step: if the interpreter was not downloaded,
    the venv had nothing to build from, and blaming "environment creation"
    would send the user in the wrong direction.

    A non-zero code from `uv python install` alone is NOT a reason to stop — uv
    also returns it when a compatible Python is already available, in which
    case the venv is created successfully.

    uv's error stream passes through `explain_log` because the exact causes
    from specification section 8 (a proxy replacing certificates, a full disk)
    are named there explicitly. Raw uv text is never shown to the user: it is
    in English and uses tool-specific jargon.
    """
    step = "install_python" if installed_code != 0 else "create_env"
    stderr = (created.stderr or "") + "\n" + (installed_text or "")
    cause = explain_log(stderr)
    return BuildEnvError(
        Issue("env_setup_failed", Severity.BLOCKER, {"step": step}),
        RuntimeError(f"uv returned {created.returncode}"),
        extra=cause,
    )
