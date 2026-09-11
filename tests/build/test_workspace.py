import hashlib
from pathlib import Path

import pytest

from exelent.build.workspace import materialize_workspace
from exelent.models import AppKind, BuildPlan, IssueError, OutputMode, SourceEntry


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _plan(
    root: Path,
    dest: Path | None = None,
    *,
    entry: Path | None = None,
    single_file: Path | None = None,
    extra: tuple[Path, ...] = (),
    converted: tuple[tuple[str, str], ...] = (),
    source_inventory: tuple[SourceEntry, ...] = (),
) -> BuildPlan:
    return BuildPlan(
        root=root,
        entry=entry or root / "main.py",
        app_kind=AppKind.CONSOLE,
        output_mode=OutputMode.ONEFILE,
        exe_name="Program",
        dest_dir=dest or root.parent / "out",
        single_file=single_file,
        extra_sources=extra,
        converted=converted,
        source_inventory=source_inventory,
    )


def test_source_directory_is_never_modified(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    before = {p.name for p in root.iterdir()}

    materialize_workspace(_plan(root, tmp_path / "out"))

    assert {p.name for p in root.iterdir()} == before


def test_excluded_directories_are_not_copied(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "big.py").write_text("x", encoding="utf-8")
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    workspace = materialize_workspace(_plan(root, tmp_path / "out"))

    assert (workspace / "main.py").exists()
    assert not (workspace / ".venv").exists()


def test_dot_directories_are_not_copied(tmp_path, monkeypatch):
    """R6: aligns with the scanner (exelent/analysis/scanner.py), which skips
    any directory whose name starts with a dot in addition to EXCLUDED_DIRS —
    e.g. a plain .git that isn't in the named exclusion list."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    (root / ".hidden" / "sub").mkdir(parents=True)
    (root / ".hidden" / "sub" / "secret.py").write_text("x", encoding="utf-8")
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    workspace = materialize_workspace(_plan(root, tmp_path / "out"))

    assert (workspace / "main.py").exists()
    assert not (workspace / ".hidden").exists()


def test_converted_text_files_are_written_to_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "kod.txt").write_text("cokolwiek", encoding="utf-8")

    plan = _plan(root, tmp_path / "out", converted=(("kod.py", "print('ok')"),))
    workspace = materialize_workspace(plan)

    assert (workspace / "kod.py").read_text(encoding="utf-8") == "print('ok')"
    assert not (root / "kod.py").exists()


def test_workspace_is_cleaned_between_builds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    first = materialize_workspace(_plan(root, tmp_path / "out"))
    (first / "smiec.py").write_text("stare", encoding="utf-8")
    second = materialize_workspace(_plan(root, tmp_path / "out"))

    assert not (second / "smiec.py").exists()


def test_workspace_path_is_ascii(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "zażółć gęślą"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    workspace = materialize_workspace(_plan(root, tmp_path / "out"))

    assert str(workspace.relative_to(tmp_path / "state")).isascii()


def test_single_file_workspace_copies_only_the_relevant_files(tmp_path, monkeypatch):
    """Bez tego `copytree` kopiuje CALE Pobrane do %LOCALAPPDATA%."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    downloads = tmp_path / "Pobrane"
    downloads.mkdir()
    (downloads / "test.py").write_text("import helper\n", encoding="utf-8")
    (downloads / "helper.py").write_text("X = 1\n", encoding="utf-8")
    (downloads / "wielki_film.mp4").write_bytes(b"x" * 5000)
    (downloads / "cudzy.py").write_text("Y = 2\n", encoding="utf-8")

    plan = _plan(
        root=downloads,
        entry=downloads / "test.py",
        single_file=downloads / "test.py",
        extra=(downloads / "helper.py",),
    )
    workspace = materialize_workspace(plan)

    assert (workspace / "test.py").exists()
    assert (workspace / "helper.py").exists()
    assert not (workspace / "wielki_film.mp4").exists()
    assert not (workspace / "cudzy.py").exists()


# --- odrocze minor M6 (Task 15): jedno miejsce, ktore wie, gdzie jest kopia ---


def test_backend_works_in_the_workspace_that_was_materialized(tmp_path, monkeypatch):
    """Kopia robocza ma JEDNO zrodlo prawdy.

    `materialize_workspace` zwracalo sciezke, ktora `cli` ignorowalo, a
    `pyinstaller.py` liczylo ja po raz drugi z tych samych skladnikow. Dwie
    niezalezne definicje tego samego trzymaly sie razem wylacznie przez
    zbieg okolicznosci: zmiana jednej („src" na cos innego) daje build
    uruchomiony w katalogu, w ktorym nie ma kodu — a to wychodzi dopiero
    po kilkunastu minutach pracy PyInstallera.

    Test jest CHARAKTERYZUJACY (przechodzi takze przed poprawka), wiec jego
    wartosc mierzy mutant M-M6, nie kolor przy pisaniu.
    """
    import pytest

    from exelent.build.backend import CancelToken
    from exelent.build.launcher import LAUNCHER_FILENAME
    from exelent.build.pyinstaller import PyInstallerBackend
    from exelent.runtime import noop_progress
    from exelent.runtime.env import BuildEnv

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    plan = _plan(root, tmp_path / "out")

    workspace = materialize_workspace(plan)

    env = BuildEnv(
        uv=tmp_path / "uv.exe",
        venv=tmp_path / "venv",
        python=tmp_path / "nie-ma-takiego-pythona.exe",
    )
    # Launcher powstaje ZANIM ruszy PyInstaller, wiec brak interpretera
    # zatrzymuje build dokladnie za miejscem, ktore ten test mierzy.
    with pytest.raises(OSError):
        PyInstallerBackend().build(plan, env, noop_progress, CancelToken())

    assert (workspace / LAUNCHER_FILENAME).exists(), (
        "backend pracowal w innym katalogu niz ten, ktory dostal kopie kodu"
    )


# --- B08: inwentarz i weryfikacja hashów ---


def test_inventory_copies_only_listed_files(tmp_path, monkeypatch):
    """B08: plik NIE wymieniony w inwentarzu nie trafia do workspace, nawet
    jeśli leży w katalogu projektu. Chroni przed przypadkowym dołączeniem
    pliku dodanego po analizie."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    main_content = b"print(1)"
    (root / "main.py").write_bytes(main_content)
    (root / "nowy.py").write_text("print('dodany po analizie')", encoding="utf-8")

    inventory = (SourceEntry(rel_path="main.py", sha256=_sha(main_content)),)
    plan = _plan(root, source_inventory=inventory)
    workspace = materialize_workspace(plan)

    assert (workspace / "main.py").exists()
    assert not (workspace / "nowy.py").exists()


def test_inventory_verifies_hash_and_raises_on_mismatch(tmp_path, monkeypatch):
    """B08: plik zmieniony po analizie blokuje build — hash się nie zgadza."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    # Inwentarz z hashem STAREJ treści, ale plik się zmienił:
    old_hash = _sha(b"print('stary')")
    inventory = (SourceEntry(rel_path="main.py", sha256=old_hash),)
    plan = _plan(root, source_inventory=inventory)

    with pytest.raises(IssueError) as exc_info:
        materialize_workspace(plan)

    assert exc_info.value.issue.code == "source_changed_after_analysis"


def test_inventory_raises_on_deleted_file(tmp_path, monkeypatch):
    """B08: plik usunięty po analizie blokuje build."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    inventory = (
        SourceEntry(rel_path="main.py", sha256=_sha(b"print(1)")),
        SourceEntry(rel_path="helper.py", sha256=_sha(b"X = 1")),
    )
    plan = _plan(root, source_inventory=inventory)

    with pytest.raises(IssueError) as exc_info:
        materialize_workspace(plan)

    assert "usunięty" in exc_info.value.issue.data["files"]


def test_inventory_happy_path_copies_and_verifies(tmp_path, monkeypatch):
    """B08: inwentarz z poprawnymi hashami — pliki są skopiowane, brak błędu."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    main_content = b"print(1)"
    data_content = b'{"key": "value"}'
    (root / "main.py").write_bytes(main_content)
    (root / "dane.json").write_bytes(data_content)

    inventory = (
        SourceEntry(rel_path="dane.json", sha256=_sha(data_content)),
        SourceEntry(rel_path="main.py", sha256=_sha(main_content)),
    )
    plan = _plan(root, source_inventory=inventory)
    workspace = materialize_workspace(plan)

    assert (workspace / "main.py").read_bytes() == main_content
    assert (workspace / "dane.json").read_bytes() == data_content


def test_inventory_with_converted_txt_writes_code(tmp_path, monkeypatch):
    """B08: konwersja TXT->PY nadpisuje workspace po skopiowaniu inwentarza."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    txt_content = b"```python\nprint('hi')\n```\n"
    (root / "main.py").write_text("import kod", encoding="utf-8")
    (root / "kod.txt").write_bytes(txt_content)

    inventory = (
        SourceEntry(rel_path="kod.txt", sha256=_sha(txt_content)),
        SourceEntry(rel_path="main.py", sha256=_sha(b"import kod")),
    )
    plan = _plan(
        root,
        source_inventory=inventory,
        converted=(("kod.py", "print('hi')"),),
    )
    workspace = materialize_workspace(plan)

    assert (workspace / "kod.py").read_text(encoding="utf-8") == "print('hi')"
    assert (workspace / "main.py").exists()


def test_empty_hash_skips_verification(tmp_path, monkeypatch):
    """B08: plik, którego nie dało się odczytać przy analizie (pusty hash),
    jest kopiowany bez weryfikacji — brak dowodu ≠ dowód braku."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    inventory = (SourceEntry(rel_path="main.py", sha256=""),)
    plan = _plan(root, source_inventory=inventory)
    workspace = materialize_workspace(plan)

    assert (workspace / "main.py").exists()
