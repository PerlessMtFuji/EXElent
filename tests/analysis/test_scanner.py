from pathlib import Path

from exelent.analysis.scanner import scan_directory, scan_single_file


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
