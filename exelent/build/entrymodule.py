"""Qualified name of the entry module and import roots.

The filename alone does not determine the module. `pkg/main.py` is module
`pkg.main`, not `main` — and a launcher with `runpy.run_module("main")` gives
an EXE that dies with `ImportError: No module named main`. The name is computed
relative to the IMPORT ROOT (the topmost directory from which every subfolder
downward is a package), and that root goes onto `--paths` so that PyInstaller
can find the code at all.

A single place from which both the launcher name and PyInstaller arguments
originate — otherwise the two paths silently diverge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EntrySpec:
    run_module: str
    """`runpy.run_module` target in the launcher. For `python -m pkg` this is `pkg`."""
    collect_module: str
    """`--hidden-import` target — the actual .py file, so for a package
    launched via `__main__.py` this is `pkg.__main__`, not `pkg`."""
    roots: tuple[Path, ...]
    """Directories to add to `--paths` so the module can be resolved."""
    alias: tuple[Path, Path] | None = None
    """(source, dest) to copy in the workspace BEFORE the build, when the entry
    module name collides with the launcher. Currently only applies to a lone
    `__main__.py` in the root — see `resolve_entry`. `None` when nothing needs
    to be copied. The copy is performed by the backend; the contract (what and
    under what name) is defined exclusively here."""


def resolve_entry(workspace: Path, entry_rel: Path) -> EntrySpec:
    """Entry module name computed relative to the import root in the workspace.

    `entry_rel` is relative to the project root (and therefore to the workspace,
    which reproduces the same structure). The import root is determined by
    climbing upward as long as each successive directory is a package
    (`__init__.py`), up to the workspace itself.

    B03: a folder WITHOUT `__init__.py` stops the climb — the module is resolved
    relative to that directory (which is added to `--paths`). Namespace packages
    (PEP 420) are handled in the scanner's import closure, not here: there it
    suffices to find the file to add it to the build, but here we need to
    determine the correct module name for `runpy.run_module`, which MUST match
    the `sys.path` structure.
    """
    entry_abs = workspace / entry_rel
    import_root = entry_abs.parent
    while import_root != workspace and (import_root / "__init__.py").exists():
        import_root = import_root.parent

    parts = list(entry_abs.relative_to(import_root).with_suffix("").parts)

    # A lone `__main__.py` in the root (parts == ["__main__"]) CANNOT remain
    # as-is: in a frozen EXE the `__main__` module is the LAUNCHER, and its
    # `__spec__` is None. runpy.run_module("__main__") calls
    # find_spec("__main__"), hits the launcher and raises
    # `ValueError: __main__.__spec__ is None` — the build finishes with exit
    # code 0 but the EXE dies with code 1 (apparent success). So we direct
    # collection and execution to a safe alias and copy the `__main__.py` file
    # under that name (the backend performs the copy). Launched with
    # run_name="__main__" the alias preserves `__name__ == "__main__"` that
    # the script expects.
    #
    # This does NOT apply to `pkg/__main__.py` (parts == ["pkg","__main__"]):
    # there we run `python -m pkg`, so runpy gets `pkg` and the package
    # includes `pkg.__main__` — neither collides with the launcher.
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
