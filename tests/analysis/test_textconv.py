import ast

from exelent.analysis.textconv import NO_CODE, convert_text_to_python, decode_bytes


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

    The bare `python` label that first produced this is stripped now (see
    `test_strips_a_bare_fence_label_left_by_the_chat_window`), so the gate is
    tested here with a displacing line the converter has no business
    removing.
    """
    raw = b"x = 1\nfrom __future__ import annotations\n\nprint(1)\n"
    result = convert_text_to_python(raw)
    assert result.ok is False
    assert result.error_line == 2
    assert result.code is None


def test_rejects_return_outside_a_function():
    """Second compile-stage-only check, same gap as the future-import one:
    `ast.parse` accepts a bare `return`, the compiler rejects it."""
    result = convert_text_to_python(b"x = 1\nreturn x\n")
    assert result.ok is False


def test_strips_a_bare_fence_label_left_by_the_chat_window():
    """Some chat windows copy the fence LABEL but not the backticks, leaving
    a bare `python` on top. It parses (it is just a name expression), so the
    file looks fine until the compiler rejects whatever it displaced."""
    raw = b"python\nfrom __future__ import annotations\n\nprint(1)\n"
    result = convert_text_to_python(raw)
    assert result.ok
    assert result.code.startswith("from __future__")
    assert "fence_label" in result.steps


def test_strips_bare_label_in_its_other_spellings():
    """Etykieta jest rozpoznawana w swoich pisowniach, ale zdejmowana tylko
    gdy REALNIE psula kompilacje (przypadek smiecia z czatu). Tu kazda etykieta
    spycha `from __future__` z pierwszej linii, wiec wejscie sie nie kompiluje
    i etykieta musi zostac zdjeta (B02: otoczke zdejmujemy dla NIEpoprawnego
    wejscia)."""
    for label in (b"py", b"python3", b"  Python  "):
        raw = label + b"\nfrom __future__ import annotations\nprint(1)\n"
        result = convert_text_to_python(raw)
        assert result.ok, label
        assert result.code.startswith("from __future__"), label
        assert "fence_label" in result.steps, label


def test_bare_label_that_already_compiles_is_kept_unchanged():
    """Kompromis B02: sama etykieta `py` na osobnej linii daje program, ktory
    NADAL sie kompiluje (`py` to zwykle wyrazenie-nazwa). Zasada compile-first
    mowi: poprawnego wejscia nie poddajemy zdejmowaniu otoczki, wiec zwracamy je
    NIETKNIETE, zamiast zgadywac, ze to smiec. (W runtime da to NameError — to
    jasny koszt reguly "nie ruszaj poprawnego programu", nie utrata programu.)"""
    result = convert_text_to_python(b"py\nprint(1)\n")
    assert result.ok
    assert result.code == "py\nprint(1)"
    assert "fence_label" not in result.steps


def test_keeps_a_first_line_that_is_real_code():
    """`python` is only a stray label when it stands alone on the line."""
    result = convert_text_to_python(b"python = 3\nprint(python)\n")
    assert result.ok and result.code.startswith("python = 3")
    assert "fence_label" not in result.steps


def test_does_not_strip_the_label_when_nothing_would_be_left():
    result = convert_text_to_python(b"python\n\n\n")
    assert "fence_label" not in result.steps


# --- B02: poprawny program nie jest poddawany zdejmowaniu otoczki ---


def test_valid_program_with_fenced_example_in_a_string_is_kept_whole():
    """Samodokumentujacy sie program: poprawny Python, ktory TRZYMA blok
    ```python jako tekst WEWNATRZ literalu napisowego. Zdejmowanie ogrodzen
    siegalo do wnetrza literalu, wycinalo `EXAMPLE` i WYRZUCALO prawdziwy
    program, zwracajac ok=True z trescia przykladu (B02: najpierw sprawdzic
    cale wejscie kompilatorem; poprawnego programu nie poddawac usuwaniu
    fences)."""
    src = 'DOC = """\n```python\nprint(\'EXAMPLE\')\n```\n"""\nprint(\'REAL PROGRAM\')\n'
    result = convert_text_to_python(src.encode())
    assert result.ok
    assert result.code == src.rstrip("\n")
    assert "REAL PROGRAM" in result.code
    assert "fence" not in result.steps


def test_valid_program_with_numbered_lines_inside_a_literal_is_kept_whole():
    """Poprawny program, ktorego wielolinijkowy literal jest zdominowany przez
    linie zaczynajace sie od cyfr. Heurystyka numeracji (>=70% linii z numerem)
    obcielaby prefiksy WEWNATRZ literalu i zamieniala `1 a` na `a`, niszczac
    dane. Compile-first tego nie dopuszcza (B02: numerowana tresc literalu)."""
    src = (
        'MENU = """\n'
        "1 alpha\n2 beta\n3 gamma\n4 delta\n5 epsilon\n"
        "6 zeta\n7 eta\n8 theta\n"
        '"""\n'
        "print(MENU)\n"
    )
    result = convert_text_to_python(src.encode())
    assert result.ok
    assert result.code == src.rstrip("\n")
    assert "1 alpha" in result.code
    assert "line_numbers" not in result.steps


# --- A05: poprawny Python zostaje bez ruszania tresci ---


def test_valid_code_keeps_typographic_characters_in_literals():
    """`label = 'A—B…'` to poprawny Python. Globalna podmiana znakow zmieniala
    wartosc literalu (myslnik, wielokropek) — teraz zostaje nietkniety."""
    src = "label = 'A\u2014B\u2026'\nprint(label)\n"
    result = convert_text_to_python(src.encode())
    assert result.ok
    assert result.code == "label = 'A\u2014B\u2026'\nprint(label)"
    assert "normalize" not in result.steps


def test_valid_code_keeps_a_tab_inside_a_string():
    """`expandtabs` na calym tekscie rozwijalo tez taby w napisach. Tab w
    literale ma zostac tabem; normalizujemy tylko wciecie."""
    src = "sep = '\\t'\nprint('a' + sep + 'b')\n"
    result = convert_text_to_python(src.encode())
    assert result.ok
    assert "\\t" in result.code


def test_reconversion_of_valid_code_is_idempotent():
    src = "x = 'a\u2014b'\nprint(x)"
    once = convert_text_to_python(src.encode())
    twice = convert_text_to_python(once.code.encode())
    assert once.code == twice.code == src


def test_line_numbers_preserve_indentation():
    """`2     return 1` po zdjeciu numeru ma zachowac wciecie funkcji —
    wczesniej `return` ladowalo w kolumnie 0 i dawalo IndentationError."""
    raw = "1 def f():\n2     return 1\n3 print(f())\n"
    result = convert_text_to_python(raw.encode())
    assert result.ok, result.error_text
    assert result.code == "def f():\n    return 1\nprint(f())"


def test_empty_fence_is_rejected_as_no_code():
    result = convert_text_to_python(b"Oto program:\n```python\n```\nGotowe!")
    assert result.ok is False
    assert result.error_text == NO_CODE
    assert result.code is None


def test_only_chat_wrapper_is_rejected_as_no_code():
    result = convert_text_to_python(b"```python\n\n\n```")
    assert result.ok is False
    assert result.error_text == NO_CODE


# --- A05: tokenowa naprawa uszkodzonych ogranicznikow ---


def test_repair_preserves_typographic_chars_inside_valid_literals():
    """Kod sie nie kompiluje przez typograficzny cudzyslow uzyty jako
    OGRANICZNIK (linia 2). Naprawa ma go podmienic, ale NIE ruszac myslnika,
    ktory jest trescia poprawnego literalu w linii 1. Globalna podmiana
    znakow psula wartosc tego dobrego literalu (A05)."""
    src = "title = 'Rok 2024—2025'\nmsg = ‘ok’\n"
    result = convert_text_to_python(src.encode())
    assert result.ok
    assert result.code == "title = 'Rok 2024—2025'\nmsg = 'ok'"


def test_repair_fixes_delimiters_but_keeps_wrapped_content():
    """Typograficzne cudzyslowy jako OGRANICZNIK, a w srodku myslnik jako
    TRESC. Naprawa ma podmienic ograniczniki, ale zostawic myslnik — po
    zamknieciu literalu staje sie on chroniona trescia. Globalna podmiana
    psula go razem z ogranicznikami (A05)."""
    result = convert_text_to_python("msg = ‘ok—now’\n".encode())
    assert result.ok
    assert result.code == "msg = 'ok—now'"


def test_repair_reports_instead_of_guessing_unbalanced_delimiter():
    """Pojedynczy typograficzny cudzyslow-otwarcie bez pary. Naprawa nie
    zmysla domkniecia literalu — zwraca kontrolowany blad, nie pozorny sukces
    (A05: gdy granic literalu nie da sie pewnie rozpoznac, wskaz problem)."""
    result = convert_text_to_python("msg = ‘ok\n".encode())
    assert result.ok is False
    assert result.code is None


def test_repair_keeps_nbsp_inside_fstring_but_fixes_it_outside():
    """Twarda spacja w czesci TEKSTOWEJ f-stringa to tresc (chroniona), ta sama
    poza literalem to strukturalny smiec (do podmiany). Naprawa musi rozroznic
    te dwa miejsca — czesci tekstowe f-stringow sa chronione (A05)."""
    src = "x = f'a b'\ny = 1\n"
    result = convert_text_to_python(src.encode())
    assert result.ok
    assert result.code == "x = f'a b'\ny = 1"


# --- A05: mapa linii wynik -> oryginalny TXT ---


def test_error_line_points_to_the_original_txt_line_through_a_fence():
    """Blad skladni w kodzie wyjetym z ogrodzenia ma wskazywac linie w
    ORYGINALNYM TXT (tu 4), nie w wycietym kodzie (1) — inaczej uzytkownik
    szuka nieistniejacej linii (A05: mapa linii)."""
    raw = "Oto program:\n\n```python\ndef f(:\n    pass\n```\n"
    result = convert_text_to_python(raw.encode())
    assert result.ok is False
    assert result.error_line == 4


def test_error_line_maps_through_the_second_of_several_fences():
    """Kilka bloków łączonych w jeden kod. Błąd w DRUGIM bloku ma wskazać jego
    linię w oryginale (tu 7), a nie przesunięcie liczone od pierwszego bloku —
    mapa jest budowana per-blok (A05)."""
    raw = "Blok 1:\n```python\nimport sys\n```\nteraz drugi:\n```python\ndef g(:\n```\n"
    result = convert_text_to_python(raw.encode())
    assert result.ok is False
    assert result.error_line == 7


def test_line_map_is_populated_for_fenced_success():
    """Przy udanej konwersji mapa linii wiąże każdą linię wyniku z oryginałem —
    podstawa dla przyszłego podglądu zmian (A05)."""
    raw = "```python\nx = 1\ny = 2\n```\n"
    result = convert_text_to_python(raw.encode())
    assert result.ok
    assert result.code == "x = 1\ny = 2"
    assert result.line_map == (2, 3)
