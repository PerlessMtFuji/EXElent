"""Izolowane środowisko, w którym uruchamiany jest PyInstaller.

uv robi trzy rzeczy: sprowadza przenośnego CPythona (z tkinterem — czego
oficjalny embeddable Python nie ma), tworzy venv i instaluje paczki.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from exelent.constants import PYINSTALLER_SPEC, TARGET_PYTHON
from exelent.runtime import ProgressFn
from exelent.runtime.bootstrap import ensure_uv
from exelent.runtime.paths import work_dir_for

CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class BuildEnv:
    uv: Path
    venv: Path
    python: Path
    failed_packages: tuple[str, ...] = field(default_factory=tuple)


def run_uv(
    uv: Path, args: Sequence[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
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


def create_build_env(
    source: Path,
    packages: Sequence[str],
    progress: ProgressFn,
    *,
    python_version: str = TARGET_PYTHON,
) -> BuildEnv:
    uv = ensure_uv(progress)
    work = work_dir_for(source)
    venv = work / "venv"
    venv.parent.mkdir(parents=True, exist_ok=True)

    progress("install_python", 0.0)
    run_uv(uv, ["python", "install", python_version])

    progress("create_env", 0.3)
    run_uv(uv, ["venv", str(venv), "--python", python_version])

    python = venv / "Scripts" / "python.exe"

    progress("install_packages", 0.5)
    wanted = [PYINSTALLER_SPEC, *packages]
    result = run_uv(uv, ["pip", "install", "--python", str(python), *wanted])

    failed: list[str] = []
    if result.returncode != 0:
        # Instalacja hurtowa padła — próbujemy pojedynczo, żeby jedna zła
        # nazwa paczki nie zabiła całego builda.
        for spec in wanted:
            single = run_uv(uv, ["pip", "install", "--python", str(python), spec])
            if single.returncode != 0:
                failed.append(spec)

    progress("install_packages", 1.0)
    return BuildEnv(uv=uv, venv=venv, python=python, failed_packages=tuple(failed))
