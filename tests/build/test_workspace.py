from pathlib import Path

from exelent.build.workspace import materialize_workspace
from exelent.models import AppKind, BuildPlan, OutputMode


def _plan(root: Path, dest: Path) -> BuildPlan:
    return BuildPlan(
        root=root,
        entry=root / "main.py",
        app_kind=AppKind.CONSOLE,
        output_mode=OutputMode.ONEFILE,
        exe_name="Program",
        dest_dir=dest,
    )


def test_source_directory_is_never_modified(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    before = {p.name for p in root.iterdir()}

    materialize_workspace(_plan(root, tmp_path / "out"), {})

    assert {p.name for p in root.iterdir()} == before


def test_excluded_directories_are_not_copied(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "big.py").write_text("x", encoding="utf-8")
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    workspace = materialize_workspace(_plan(root, tmp_path / "out"), {})

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

    workspace = materialize_workspace(_plan(root, tmp_path / "out"), {})

    assert (workspace / "main.py").exists()
    assert not (workspace / ".hidden").exists()


def test_converted_text_files_are_written_to_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "kod.txt").write_text("cokolwiek", encoding="utf-8")

    workspace = materialize_workspace(_plan(root, tmp_path / "out"), {"kod.py": "print('ok')"})

    assert (workspace / "kod.py").read_text(encoding="utf-8") == "print('ok')"
    assert not (root / "kod.py").exists()


def test_workspace_is_cleaned_between_builds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    first = materialize_workspace(_plan(root, tmp_path / "out"), {})
    (first / "smiec.py").write_text("stare", encoding="utf-8")
    second = materialize_workspace(_plan(root, tmp_path / "out"), {})

    assert not (second / "smiec.py").exists()


def test_workspace_path_is_ascii(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / "zażółć gęślą"
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")

    workspace = materialize_workspace(_plan(root, tmp_path / "out"), {})

    assert str(workspace.relative_to(tmp_path / "state")).isascii()


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

    workspace = materialize_workspace(plan, {})

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
