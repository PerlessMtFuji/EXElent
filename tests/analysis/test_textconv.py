import ast

from exelent.analysis.textconv import convert_text_to_python, decode_bytes


def test_decodes_utf8_with_bom():
    text, enc = decode_bytes("print('zażółć')".encode("utf-8-sig"))
    assert "zażółć" in text and enc == "utf-8-sig"


def test_decodes_cp1250_polish_notepad():
    text, enc = decode_bytes("x = 'ąćę'".encode("cp1250"))
    assert text == "x = 'ąćę'" and enc == "cp1250"


def test_decodes_utf16():
    text, _ = decode_bytes("print(1)".encode("utf-16"))
    assert text.strip() == "print(1)"


def test_normalizes_typographic_quotes():
    result = convert_text_to_python("x = \u201ecze\u015b\u0107\u201d".encode())
    assert result.ok and result.code == 'x = "cześć"'


def test_normalizes_nonbreaking_space():
    result = convert_text_to_python("x\u00a0=\u00a01".encode())
    assert result.ok and result.code == "x = 1"


def test_strips_markdown_fence():
    raw = "Oto twój program:\n\n```python\nprint('hi')\n```\n\nMiłego dnia!"
    result = convert_text_to_python(raw.encode())
    assert result.ok and result.code == "print('hi')"


def test_joins_multiple_fences():
    raw = "```python\nimport sys\n```\ntekst\n```python\nprint(sys.argv)\n```"
    result = convert_text_to_python(raw.encode())
    assert result.ok and result.code == "import sys\nprint(sys.argv)"


def test_strips_line_numbers():
    raw = "1  import sys\n2  print(sys.version)\n3  print('ok')\n"
    result = convert_text_to_python(raw.encode())
    assert result.ok and result.code == "import sys\nprint(sys.version)\nprint('ok')"


def test_strips_repl_prompts():
    raw = ">>> x = 1\n>>> if x:\n...     print(x)\n"
    result = convert_text_to_python(raw.encode())
    assert result.ok and result.code == "x = 1\nif x:\n    print(x)"


def test_converts_tabs_when_mixed_with_spaces():
    raw = "def f():\n\treturn 1\n\ndef g():\n    return 2\n"
    result = convert_text_to_python(raw.encode())
    assert result.ok and "\t" not in result.code


def test_reports_syntax_error_with_line_and_does_not_guess():
    result = convert_text_to_python(b"def f(:\n    pass\n")
    assert result.ok is False
    assert result.error_line == 1
    assert result.code is None


def test_records_applied_steps():
    raw = "```python\nprint(1)\n```"
    result = convert_text_to_python(raw.encode())
    assert "fence" in result.steps


def test_tab_expansion_preserves_program_structure():
    """Regression for a tabwidth-4 bug: two indent strings can share the same
    tabstop-8 column and the same character count (so CPython's TabError
    detector sees no ambiguity and ast.parse succeeds on the raw input) while
    still expanding to different columns at tabstop 4 -- silently reparenting
    `y = 2` into the inner `if` body. Tab expansion must use tabstop 8, the
    width CPython's own tokenizer used to decide the original structure, so
    the converted code parses to the exact same AST as the raw input.
    """
    raw = b"if True:\n  \t  \tif True:\n  \t  \t    z = 1\n    \t\ty = 2\n"
    result = convert_text_to_python(raw)
    assert result.ok
    assert ast.dump(ast.parse(result.code)) == ast.dump(ast.parse(raw.decode()))


def test_rejects_future_import_pushed_off_the_first_line():
    """Regression: `ast.parse` is not a strong enough gate for this module.

    `ast.parse` runs the parser only (PyCF_ONLY_AST); the rule that a
    `from __future__` import must precede every other statement lives in the
    COMPILER, one stage later. A chat window that copies the fence label but
    not the backticks leaves a bare `python` line on top -- valid as an
    expression statement, so the parser is happy, and the whole file then
    fails to compile.

    Letting that through is not a cosmetic miss. PyInstaller compiles every
    module while writing the PYZ, catches the SyntaxError, DROPS the module
    and exits 0, so the user gets an EXE that dies with
    "ImportError: No module named <their program>".
    """
    raw = b"python\nfrom __future__ import annotations\n\nprint(1)\n"
    result = convert_text_to_python(raw)
    assert result.ok is False
    assert result.error_line == 2
    assert result.code is None


def test_rejects_return_outside_a_function():
    """Second compile-stage-only check, same gap as the future-import one:
    `ast.parse` accepts a bare `return`, the compiler rejects it."""
    result = convert_text_to_python(b"x = 1\nreturn x\n")
    assert result.ok is False
