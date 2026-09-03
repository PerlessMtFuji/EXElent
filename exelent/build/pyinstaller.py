"""Backend PyInstallera: składa argumenty, prowadzi podproces i tłumaczy
jego log na fazy paska postępu."""

from __future__ import annotations

import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from exelent.build.backend import CancelToken
from exelent.build.icon import ensure_ico
from exelent.build.launcher import LAUNCHER_FILENAME, render_launcher
from exelent.build.workspace import workspace_for
from exelent.models import AppKind, BuildPlan, BuildResult, Issue, OutputMode, Severity
from exelent.runtime import Progress, ProgressFn
from exelent.runtime.env import CREATE_NO_WINDOW, BuildEnv
from exelent.runtime.paths import logs_dir, path_hash

PHASES: dict[str, str] = {
    r"Analyzing": "analyze",
    r"Processing module hooks": "hooks",
    r"Looking for dynamic libraries": "libraries",
    r"Building PKG": "package",
    r"Building EXE": "package",
    r"Building COLLECT": "collect",
}

_PHASE_PROGRESS = {
    "analyze": 0.35,
    "hooks": 0.55,
    "libraries": 0.70,
    "package": 0.88,
    "collect": 0.95,
}

# PyInstaller's --add-data separator between "source" and "dest in bundle"
# is ';' on Windows and ':' elsewhere. EXElent only ever runs on Windows
# (see global constraints), so this is a fixed constant rather than a
# platform check or a one-line function pretending otherwise.
_ADD_DATA_SEPARATOR = ";"

# How often the cancel token is polled while waiting for subprocess output.
# PyInstaller can go silent for long stretches (archive writing, antivirus
# scanning the freshly written EXE) -- the cancel check must run on a timer,
# not once per emitted log line, or Cancel looks dead during those silences.
_CANCEL_POLL_SECONDS = 0.2

# Bound on how long we wait for the process to actually exit after taskkill,
# and on joining the stdout-reader thread, once a cancel has been requested.
# taskkill on Windows normally finishes in well under a second; a few
# seconds is generous headroom for a slow-but-dying process while still
# being short enough that a person watching the screen does not conclude
# the whole program is frozen. If the child is genuinely unkillable, build()
# must still return within this bound rather than hang forever -- see
# cancel_incomplete below.
_CANCEL_KILL_WAIT_SECONDS = 3.0
_CANCEL_READER_JOIN_SECONDS = 1.0


def build_arguments(
    plan: BuildPlan, workspace: Path, launcher: Path, icon: Path | None
) -> list[str]:
    args = [
        "--noconfirm",
        "--clean",
        "--noupx",
        "--distpath",
        str(workspace / "dist"),
        "--workpath",
        str(workspace / "build"),
        "--specpath",
        str(workspace),
        "--paths",
        str(workspace),
        "--name",
        plan.exe_name,
    ]
    args.append("--onefile" if plan.output_mode is OutputMode.ONEFILE else "--onedir")
    args.append("--windowed" if plan.app_kind is AppKind.WINDOWED else "--console")

    for module in (plan.entry.stem, *plan.hidden_imports):
        args += ["--hidden-import", module]

    for data in plan.data_files:
        # Data files must point at the workspace copy, not the user's
        # original folder: the whole point of the workspace is that the
        # build never reads from (or writes into) the user's directory.
        workspace_data = workspace / data.relative_to(plan.root)
        args += ["--add-data", f"{workspace_data}{_ADD_DATA_SEPARATOR}."]

    if icon is not None:
        args += ["--icon", str(icon)]

    args.append(str(launcher))
    return args


def log_path_for(plan: BuildPlan) -> Path:
    """Sciezka logu tego builda — wyliczalna z planu, zanim build ruszy.

    Publiczna, bo `run_build` musi ja znac takze wtedy, gdy backend NIE
    zdazyl oddac `BuildResult`: gdy wyjatek poleci juz po zapisaniu logu,
    uzytkownik i tak ma dostac sciezke, ktora zadanie 20 podpina pod "Zapisz
    raport". Jedno miejsce, w ktorym powstaje ta nazwa.

    W nazwie jest skrot sciezki PROJEKTU, nie sama nazwa EXE. Dwa rozne
    projekty czesto nazywaja sie tak samo ("program", "main"), a od rundy 2
    stary log jest KASOWANY przed buildem — bez tego skrotu build jednego
    projektu niszczylby log drugiego, zanim cokolwiek zapisze.
    """
    return logs_dir() / f"{plan.exe_name}-{path_hash(plan.root)}.log"


