"""Kwalifikowana nazwa modułu wejściowego i korzenie importów (A03).

Sama nazwa pliku nie określa modułu. `pkg/main.py` to moduł `pkg.main`, nie
`main` — a launcher z `runpy.run_module("main")` daje EXE, które umiera na
`ImportError: No module named main`. Nazwę liczymy względem KORZENIA IMPORTÓW
(najwyższego katalogu, od którego w dół każdy folder jest pakietem), a ten
korzeń trafia na `--paths`, żeby PyInstaller w ogóle znalazł kod.

Jedno miejsce, z którego bierze się i nazwa dla launchera, i argumenty
PyInstallera — inaczej te dwie ścieżki rozjeżdżają się po cichu.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EntrySpec:
    run_module: str
    """Cel `runpy.run_module` w launcherze. Dla `python -m pkg` to `pkg`."""
    collect_module: str
    """Cel `--hidden-import` — rzeczywisty plik .py, więc dla pakietu
    uruchamianego przez `__main__.py` to `pkg.__main__`, nie `pkg`."""
    roots: tuple[Path, ...]
    """Katalogi do dołożenia na `--paths`, żeby moduł dał się rozwiązać."""


def resolve_entry(workspace: Path, entry_rel: Path) -> EntrySpec:
    """Nazwa modułu wejściowego liczona względem korzenia importów w workspace.

    `entry_rel` jest względne do korzenia projektu (i tym samym do workspace,
    który odtwarza tę samą strukturę). Korzeń importów wyznaczamy wspinaczką w
    górę tak długo, jak każdy kolejny katalog jest pakietem (`__init__.py`),
    najwyżej do samego workspace.
    """
    entry_abs = workspace / entry_rel
    import_root = entry_abs.parent
    while import_root != workspace and (import_root / "__init__.py").exists():
        import_root = import_root.parent

    parts = list(entry_abs.relative_to(import_root).with_suffix("").parts)
    collect_module = ".".join(parts)

    # `pkg/__main__.py` uruchamia się jako `python -m pkg`: runpy dostaje `pkg`,
    # ale do paczki musi wejść `pkg.__main__`. Lone `__main__.py` w korzeniu
    # (parts == ["__main__"]) zostaje sobą — nie ma pakietu do uruchomienia.
    if len(parts) > 1 and parts[-1] == "__main__":
        run_module = ".".join(parts[:-1])
    else:
        run_module = collect_module

    return EntrySpec(run_module=run_module, collect_module=collect_module, roots=(import_root,))
