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
