"""Entry point detection. The strongest signal is the import graph within
the project: the root is the file that imports others but is not itself
imported by any non-test file in the project.

This graph signal intentionally dominates over all weaker hints combined
(file name, __main__ guard, root location, startup call): the import-graph
root (ROOT_CANDIDATE_BONUS) is numerically larger than the sum of all other
bonuses, so no combination of weak signals can outweigh the true import
root. Imports from test files (test_*.py / *_test.py) do not count toward
this graph — a file imported only by tests is still treated as a root.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path

from exelent.analysis.parsed import ParsedSources
from exelent.models import EntryCandidate

PREFERRED_STEMS = ("main", "app", "run", "start", "__main__", "program", "gui")
STARTUP_CALLS = frozenset({"mainloop", "exec", "exec_", "run", "run_app", "show"})
CERTAINTY_MARGIN = 15

# The sum of all weaker bonuses (IMPORTS_LOCAL_BONUS + MAIN_GUARD_BONUS +
# ROOT_LOCATION_BONUS + PREFERRED_NAME_BONUS + STARTUP_CALL_BONUS) equals
# 15+25+10+20+15 = 85. ROOT_CANDIDATE_BONUS must exceed this so the
# import-graph signal always wins — see module docstring.
ROOT_CANDIDATE_BONUS = 100
IMPORTS_LOCAL_BONUS = 15
MAIN_GUARD_BONUS = 25
ROOT_LOCATION_BONUS = 10
PREFERRED_NAME_BONUS = 20
STARTUP_CALL_BONUS = 15
TEST_FILE_PENALTY = 40


def import_roots(root: Path, sources: Mapping[Path, str]) -> tuple[Path, ...]:
    """Import roots of the project — directories from which ``import X`` resolves.

    Normal layout: just ``root``. ``src/`` layout: ALSO ``root/src/`` when
    ``src/`` exists as a directory but is NOT a Python package (no
    ``__init__.py``) and at least one source file resides under ``src/`` (B04).

    This same logic must apply everywhere: in the set of local modules (so
    that ``import demo`` does not go to PyPI), in the scanner's import
    closure (so that ``import helper`` finds a neighbour), and in PyInstaller
    arguments (``--paths``). One place.
    """
    roots: list[Path] = [root]
    src = root / "src"
    if (
        src.is_dir()
        and not (src / "__init__.py").is_file()
        and any(_is_under(p, src) for p in sources)
    ):
        roots.append(src)
    return tuple(roots)


def _is_under(path: Path, directory: Path) -> bool:
    """Whether ``path`` lies under ``directory`` (not ``directory`` itself)."""
    try:
        path.relative_to(directory)
        return path != directory
    except ValueError:
        return False


def _module_name_from_root(import_root: Path, path: Path) -> str:
    """Top-level module name relative to a single import root."""
    rel = path.relative_to(import_root)
    return rel.stem if rel.parent == Path(".") else rel.parts[0]


def _module_name(root: Path, path: Path, roots: tuple[Path, ...] | None = None) -> str:
    """Top-level module name, accounting for the ``src/`` layout.

    For ``src/demo/main.py`` when ``src/`` is not a package: returns
    ``"demo"``, not ``"src"``. Without this, ``import demo.helper`` would
    be flagged as an external package (B04).
    """
    if roots is not None:
        # Pick the deepest matching root (src/ is deeper than root).
        for ir in sorted(roots, key=lambda r: len(r.parts), reverse=True):
            try:
                return _module_name_from_root(ir, path)
            except ValueError:
                continue
    rel = path.relative_to(root)
    return rel.stem if rel.parent == Path(".") else rel.parts[0]


def local_module_names(root: Path, sources: Mapping[Path, str]) -> set[str]:
    roots = import_roots(root, sources)
    return {_module_name(root, p, roots) for p in sources}


def _is_test_file(path: Path) -> bool:
    stem = path.stem.lower()
    return stem.startswith("test_") or stem.endswith("_test")


def _imported_locals(code: str, local: set[str], *, tree: ast.Module | None = None) -> set[str]:
    if tree is None:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                found.add(node.module.split(".")[0])
    return found & local


def _has_main_guard(code: str, *, tree: ast.Module | None = None) -> bool:
    if tree is None:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = ast.dump(node.test)
        if "__name__" in test and "__main__" in test:
            return True
    return False


def _has_startup_call(code: str, *, tree: ast.Module | None = None) -> bool:
    if tree is None:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in STARTUP_CALLS
        ):
            return True
    return False


def rank_entry_candidates(root: Path, sources: Mapping[Path, str]) -> tuple[EntryCandidate, ...]:
    if not sources:
        return ()
    if len(sources) == 1:
        only = next(iter(sources))
        return (EntryCandidate(path=only, score=100, reasons=("only file",)),)

    # B11: use AST cache if sources is a ParsedSources
    parsed = sources if isinstance(sources, ParsedSources) else ParsedSources(sources)

    roots = import_roots(root, sources)
    local = local_module_names(root, sources)
    imported_by_nontest: set[str] = set()
    imports_map: dict[Path, set[str]] = {}
    for path, code in sources.items():
        t = parsed.tree(path)
        deps = _imported_locals(code, local, tree=t)
        imports_map[path] = deps
        if not _is_test_file(path):
            imported_by_nontest |= deps

    candidates: list[EntryCandidate] = []
    for path, code in sources.items():
        score = 0
        reasons: list[str] = []
        module = _module_name(root, path, roots)
        t = parsed.tree(path)

        if module not in imported_by_nontest:
            score += ROOT_CANDIDATE_BONUS
            reasons.append("import graph root (no non-test file imports it)")
        if imports_map[path]:
            score += IMPORTS_LOCAL_BONUS
            reasons.append("imports other project files")
        if _has_main_guard(code, tree=t):
            score += MAIN_GUARD_BONUS
            reasons.append("has __main__ guard")
        if path.parent == root:
            score += ROOT_LOCATION_BONUS
            reasons.append("located in project root")
        if path.stem.lower() in PREFERRED_STEMS or path.stem.lower() == root.name.lower():
            score += PREFERRED_NAME_BONUS
            reasons.append("typical entry point filename")
        if _has_startup_call(code, tree=t):
            score += STARTUP_CALL_BONUS
            reasons.append("calls application startup")
        if _is_test_file(path):
            score -= TEST_FILE_PENALTY
            reasons.append("looks like a test")

        candidates.append(EntryCandidate(path=path, score=score, reasons=tuple(reasons)))

    candidates.sort(key=lambda c: (-c.score, str(c.path)))
    return tuple(candidates)


def entry_is_certain(candidates: Sequence[EntryCandidate]) -> bool:
    if len(candidates) <= 1:
        return True
    return candidates[0].score - candidates[1].score >= CERTAINTY_MARGIN
