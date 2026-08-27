"""Kopia robocza projektu.

Build nigdy nie dotyka katalogu użytkownika: odbiorca nie używa gita i nie
ma jak cofnąć zmian. Wszystko dzieje się na kopii w %LOCALAPPDATA%.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

from exelent.constants import EXCLUDED_DIRS
from exelent.models import BuildPlan
from exelent.runtime.paths import work_dir_for


def workspace_for(root: Path) -> Path:
    """Gdzie lezy kopia robocza projektu z `root`.

    Jedno miejsce, ktore to wie. Wczesniej ta sciezka powstawala dwa razy —
    tutaj i w `pyinstaller.py` — z tych samych skladnikow, ale niezaleznie:
    zmiana jednej definicji dawala build uruchomiony w katalogu bez kodu,
    co widac dopiero po kilkunastu minutach pracy PyInstallera.
    """
    return work_dir_for(root) / "src"


def materialize_workspace(plan: BuildPlan, converted: Mapping[str, str]) -> Path:
    workspace = workspace_for(plan.root)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.parent.mkdir(parents=True, exist_ok=True)

    # ".*" mirrors the scanner (exelent/analysis/scanner.py), which skips
    # any directory whose name starts with a dot in addition to the named
    # EXCLUDED_DIRS. Without this the workspace can contain files analysis
    # never saw (e.g. .git history, editor caches), which PyInstaller would
    # then be free to bundle into the EXE.
    shutil.copytree(
        plan.root,
        workspace,
        ignore=shutil.ignore_patterns(*EXCLUDED_DIRS, ".*"),
        dirs_exist_ok=False,
    )

    for name, code in converted.items():
        (workspace / name).write_text(code, encoding="utf-8")

    return workspace
