"""Validate prepared sources with the target interpreter before PyInstaller.

Tests inject the development interpreter as the target (`sys.executable`), so
they remain fast and hermetic without downloading 3.12 through uv. They verify
the mechanism: starting the interpreter, compiling sources, and converting an
error to an Issue. Golden tests cover real 3.13-versus-3.12 incompatibility.
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


def test_unavailable_target_interpreter_blocks_instead_of_passing_as_no_error(tmp_path):
    """B09: a target interpreter that did not start means validation failed.

    Return the named `validation_failed` blocker instead of None or a bare
    exception.
    """
    ws = _workspace(tmp_path, {"main.py": "print(1)\n"})
    missing_python = tmp_path / "missing-python.exe"
    issue = validate_target_syntax(missing_python, ws, python_version="3.12")
    assert issue is not None
    assert issue.code == "validation_failed"
    assert issue.severity is Severity.BLOCKER


def test_nonzero_without_protocol_line_is_a_failure_not_success(tmp_path, monkeypatch):
    """A nonzero exit without the expected protocol means validation failed.

    B09 forbids treating a missing protocol as None/success, and an arbitrary
    tab on stdout must not be mistaken for an error record.
    """
    from exelent.build import validate

    ws = _workspace(tmp_path, {"main.py": "print(1)\n"})
    # The replacement checker exits nonzero without a protocol marker and also
    # prints a tab that the old heuristic would have mistaken for an error.
    monkeypatch.setattr(validate, "_CHECK_SOURCE", "import sys\nprint('a\\tb')\nsys.exit(3)\n")
    issue = validate.validate_target_syntax(Path(sys.executable), ws, python_version="3.12")
    assert issue is not None
    assert issue.code == "validation_failed"


def test_pyw_file_with_syntax_error_is_caught(tmp_path):
    """B09: validate .pyw as well as .py so GUI syntax errors fail before packaging."""
    ws = _workspace(tmp_path, {"app.pyw": "def f(:\n    pass\n"})
    issue = validate_target_syntax(Path(sys.executable), ws, python_version="3.12")
    assert issue is not None
    assert issue.code == "target_syntax_error"
    assert "app.pyw" in issue.data["file"]


def test_valid_pyw_file_passes(tmp_path):
    """B09: poprawny .pyw przechodzi walidacje."""
    ws = _workspace(tmp_path, {"app.pyw": "import tkinter\n"})
    assert validate_target_syntax(Path(sys.executable), ws, python_version="3.12") is None


def test_compiler_stage_error_is_caught_where_ast_parse_would_miss_it(tmp_path):
    """`ast.parse` accepts `return` outside a function, but the compiler rejects it.

    This gap let PyInstaller discard a module while assembling PYZ and still
    exit with code 0 (A08). Target-interpreter validation uses `compile` and
    catches the case before building.
    """
    ws = _workspace(tmp_path, {"main.py": "return 1\n"})
    issue = validate_target_syntax(Path(sys.executable), ws, python_version="3.12")
    assert issue is not None
    assert issue.code == "target_syntax_error"