class PyInstallerBackend:
    def build(
        self,
        plan: BuildPlan,
        env: BuildEnv,
        progress: ProgressFn,
        cancel: CancelToken,
    ) -> BuildResult:
        started = time.monotonic()
        workspace = workspace_for(plan.root, plan.single_file)

        launcher = workspace / LAUNCHER_FILENAME
        launcher.write_text(
            render_launcher(plan.entry.stem, plan.app_kind, plan.output_mode),
            encoding="utf-8",
        )

        icon = None
        if plan.icon is not None:
            try:
                icon = ensure_ico(plan.icon, workspace / "_exelent_icon.ico")
            except ValueError:
                pass

        args = build_arguments(plan, workspace, launcher, icon)
        logs_dir().mkdir(parents=True, exist_ok=True)
        log_path = log_path_for(plan)
        lines: list[str] = []

        process = subprocess.Popen(
            [str(env.python), "-m", "PyInstaller", *args],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )

        progress(Progress(phase="build_start", fraction=0.2))
        assert process.stdout is not None

        # Read stdout on a worker thread so the main loop can poll the
        # cancel token on a short timer regardless of whether -- or how
        # rarely -- PyInstaller is currently emitting output.
        output_queue: queue.Queue[str | None] = queue.Queue()

        def _pump(stdout: object) -> None:
            try:
                for line in stdout:  # type: ignore[attr-defined]
                    output_queue.put(line)
            finally:
                output_queue.put(None)  # sentinel: stdout closed

        reader = threading.Thread(target=_pump, args=(process.stdout,), daemon=True)
        reader.start()

        cancelled = False
        stdout_closed = False
        while not stdout_closed:
            if cancel.cancelled:
                cancelled = True
                break
            try:
                line = output_queue.get(timeout=_CANCEL_POLL_SECONDS)
            except queue.Empty:
                continue
            if line is None:
                stdout_closed = True
                break
            lines.append(line.rstrip("\n"))
            for pattern, phase in PHASES.items():
                if re.search(pattern, line):
                    progress(Progress(phase=phase, fraction=_PHASE_PROGRESS[phase]))
                    break

        if cancelled:
            kill_returncode = _kill_tree(process.pid)
            lines.append(f"[exelent] taskkill returncode={kill_returncode}")

            wait_timed_out = False
            try:
                process.wait(timeout=_CANCEL_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                # The process is still alive despite taskkill -- do not hang
                # build() waiting for it. Give up on THIS wait, not on ever
                # returning: a build that cannot be cancelled and never
                # returns is indistinguishable from a frozen application.
                wait_timed_out = True
                lines.append(
                    f"[exelent] process still alive {_CANCEL_KILL_WAIT_SECONDS}s "
                    "after taskkill; giving up on waiting for it"
                )

            # Daemon thread: even if it never finishes (child still alive,
            # still writing to its stdout pipe), it cannot block interpreter
            # shutdown, and build() must not wait on it unboundedly either.
            reader.join(timeout=_CANCEL_READER_JOIN_SECONDS)
            log_path.write_text("\n".join(lines), encoding="utf-8")

            issues = [Issue("build_cancelled", Severity.INFO)]
            if kill_returncode != 0 or wait_timed_out:
                # Either taskkill itself reported failure, or -- regardless
                # of what it reported -- the wait timed out, which means the
                # process is still alive. Either way a PyInstaller process
                # may still be running and holding workspace files open,
                # which could make the NEXT build fail for reasons nobody
                # would connect back to this cancel.
                issues.append(Issue("cancel_incomplete", Severity.WARNING))
            return BuildResult(ok=False, log_path=log_path, issues=tuple(issues))

        returncode = process.wait()
        reader.join(timeout=5)
        log_path.write_text("\n".join(lines), encoding="utf-8")
        duration = time.monotonic() - started

        if returncode != 0:
            return BuildResult(ok=False, log_path=log_path, duration_s=duration)

        produced, issue = self._collect_artifact(plan, workspace)
        if produced is None:
            return BuildResult(
                ok=False,
                log_path=log_path,
                duration_s=duration,
                issues=(issue,) if issue is not None else (),
            )

        progress(Progress(phase="done", fraction=1.0))
        return BuildResult(
            ok=True,
            artifact=produced,
            size_bytes=_tree_size(produced),
            duration_s=duration,
            log_path=log_path,
        )

    def _collect_artifact(
        self, plan: BuildPlan, workspace: Path
    ) -> tuple[Path | None, Issue | None]:
        dist = workspace / "dist"
        is_onedir = plan.output_mode is OutputMode.ONEDIR
        source = dist / plan.exe_name if is_onedir else dist / f"{plan.exe_name}.exe"
        if not source.exists():
            return None, Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name})

        plan.dest_dir.mkdir(parents=True, exist_ok=True)
        target = plan.dest_dir / source.name

        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                try:
                    target.unlink()
                except OSError:
                    pass
            if target.exists():
                # A build reports ok=True only when the artifact is exactly
                # where BuildResult says it is. A locked leftover file (a
                # prior EXE still running, antivirus scanning it, ...) must
                # not let shutil.move silently nest the new build one level
                # deeper inside the stale directory it could not clear.
                return None, Issue("dest_in_use", Severity.BLOCKER, {"path": str(target)})

        shutil.move(str(source), str(target))

        if not target.exists():
            return None, Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name})

        if is_onedir and (target / source.name).exists():
            return None, Issue("dest_in_use", Severity.BLOCKER, {"path": str(target)})

        return target, None


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _kill_tree(pid: int) -> int:
    """PyInstaller uruchamia procesy potomne — bez /T zostają sierotami.

    Zwraca kod wyjścia taskkill, żeby wywołujący mógł wykryć nieudane
    zabicie (proces może wciąż trzymać otwarte pliki w workspace).
    """
    result = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    return result.returncode
