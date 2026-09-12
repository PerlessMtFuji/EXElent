"""Kwalifikowana nazwa modułu wejściowego i korzenie importów.

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
    alias: tuple[Path, Path] | None = None
    """(źródło, cel) do skopiowania w workspace PRZED buildem, gdy nazwa modułu
    wejściowego zderza się z launcherem. Dziś dotyczy tylko samotnego
    `__main__.py` w korzeniu — patrz `resolve_entry`. `None`, gdy nic nie trzeba
    kopiować. Kopiowanie wykonuje backend; kontrakt (co i pod jaką nazwą)
    powstaje wyłącznie tutaj."""


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

    # Samotny `__main__.py` w korzeniu (parts == ["__main__"]) NIE moze zostac
    # sobą: w zamrozonym EXE modul `__main__` to LAUNCHER, a jego `__spec__`
    # jest None. runpy.run_module("__main__") wola find_spec("__main__"), trafia
    # na launcher i rzuca `ValueError: __main__.__spec__ is None` — build konczy
    # sie kodem 0, a EXE umiera z kodem 1 (pozorny sukces). Kierujemy wiec
    # zbieranie i uruchomienie na bezpieczny alias, a plik `__main__.py`
    # kopiujemy pod te nazwe (kopiuje backend). Uruchomiony z run_name="__main__"
    # alias zachowuje `__name__ == "__main__"`, ktorego skrypt oczekuje.
    #
    # To NIE dotyczy `pkg/__main__.py` (parts == ["pkg","__main__"]): tam
    # uruchamiamy `python -m pkg`, wiec runpy dostaje `pkg`, a do paczki wchodzi
    # `pkg.__main__` — zaden z nich nie zderza sie z launcherem.
    if parts == ["__main__"]:
        alias_name = "_exelent_main"
        return EntrySpec(
            run_module=alias_name,
            collect_module=alias_name,
            roots=(import_root,),
            alias=(entry_abs, import_root / f"{alias_name}.py"),
        )

    collect_module = ".".join(parts)
    if len(parts) > 1 and parts[-1] == "__main__":
        run_module = ".".join(parts[:-1])
    else:
        run_module = collect_module

    return EntrySpec(run_module=run_module, collect_module=collect_module, roots=(import_root,))
