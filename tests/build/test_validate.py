"""Walidacja przygotowanych zrodel DOCELOWYM interpreterem przed PyInstallerem.

Testy wstrzykuja interpreter deweloperski jako "docelowy" (`sys.executable`),
wiec sa szybkie i hermetyczne — nie sciagaja 3.12 przez uv. Sprawdzaja MECHANIZM
(uruchomienie interpretera, kompilacja zrodel, przelozenie bledu na Issue);
dowod na realna niezgodnosc 3.13 vs 3.12 nalezy do golden testow.
"""

from __future__ import annotations

import sys
from pathlib import Path

from exelent.build.validate import validate_target_syntax
from exelent.models import Severity


def _workspace(tmp_path: Path, files: dict[str, str]) -> Path:
    ws = tmp_path / "src"
    for rel, content in files.items():
        target = ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return ws


def test_valid_sources_pass(tmp_path):
    ws = _workspace(tmp_path, {"main.py": "print(1)\n", "pkg/util.py": "x = 1\n"})
    assert validate_target_syntax(Path(sys.executable), ws, python_version="3.12") is None


def test_broken_source_returns_blocker_with_file_and_line(tmp_path):
    ws = _workspace(tmp_path, {"main.py": "print(1)\n", "pkg/bad.py": "def f(:\n    pass\n"})
    issue = validate_target_syntax(Path(sys.executable), ws, python_version="3.12")
    assert issue is not None
    assert issue.code == "target_syntax_error"
    assert issue.severity is Severity.BLOCKER
    assert issue.data["line"] == "1"
    assert "bad.py" in issue.data["file"]
    assert issue.data["version"] == "3.12"


def test_compiler_stage_error_is_caught_where_ast_parse_would_miss_it(tmp_path):
    """`return` poza funkcja: `ast.parse` (walidacja deweloperska) przepuszcza,
    a KOMPILATOR odrzuca. To dokladnie ta luka, przez ktora PyInstaller wyrzucal
    modul przy skladaniu PYZ i konczyl z kodem 0 (A08). Walidacja docelowym
    interpreterem uzywa `compile`, wiec lapie ten przypadek przed buildem."""
    ws = _workspace(tmp_path, {"main.py": "return 1\n"})
    issue = validate_target_syntax(Path(sys.executable), ws, python_version="3.12")
    assert issue is not None
    assert issue.code == "target_syntax_error"
