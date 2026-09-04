"""Co rdzen NAPRAWDE produkuje — liczone z kodu, nie przepisane do testu.

Recenzja rundy 4 (I12) pokazala, po co to istnieje: oba straznik i kompletnosci
przewidziane w planie byly slepe na 7 kodow, ktore rdzen produkuje, w tym na
`cloud_file_unavailable` stworzony rundu wczesniej. Lista przepisana recznie
starzeje sie po cichu — nikt nie dostaje czerwonego testu, tylko uzytkownik
dostaje goly kod zamiast zdania.

Skan jest skladniowy (AST), wiec ma swoje granice: widzi `Issue("kod", ...)`
z literalem, nie widzi kodu skladanego w locie. Dlatego kazde takie miejsce
musi byc ZADEKLAROWANE ponizej, a test pilnuje, ze deklaracja zgadza sie z
rzeczywistoscia. Nowa konstrukcja dynamiczna zapala test, zamiast po cichu
wypasc z inwentarza.
"""

from __future__ import annotations

import ast
from pathlib import Path

from exelent.build.pyinstaller import PHASES
from exelent.diagnostics.patterns import PATTERNS

CORE = Path(__file__).resolve().parents[2] / "exelent"

# Kody, ktorych `data` nie jest literalnym slownikiem w miejscu wywolania.
# Klucze podane recznie, bo skan ich nie widzi — i wlasnie dlatego test
# `test_codes_with_non_literal_data_are_declared` pilnuje tej listy.
DECLARED_DATA: dict[str, frozenset[str]] = {
    "txt_syntax_error": frozenset({"file", "line", "detail"}),
    "size_estimate": frozenset({"low", "high", "packages"}),
    "size_estimate_large": frozenset({"low", "high", "packages"}),
}

# Miejsca, w ktorych sam KOD Issue nie jest literalem. Jedyne takie miejsce to
# `explain_log`, ktore przepisuje kody z `PATTERNS` — a te inwentarz i tak zna.
DECLARED_DYNAMIC_ISSUES = frozenset({"diagnostics/patterns.py::explain_log"})

# To samo dla faz postepu: `_run_pyinstaller` przepisuje wartosci z `PHASES`.
DECLARED_DYNAMIC_PHASES = frozenset({"build/pyinstaller.py::build"})


def _calls(name: str):
    """(sciezka::funkcja, wezel wywolania) dla kazdego wywolania `name` w rdzeniu."""
    for path in sorted(CORE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = path.relative_to(CORE).as_posix()
        yield from _in_scope(tree, f"{where}::<modul>", where, name)


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
    """Kod Issue -> klucze `data`, ktore rdzen pod niego podklada."""
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
    """Faza z wywolania `progress(...)` — w obu ksztaltach.

    Do zadania 10 faza byla pierwszym argumentem: `progress("analyze", 0.3)`.
    Teraz siedzi w obiekcie: `progress(Progress(phase="analyze", ...))`.
    Bez tego skan przestaje widziec fazy, `test_every_progress_phase_is_translated`
    slepnie na pustym zbiorze, a jedynym sygnalem zostaje
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
