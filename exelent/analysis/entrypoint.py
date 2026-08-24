"""Wykrywanie pliku głównego. Najsilniejszym sygnałem jest graf importów
wewnątrz projektu: korzeń to plik, który importuje inne, ale sam nie jest
importowany przez żaden nietestowy plik projektu.

Ten graf sygnał celowo dominuje nad wszystkimi słabszymi wskazówkami razem
wziętymi (nazwa pliku, blok __main__, lokalizacja w korzeniu, wywołanie
startowe): korzeń grafu (ROOT_CANDIDATE_BONUS) jest liczbowo większy niż
suma wszystkich pozostałych bonusów, więc żadna kombinacja słabych sygnałów
nie potrafi przebić prawdziwego korzenia importów. Importy pochodzące z
plików testowych (test_*.py / *_test.py) nie liczą się do tego grafu —
plik importowany wyłącznie przez test nadal jest traktowany jak korzeń.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path

from exelent.models import EntryCandidate

PREFERRED_STEMS = ("main", "app", "run", "start", "__main__", "program", "gui")
STARTUP_CALLS = frozenset({"mainloop", "exec", "exec_", "run", "run_app", "show"})
CERTAINTY_MARGIN = 15

# Suma wszystkich słabszych bonusów (IMPORTS_LOCAL_BONUS + MAIN_GUARD_BONUS +
# ROOT_LOCATION_BONUS + PREFERRED_NAME_BONUS + STARTUP_CALL_BONUS) wynosi
# 15+25+10+20+15 = 85. ROOT_CANDIDATE_BONUS musi być od tego większy, żeby
# sygnał grafu importów zawsze wygrywał — patrz docstring modułu.
ROOT_CANDIDATE_BONUS = 100
IMPORTS_LOCAL_BONUS = 15
MAIN_GUARD_BONUS = 25
ROOT_LOCATION_BONUS = 10
PREFERRED_NAME_BONUS = 20
STARTUP_CALL_BONUS = 15
TEST_FILE_PENALTY = 40


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    return rel.stem if rel.parent == Path(".") else rel.parts[0]


def local_module_names(root: Path, sources: Mapping[Path, str]) -> set[str]:
    return {_module_name(root, p) for p in sources}


def _is_test_file(path: Path) -> bool:
    stem = path.stem.lower()
    return stem.startswith("test_") or stem.endswith("_test")


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
    imported_by_nontest: set[str] = set()
    imports_map: dict[Path, set[str]] = {}
    for path, code in sources.items():
        deps = _imported_locals(code, local)
        imports_map[path] = deps
        if not _is_test_file(path):
            imported_by_nontest |= deps

    candidates: list[EntryCandidate] = []
    for path, code in sources.items():
        score = 0
        reasons: list[str] = []
        module = _module_name(root, path)

        if module not in imported_by_nontest:
            score += ROOT_CANDIDATE_BONUS
            reasons.append("korzeń grafu importów (nikt nietestowy go nie importuje)")
        if imports_map[path]:
            score += IMPORTS_LOCAL_BONUS
            reasons.append("importuje inne pliki projektu")
        if _has_main_guard(code):
            score += MAIN_GUARD_BONUS
            reasons.append("ma blok __main__")
        if path.parent == root:
            score += ROOT_LOCATION_BONUS
            reasons.append("leży w korzeniu")
        if path.stem.lower() in PREFERRED_STEMS or path.stem.lower() == root.name.lower():
            score += PREFERRED_NAME_BONUS
            reasons.append("typowa nazwa pliku startowego")
        if _has_startup_call(code):
            score += STARTUP_CALL_BONUS
            reasons.append("wywołuje start aplikacji")
        if _is_test_file(path):
            score -= TEST_FILE_PENALTY
            reasons.append("wygląda na test")

        candidates.append(EntryCandidate(path=path, score=score, reasons=tuple(reasons)))

    candidates.sort(key=lambda c: (-c.score, str(c.path)))
    return tuple(candidates)


def entry_is_certain(candidates: Sequence[EntryCandidate]) -> bool:
    if len(candidates) <= 1:
        return True
    return candidates[0].score - candidates[1].score >= CERTAINTY_MARGIN
