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
from exelent.diagnostics.patterns import explain_log
from exelent.models import Issue, IssueError, Severity
from exelent.runtime import ProgressFn
from exelent.runtime.bootstrap import ensure_uv
from exelent.runtime.paths import work_dir_for

CREATE_NO_WINDOW = 0x08000000


class BuildEnvError(IssueError):
    """Srodowisko builda nie powstalo.

    Bez tego wyjatku `create_build_env` oddawalo `BuildEnv` wygladajace na
    zdrowe, a awaria wychodzila cztery ramki dalej jako `FileNotFoundError
    [WinError 2]` z `Popen` — czyli w miejscu, ktore o przyczynie nie wie nic.
    """


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
    installed = run_uv(uv, ["python", "install", python_version])

    progress("create_env", 0.3)
    created = run_uv(uv, ["venv", str(venv), "--python", python_version])
    if created.returncode != 0:
        raise _env_failure(installed, created)

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


def _env_failure(
    installed: subprocess.CompletedProcess[str],
    created: subprocess.CompletedProcess[str],
) -> BuildEnvError:
    """Zamienia porazke uv w Issue — z winnym krokiem i rozpoznana przyczyna.

    Winny jest krok PIERWSZY z tych, ktore padly: gdy interpreter nie zjechal
    na dysk, venv nie mial z czego powstac, a wskazanie "tworzenie srodowiska"
    wyslaloby uzytkownika w zla strone.

    Niezerowy kod z samego `uv python install` NIE jest tu powodem do
    przerwania — uv zwraca go takze wtedy, gdy zgodny Python juz jest w
    systemie, a venv powstaje wtedy bez problemu.

    Strumien bledow uv przechodzi przez `explain_log`, bo dokladnie te
    przyczyny z sekcji 8 specyfikacji (proxy z podmienionym certyfikatem,
    zapelniony dysk) sa tam nazwane wprost. Sam tekst uv nigdy nie trafia do
    uzytkownika: jest po angielsku i w zargonie narzedzia.
    """
    step = "install_python" if installed.returncode != 0 else "create_env"
    stderr = (created.stderr or "") + "\n" + (installed.stderr or "")
    cause = explain_log(stderr)
    return BuildEnvError(
        Issue("env_setup_failed", Severity.BLOCKER, {"step": step}),
        RuntimeError(f"uv zwrocilo {created.returncode}"),
        extra=cause,
    )
