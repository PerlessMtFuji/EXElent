"""Kopia robocza projektu.

Build nigdy nie dotyka katalogu użytkownika: odbiorca nie używa gita i nie
ma jak cofnąć zmian. Wszystko dzieje się na kopii w %LOCALAPPDATA%.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from exelent.constants import EXCLUDED_DIRS
from exelent.models import BuildPlan, Issue, IssueError, Severity
from exelent.runtime.paths import work_dir_for


def workspace_for(root: Path, single_file: Path | None = None) -> Path:
    """Gdzie lezy kopia robocza projektu z `root`.

    Jedno miejsce, ktore to wie. Wczesniej ta sciezka powstawala dwa razy —
    tutaj i w `pyinstaller.py` — z tych samych skladnikow, ale niezaleznie:
    zmiana jednej definicji dawala build uruchomiony w katalogu bez kodu,
    co widac dopiero po kilkunastu minutach pracy PyInstallera.
    """
    return work_dir_for(root, single_file) / "src"


def _copy_and_verify(source: Path, target: Path, expected_hash: str) -> str | None:
    """Kopiuje plik i weryfikuje hash (B08).

    Zwraca `None` jeśli OK; nazwę pliku z opisem jeśli hash się nie zgadza.
    Pusty `expected_hash` (plik nie dał się odczytać przy analizie) pomija
    weryfikację — kopiowanie nadal się odbywa, bo brak hashu to brak
    dowodu, nie dowód braku.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if not expected_hash:
        return None
    h = hashlib.sha256()
    with open(target, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    if h.hexdigest() != expected_hash:
        return source.name
    return None


def materialize_workspace(plan: BuildPlan) -> Path:
    """Kopia robocza projektu z weryfikacją inwentarza (B08).

    Kopiuje TYLKO pliki zaakceptowane przez analizę (z inwentarza planu),
    nie cały katalog. Nowe pliki dodane po analizie nie wchodzą do builda
    bez ponownej analizy. Konwersje TXT->PY zapisywane z planu.

    Gdy inwentarz jest pusty (starszy plan bez B08), spada do kopiowania
    jawnych pól planu — bezpieczniejsze niż copytree, choć bez weryfikacji."""
    workspace = workspace_for(plan.root, plan.single_file)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)

    changed: list[str] = []

    if plan.source_inventory:
        # B08: kopiowanie inwentarza — TYLKO zaakceptowane pliki.
        inventory_lookup = {e.rel_path: e.sha256 for e in plan.source_inventory}
        for entry in plan.source_inventory:
            source = plan.root / entry.rel_path
            if not source.is_file():
                changed.append(f"{entry.rel_path} (usunięty)")
                continue
            target = workspace / entry.rel_path
            mismatch = _copy_and_verify(source, target, entry.sha256)
            if mismatch:
                changed.append(f"{entry.rel_path} (zmieniony)")
        # Upewnij się, że plik główny jest w workspace, nawet jeśli nie
        # trafił do inwentarza (konwersja TXT → nowy .py).
        entry_rel = plan.entry.relative_to(plan.root).as_posix()
        if entry_rel not in inventory_lookup and plan.entry.is_file():
            target = workspace / entry_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.entry, target)
    else:
        # Fallback: brak inwentarza — kopiuj jawne pola planu.
        all_sources: list[Path] = []
        if plan.single_file is not None:
            all_sources.append(plan.single_file)
        all_sources.extend(plan.extra_sources)
        # Dodaj WSZYSTKIE pliki .py z korzenia, jeśli to projekt (nie single file).
        # Filtrujemy wykluczone katalogi — tak samo jak skaner (B08 fallback).
        if plan.single_file is None:
            for dirpath, dirnames, filenames in plan.root.walk():
                dirnames[:] = [
                    d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")
                ]
                for name in filenames:
                    if name.endswith((".py", ".pyw")):
                        all_sources.append(dirpath / name)
        for source in all_sources:
            try:
                rel = source.relative_to(plan.root)
            except ValueError:
                continue
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for data in plan.data_files:
            try:
                rel = data.relative_to(plan.root)
            except ValueError:
                continue
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(data, target)

    if changed:
        raise IssueError(
            Issue(
                "source_changed_after_analysis",
                Severity.BLOCKER,
                {"files": ", ".join(changed[:5])},
            )
        )

    for name, code in plan.converted:
        # `name` to sciezka WZGLEDNA (np. `pkg/help.py`), wiec odtwarzamy
        # katalog docelowy — inaczej konwersja z podkatalogu ladowala w
        # korzeniu, a dwie o tej samej nazwie nadpisywaly sie (A06).
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")

    return workspace
