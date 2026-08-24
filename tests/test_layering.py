import ast
from pathlib import Path

CORE = Path("exelent")
UI_ONLY = {"ui"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_core_never_imports_qt():
    offenders = []
    for path in CORE.rglob("*.py"):
        if set(path.relative_to(CORE).parts) & UI_ONLY:
            continue
        if {"PySide6", "PyQt5", "PyQt6"} & _imports(path):
            offenders.append(str(path))
    assert offenders == [], f"Qt zaimportowane poza exelent/ui/: {offenders}"
