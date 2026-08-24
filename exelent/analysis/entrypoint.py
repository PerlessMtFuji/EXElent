"""Wykrywanie pliku głównego. Najsilniejszym sygnałem jest graf importów
wewnątrz projektu: korzeń to plik, który importuje inne, ale sam nie jest
importowany przez nikogo."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path

from exelent.models import EntryCandidate

PREFERRED_STEMS = ("main", "app", "run", "start", "__main__", "program", "gui")
STARTUP_CALLS = frozenset({"mainloop", "exec", "exec_", "run", "run_app", "show"})
CERTAINTY_MARGIN = 15


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    return rel.stem if rel.parent == Path(".") else rel.parts[0]


def local_module_names(root: Path, sources: Mapping[Path, str]) -> set[str]:
    return {_module_name(root, p) for p in sources}


def _imported_locals(code: str, local: set[str]) -> set[str]:
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


def _has_main_guard(code: str) -> bool:
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


def _has_startup_call(code: str) -> bool:
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
        return (EntryCandidate(path=only, score=100, reasons=("jedyny plik",)),)

    local = local_module_names(root, sources)
    imported_by_someone: set[str] = set()
    imports_map: dict[Path, set[str]] = {}
    for path, code in sources.items():
        deps = _imported_locals(code, local)
        imports_map[path] = deps
        imported_by_someone |= deps

    candidates: list[EntryCandidate] = []
    for path, code in sources.items():
        score = 0
        reasons: list[str] = []
        module = _module_name(root, path)

        if module not in imported_by_someone:
            score += 30
            reasons.append("nikt go nie importuje")
        if imports_map[path]:
            score += 15
            reasons.append("importuje inne pliki projektu")
        if _has_main_guard(code):
            score += 25
            reasons.append("ma blok __main__")
        if path.parent == root:
            score += 10
            reasons.append("leży w korzeniu")
        if path.stem.lower() in PREFERRED_STEMS or path.stem.lower() == root.name.lower():
            score += 20
            reasons.append("typowa nazwa pliku startowego")
        if _has_startup_call(code):
            score += 15
            reasons.append("wywołuje start aplikacji")
        if path.stem.lower().startswith("test_") or path.stem.lower().endswith("_test"):
            score -= 40
            reasons.append("wygląda na test")

        candidates.append(EntryCandidate(path=path, score=score, reasons=tuple(reasons)))

    candidates.sort(key=lambda c: (-c.score, str(c.path)))
    return tuple(candidates)


def entry_is_certain(candidates: Sequence[EntryCandidate]) -> bool:
    if len(candidates) <= 1:
        return True
    return candidates[0].score - candidates[1].score >= CERTAINTY_MARGIN
