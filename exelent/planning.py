"""Od ProjectAnalysis (zgadywanie) do BuildPlan (decyzja).

Wspólny punkt dla CLI i GUI. Build nigdy nie zgaduje — dostaje gotowy plan.
"""

from __future__ import annotations

import os
import re
import uuid
from contextlib import suppress
from pathlib import Path

from exelent.models import AppKind, BuildPlan, OutputMode, ProjectAnalysis

_ILLEGAL = re.compile(r'[/\\:*?"<>|]')

# Delete-on-close: Windows usuwa plik w momencie zamknięcia ostatniego uchwytu,
# także wtedy, gdy proces zostanie ubity między utworzeniem a sprzątaniem.
# Poza Windows stała nie istnieje i zostaje zwykły `unlink` w `finally`.
_O_TEMPORARY = getattr(os, "O_TEMPORARY", 0)


def sanitize_exe_name(name: str) -> str:
    cleaned = _ILLEGAL.sub("-", name).strip().rstrip(".")
    return cleaned or "program"


def _is_writable(path: Path) -> bool:
    """Czy da się utworzyć plik w `path` — bez zostawiania po sobie śladu.

    Dlaczego w ogóle zapis, skoro §7 specyfikacji mówi o nienaruszalności
    katalogu użytkownika: §7 chroni **katalog źródłowy**, a sondowany jest
    jego rodzic — dokładnie ten katalog, w którym za chwilę i tak powstanie
    folder `<Nazwa>-EXE`. Nie sprawdzamy więc nowego miejsca, tylko to, do
    którego build ma prawo pisać z definicji.

    Dlaczego nie `os.access(path, os.W_OK)`: na Windows odzwierciedla ono
    jedynie atrybut „tylko do odczytu", którego katalogi praktycznie nie
    używają, i całkowicie ignoruje listy ACL oraz blokady OneDrive. Zwróciłoby
    „można pisać" dla katalogu, do którego zapis i tak padnie — a wtedy build
    umiera po kilkunastu minutach pracy zamiast od razu wybrać Pulpit.

    Zapis jest tak zaprojektowany, żeby nie mógł zaszkodzić:
    - nazwa jest losowa, a flaga `O_EXCL` gwarantuje, że sonda nigdy nie
      nadpisze (ani nie skasuje) istniejącego pliku użytkownika,
    - `O_TEMPORARY` każe systemowi skasować plik przy zamknięciu uchwytu, więc
      nawet zabity w połowie proces nie zostawia śmiecia,
    - `unlink` w `finally` sprząta tam, gdzie `O_TEMPORARY` nie istnieje.
    """
    probe = Path(path) / f".exelent-probe-{uuid.uuid4().hex}.tmp"
    try:
        handle = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_RDWR | _O_TEMPORARY)
    except OSError:
        return False
    try:
        os.close(handle)
    finally:
        with suppress(OSError):
            os.unlink(probe)
    return True


def default_dest_dir(root: Path, exe_name: str) -> Path:
    folder = f"{sanitize_exe_name(exe_name)}-EXE"
    parent = Path(root).parent
    if parent.exists() and _is_writable(parent):
        return parent / folder
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    if not desktop.exists():
        desktop = Path(os.path.expanduser("~")) / "Pulpit"
    return desktop / folder


def make_plan(
    analysis: ProjectAnalysis,
    *,
    exe_name: str | None = None,
    entry: Path | None = None,
    icon: Path | None = None,
    dest_dir: Path | None = None,
    output_mode: OutputMode | None = None,
    app_kind: AppKind | None = None,
) -> BuildPlan:
    chosen_entry = entry or analysis.entry
    if chosen_entry is None:
        raise ValueError("brak pliku glownego — analiza nie znalazla kodu Pythona")

    name = sanitize_exe_name(exe_name or analysis.suggested_name)

    return BuildPlan(
        root=analysis.root,
        entry=Path(chosen_entry),
        app_kind=app_kind or analysis.app_kind,
        output_mode=output_mode or analysis.output_mode,
        exe_name=name,
        dest_dir=Path(dest_dir) if dest_dir else default_dest_dir(analysis.root, name),
        icon=Path(icon) if icon else analysis.suggested_icon,
        packages=tuple(d.package for d in analysis.dependencies if not d.optional),
        data_files=analysis.scan.data_files,
        # Policzone raz, w zadaniu 8, na prawdziwych treściach plików
        # (łącznie z tymi skonwertowanymi z `.txt`, których nie ma na dysku).
        hidden_imports=analysis.hidden_imports,
    )
