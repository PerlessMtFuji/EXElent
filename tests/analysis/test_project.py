from pathlib import Path

from exelent.analysis.project import analyze_project
from exelent.models import AppKind, OutputMode, Severity


def _make(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_simple_project_end_to_end(tmp_path):
    root = _make(
        tmp_path,
        {
            "main.py": "import requests\nif __name__ == '__main__':\n    print(requests)",
            "util.py": "def h():\n    pass",
        },
    )
    result = analyze_project(root)
    assert result.entry.name == "main.py"
    assert result.app_kind is AppKind.CONSOLE
    assert [d.package for d in result.dependencies] == ["requests"]
    assert result.suggested_name == tmp_path.name


def test_txt_only_project_is_converted(tmp_path):
    root = _make(tmp_path, {"kod.txt": "```python\nprint('hi')\n```"})
    result = analyze_project(root)
    assert "kod.py" in result.converted
    assert result.converted["kod.py"] == "print('hi')"
    assert result.entry.name == "kod.py"


def test_broken_txt_produces_blocker(tmp_path):
    root = _make(tmp_path, {"kod.txt": "def f(:\n    pass"})
    result = analyze_project(root)
    codes = {i.code for i in result.issues}
    assert "txt_syntax_error" in codes


def test_empty_directory_produces_blocker(tmp_path):
    result = analyze_project(_make(tmp_path, {"notatki.txt": "zwykly tekst bez kodu"}))
    codes = {i.code for i in result.issues}
    assert "no_python_found" in codes
    assert result.entry_candidates == ()


def test_other_language_project_is_reported(tmp_path):
    root = _make(tmp_path, {"a.js": "x", "b.js": "y", "c.js": "z"})
    codes = {i.code for i in analyze_project(root).issues}
    assert "other_language" in codes


def test_multiple_unrelated_entry_points_reported(tmp_path):
    root = _make(
        tmp_path,
        {
            "gra.py": "if __name__ == '__main__':\n    print(1)",
            "kalkulator.py": "if __name__ == '__main__':\n    print(2)",
        },
    )
    result = analyze_project(root)
    codes = {i.code for i in result.issues}
    assert "multiple_entry_points" in codes
    assert result.entry_certain is False


def test_gui_project_gets_windowed_and_icon(tmp_path):
    root = _make(
        tmp_path,
        {
            "main.py": "import tkinter\ntkinter.Tk().mainloop()",
            "logo.png": "x",
        },
    )
    result = analyze_project(root)
    assert result.app_kind is AppKind.WINDOWED
    assert result.suggested_icon is not None and result.suggested_icon.name == "logo.png"


def test_writing_program_gets_onedir(tmp_path):
    root = _make(tmp_path, {"main.py": "open('a.txt','w').write('x')"})
    assert analyze_project(root).output_mode is OutputMode.ONEDIR


def test_requirements_file_wins_over_imports(tmp_path):
    root = _make(tmp_path, {"main.py": "import requests", "requirements.txt": "rich==13.7.0\n"})
    assert [d.package for d in analyze_project(root).dependencies] == ["rich==13.7.0"]


def test_hidden_imports_populated_from_dynamic_import(tmp_path):
    root = _make(
        tmp_path,
        {"main.py": "import importlib\nimportlib.import_module('requests')\n"},
    )
    result = analyze_project(root)
    assert "requests" in result.hidden_imports


def test_heavy_package_produces_warning(tmp_path):
    root = _make(tmp_path, {"main.py": "import torch\nprint(torch)"})
    result = analyze_project(root)
    heavy = [i for i in result.issues if i.code == "heavy_packages"]
    assert len(heavy) == 1
    assert "torch" in heavy[0].data["packages"]


def test_broken_txt_alone_is_blocker(tmp_path):
    root = _make(tmp_path, {"kod.txt": "def f(:\n    pass"})
    result = analyze_project(root)
    txt_issues = [i for i in result.issues if i.code == "txt_syntax_error"]
    assert len(txt_issues) == 1
    assert txt_issues[0].severity is Severity.BLOCKER
    assert result.entry is None


def test_broken_txt_alongside_working_source_is_warning(tmp_path):
    root = _make(
        tmp_path,
        {
            "main.py": "if __name__ == '__main__':\n    print('hi')\n",
            "notes.txt": "def f(:\n    pass",
        },
    )
    result = analyze_project(root)
    txt_issues = [i for i in result.issues if i.code == "txt_syntax_error"]
    assert len(txt_issues) == 1
    assert txt_issues[0].severity is Severity.WARNING
    assert result.entry is not None
    assert result.entry.name == "main.py"


def test_short_fenced_program_amid_prose_is_converted(tmp_path):
    root = _make(
        tmp_path,
        {
            "kod.txt": (
                "Hej, tu jest ten program o ktorym mowilismy wczoraj.\n"
                "Powinien dzialac od razu, wklej go do pliku i uruchom:\n\n"
                "```python\n"
                "print('hi')\n"
                "```\n\n"
                "Daj znac czy dziala.\n"
            )
        },
    )
    result = analyze_project(root)
    assert "kod.py" in result.converted
    assert result.converted["kod.py"] == "print('hi')"
    assert result.entry is not None
    assert result.entry.name == "kod.py"


def test_analyze_of_a_single_file_ignores_the_neighbours(tmp_path):
    (tmp_path / "test.txt").write_text("print('czesc')\n", encoding="utf-8")
    (tmp_path / "cudzy_projekt.py").write_text("import torch\n", encoding="utf-8")

    analysis = analyze_project(tmp_path / "test.txt")

    assert analysis.single_file == tmp_path / "test.txt"
    assert [d.package for d in analysis.dependencies] == []
    assert analysis.entry is not None


def test_analyze_of_a_single_file_reports_pulled_in_modules(tmp_path):
    (tmp_path / "main.py").write_text("import helper\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("X = 1\n", encoding="utf-8")

    analysis = analyze_project(tmp_path / "main.py")

    assert analysis.extra_sources == (tmp_path / "helper.py",)


def test_analyze_of_a_directory_is_unchanged(tmp_path):
    root = tmp_path / "projekt"
    root.mkdir()
    (root / "main.py").write_text("print('x')\n", encoding="utf-8")

    analysis = analyze_project(root)

    assert analysis.single_file is None
    assert analysis.extra_sources == ()
