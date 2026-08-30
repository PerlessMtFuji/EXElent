from pathlib import Path

from exelent.analysis.scanner import local_import_closure, scan_directory, scan_single_file


def _make(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_collects_python_files(tmp_path):
    root = _make(tmp_path, {"main.py": "print(1)", "lib/util.py": "x = 1"})
    result = scan_directory(root)
    assert {p.name for p in result.py_files} == {"main.py", "util.py"}


def test_skips_excluded_directories(tmp_path):
    root = _make(tmp_path, {"main.py": "", ".venv/lib/thing.py": "", "__pycache__/a.py": ""})
    result = scan_directory(root)
    assert [p.name for p in result.py_files] == ["main.py"]


def test_requirements_is_not_a_text_candidate(tmp_path):
    root = _make(tmp_path, {"main.py": "", "requirements.txt": "requests\n"})
    result = scan_directory(root)
    assert result.requirements is not None
    assert result.text_candidates == ()


def test_prose_txt_is_not_a_candidate(tmp_path):
    root = _make(tmp_path, {"README.txt": "To jest opis programu dla uzytkownika."})
    result = scan_directory(root)
    assert result.text_candidates == ()


def test_code_in_txt_is_a_candidate(tmp_path):
    root = _make(tmp_path, {"kod.txt": "import sys\n\ndef main():\n    print('hi')\n"})
    result = scan_directory(root)
    assert [p.name for p in result.text_candidates] == ["kod.txt"]


def test_classifies_data_and_icons(tmp_path):
    root = _make(tmp_path, {"main.py": "", "dane.json": "{}", "logo.png": "x"})
    result = scan_directory(root)
    assert [p.name for p in result.data_files] == ["dane.json"]
    assert [p.name for p in result.icon_files] == ["logo.png"]


def test_stops_at_file_limit(tmp_path):
    root = _make(tmp_path, {f"f{i}.py": "" for i in range(20)})
    result = scan_directory(root, max_files=5)
    assert result.truncated is True
    assert result.file_count <= 6


def test_single_file_scan_ignores_everything_around_it(tmp_path):
    """Uzytkownik wskazal PLIK. Katalog nadrzedny to Pobrane, nie projekt."""
    (tmp_path / "test.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "cudzy.py").write_text("print('obcy')\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (tmp_path / "icon.ico").write_bytes(b"\x00")
    (tmp_path / "dane.csv").write_text("a,b\n", encoding="utf-8")

    result = scan_single_file(tmp_path / "test.py")

    assert result.single_file == tmp_path / "test.py"
    assert result.root == tmp_path
    assert result.py_files == (tmp_path / "test.py",)
    assert result.requirements is None
    assert result.icon_files == ()
    assert result.data_files == ()


def test_single_file_scan_routes_txt_through_the_same_check(tmp_path):
    """Plik .txt z kodem to sciezka flagowa produktu — musi trafic do
    kandydatow do konwersji, a nie do danych."""
    (tmp_path / "test.txt").write_text("import sys\nprint('x')\n", encoding="utf-8")

    result = scan_single_file(tmp_path / "test.txt")

    assert result.text_candidates == (tmp_path / "test.txt",)
    assert result.py_files == ()


def test_single_file_scan_of_plain_text_finds_no_code(tmp_path):
    (tmp_path / "notatka.txt").write_text("kup mleko\n", encoding="utf-8")

    result = scan_single_file(tmp_path / "notatka.txt")

    assert result.py_files == ()
    assert result.text_candidates == ()


def test_local_import_closure_follows_neighbours_transitively(tmp_path):
    (tmp_path / "main.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("import util\n", encoding="utf-8")
    (tmp_path / "util.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "obcy.py").write_text("Y = 2\n", encoding="utf-8")

    found, truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert set(found) == {tmp_path / "helper.py", tmp_path / "util.py"}
    assert truncated is False


def test_local_import_closure_resolves_packages(tmp_path):
    (tmp_path / "main.py").write_text("from pakiet import rzecz\n", encoding="utf-8")
    (tmp_path / "pakiet").mkdir()
    (tmp_path / "pakiet" / "__init__.py").write_text("rzecz = 1\n", encoding="utf-8")

    found, _truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert found == (tmp_path / "pakiet" / "__init__.py",)


def test_local_import_closure_ignores_installed_packages(tmp_path):
    """`requests` nie lezy obok pliku, wiec nie jest modulem lokalnym —
    to zaleznosc do zainstalowania, a tym zajmuje sie `resolve_dependencies`."""
    (tmp_path / "main.py").write_text("import requests\nimport os\n", encoding="utf-8")

    found, _truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert found == ()


def test_local_import_closure_survives_a_cycle(tmp_path):
    (tmp_path / "main.py").write_text("import a\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import a\n", encoding="utf-8")

    found, _truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert set(found) == {tmp_path / "a.py", tmp_path / "b.py"}


def test_local_import_closure_stops_at_the_limit(tmp_path):
    """Limit chroni przed wciagnieciem polowy katalogu Pobrane przez lancuch
    importow. Po jego przekroczeniu zostaje sam plik wskazany."""
    (tmp_path / "main.py").write_text("import m0\n", encoding="utf-8")
    for i in range(10):
        nxt = f"import m{i + 1}\n" if i < 9 else "X = 1\n"
        (tmp_path / f"m{i}.py").write_text(nxt, encoding="utf-8")

    found, truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=3)

    assert truncated is True
    assert found == ()


def test_local_import_closure_ignores_unparsable_files(tmp_path):
    (tmp_path / "main.py").write_text("import zepsuty\n", encoding="utf-8")
    (tmp_path / "zepsuty.py").write_text("def (\n", encoding="utf-8")

    found, truncated = local_import_closure(tmp_path / "main.py", tmp_path, limit=50)

    assert found == (tmp_path / "zepsuty.py",)
    assert truncated is False
