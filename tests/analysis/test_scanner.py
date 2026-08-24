from pathlib import Path

from exelent.analysis.scanner import scan_directory


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
