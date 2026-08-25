"""Backend PyInstallera: składa argumenty, prowadzi podproces i tłumaczy
jego log na fazy paska postępu."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from exelent.build.backend import CancelToken
from exelent.build.icon import ensure_ico
from exelent.build.launcher import LAUNCHER_FILENAME, render_launcher
from exelent.models import AppKind, BuildPlan, BuildResult, Issue, OutputMode, Severity
from exelent.runtime import ProgressFn
from exelent.runtime.env import CREATE_NO_WINDOW, BuildEnv
from exelent.runtime.paths import logs_dir, work_dir_for

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


class PyInstallerBackend:
    def build(
        self,
        plan: BuildPlan,
        env: BuildEnv,
        progress: ProgressFn,
        cancel: CancelToken,
    ) -> BuildResult:
        started = time.monotonic()
        workspace = work_dir_for(plan.root) / "src"

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
        log_path = logs_dir() / f"{plan.exe_name}.log"
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

        progress("build_start", 0.2)
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line.rstrip("\n"))
            if cancel.cancelled:
                _kill_tree(process.pid)
                log_path.write_text("\n".join(lines), encoding="utf-8")
                return BuildResult(
                    ok=False,
                    log_path=log_path,
                    issues=(Issue("build_cancelled", Severity.INFO),),
                )
            for pattern, phase in PHASES.items():
                if re.search(pattern, line):
                    progress(phase, _PHASE_PROGRESS[phase])
                    break

        returncode = process.wait()
        log_path.write_text("\n".join(lines), encoding="utf-8")
        duration = time.monotonic() - started

        if returncode != 0:
            return BuildResult(ok=False, log_path=log_path, duration_s=duration)

        produced = self._collect_artifact(plan, workspace)
        if produced is None:
            return BuildResult(
                ok=False,
                log_path=log_path,
                duration_s=duration,
                issues=(Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name}),),
            )

        progress("done", 1.0)
        return BuildResult(
            ok=True,
            artifact=produced,
            size_bytes=_tree_size(produced),
            duration_s=duration,
            log_path=log_path,
        )

    def _collect_artifact(self, plan: BuildPlan, workspace: Path) -> Path | None:
        dist = workspace / "dist"
        source = (
            dist / f"{plan.exe_name}.exe"
            if plan.output_mode is OutputMode.ONEFILE
            else dist / plan.exe_name
        )
        if not source.exists():
            return None

        plan.dest_dir.mkdir(parents=True, exist_ok=True)
        target = plan.dest_dir / source.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink()
        shutil.move(str(source), str(target))
        return target


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _kill_tree(pid: int) -> None:
    """PyInstaller uruchamia procesy potomne — bez /T zostają sierotami."""
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
