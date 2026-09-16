"""Derive what the core actually produces from code instead of a copied list.

Review round 4 (I12) showed why this exists: both planned completeness guards
missed seven codes emitted by the core, including `cloud_file_unavailable`
added one round earlier. A manually copied list becomes stale silently, leaving
the user with a raw code instead of a sentence while tests remain green.

The scan is syntax-based (AST), so it has limits: it sees a literal
`Issue("code", ...)`, but not a code assembled at runtime. Every dynamic site
must therefore be declared below, and a test checks declarations against
reality. A new dynamic construction fails a test instead of leaving the
inventory silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

from exelent.build.pyinstaller import PHASES
from exelent.diagnostics.patterns import PATTERNS

CORE = Path(__file__).resolve().parents[2] / "exelent"

# Codes whose `data` is not a literal dictionary at the call site. The keys are
# listed manually because the scan cannot see them, which is precisely why
# `test_codes_with_non_literal_data_are_declared` protects this list.
DECLARED_DATA: dict[str, frozenset[str]] = {
    "txt_syntax_error": frozenset({"file", "line", "detail"}),
    "size_estimate": frozenset({"low", "high", "packages"}),
    "size_estimate_large": frozenset({"low", "high", "packages"}),
}

# Sites where the Issue code itself is not a literal. The only such site is
# `explain_log`, which copies codes from `PATTERNS`, already known to inventory.
DECLARED_DYNAMIC_ISSUES = frozenset({"diagnostics/patterns.py::explain_log"})

# Likewise for progress phases: `_run_pyinstaller` copies values from `PHASES`.
DECLARED_DYNAMIC_PHASES = frozenset({"build/pyinstaller.py::build"})


def _calls(name: str):
    """Yield (path::function, call node) for each core call to `name`."""
    for path in sorted(CORE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = path.relative_to(CORE).as_posix()
        yield from _in_scope(tree, f"{where}::<module>", where, name)


def _in_scope(node: ast.AST, scope: str, where: str, name: str):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _in_scope(child, f"{where}::{child.name}", where, name)
            continue
        if isinstance(child, ast.Call) and getattr(child.func, "id", None) == name:
            yield scope, child
        yield from _in_scope(child, scope, where, name)


def _literal_str(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _data_node(node: ast.Call) -> ast.AST | None:
    if len(node.args) > 2:
        return node.args[2]
    for keyword in node.keywords:
        if keyword.arg == "data":
            return keyword.value
    return None


def issue_data_keys() -> dict[str, set[str]]:
    """Map each Issue code to the `data` keys supplied by the core."""
    found: dict[str, set[str]] = {}
    for _where, node in _calls("Issue"):
        code = _literal_str(node.args[0]) if node.args else None
        if code is None:
            continue
        keys = found.setdefault(code, set())
        data = _data_node(node)
        if isinstance(data, ast.Dict):
            keys |= {k.value for k in data.keys if _literal_str(k) is not None}
    for code, declared in DECLARED_DATA.items():
        found.setdefault(code, set()).update(declared)
    for pattern, code, _severity in PATTERNS:
        found.setdefault(code, set())
        if pattern.groups:
            found[code].add("module")
    return found


def codes_with_non_literal_data() -> set[str]:
    unknown = set()
    for _where, node in _calls("Issue"):
        code = _literal_str(node.args[0]) if node.args else None
        data = _data_node(node)
        if code is not None and data is not None and not isinstance(data, ast.Dict):
            unknown.add(code)
    return unknown


def dynamic_issue_sites() -> set[str]:
    return {
        where
        for where, node in _calls("Issue")
        if not node.args or _literal_str(node.args[0]) is None
    }


def _phase_of(node: ast.Call) -> str | None:
    """Extract the phase from either form of a `progress(...)` call.

    Before task 10, the phase was the first argument: `progress("analyze", 0.3)`.
    It now lives in an object: `progress(Progress(phase="analyze", ...))`.
    Without both forms, the scan stops seeing phases,
    `test_every_progress_phase_is_translated` passes on an empty set, and the
    only remaining signal is
    `test_dynamic_progress_sites_are_declared`.
    """
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Call) and getattr(first.func, "id", None) == "Progress":
        for keyword in first.keywords:
            if keyword.arg == "phase":
                return _literal_str(keyword.value)
        return _literal_str(first.args[0]) if first.args else None
    return _literal_str(first)


def phase_keys() -> set[str]:
    literal = {
        phase for _where, node in _calls("progress") if (phase := _phase_of(node)) is not None
    }
    return literal | set(PHASES.values())


def dynamic_phase_sites() -> set[str]:
    return {where for where, node in _calls("progress") if _phase_of(node) is None}
