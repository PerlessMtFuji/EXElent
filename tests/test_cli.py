"""Testy `run_build` i `main` — cala sciezka rdzenia bez prawdziwego builda.

Prawdziwe buildy zyja w `tests/test_golden_builds.py` (marker `slow`).
Tutaj sprawdzamy wylacznie to, czego golden testy nie potrafia pokazac:
co `run_build` robi, gdy cos pojdzie nie tak.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from exelent import cli
from exelent.models import (
    AppKind,
    BuildResult,
    Issue,
    OutputMode,
    ProjectAnalysis,
    ScanResult,
    Severity,
)
from exelent.runtime import noop_progress
from exelent.runtime.bootstrap import UvDownloadError
from exelent.runtime.env import BuildEnv


def _project(tmp_path: Path, files: dict[str, str], name: str = "p") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


class _FakeBackend:
    """Backend, ktory nie uruchamia PyInstallera."""

    result = BuildResult(ok=True, artifact=Path("x.exe"), size_bytes=1024)

    def build(self, plan, env, progress, cancel):
        type(self).seen = (plan, env)
        return type(self).result


@pytest.fixture
def stub_build(monkeypatch, tmp_path):
    """Wycina z `run_build` wszystko, co dotyka sieci i dysku systemowego."""
    monkeypatch.setattr(cli, "check_preconditions", lambda **_kw: ())
    monkeypatch.setattr(cli, "materialize_workspace", lambda plan, converted: tmp_path / "ws")
    monkeypatch.setattr(
        cli,
        "create_build_env",
        lambda source, packages, progress: BuildEnv(
            uv=Path("uv.exe"), venv=Path("venv"), python=Path("python.exe")
        ),
    )
    backend = _FakeBackend
    backend.result = BuildResult(ok=True, artifact=tmp_path / "x.exe", size_bytes=1024)
    monkeypatch.setattr(cli, "PyInstallerBackend", backend)
    return backend


# --- carried finding 1: UvDownloadError must not escape as a traceback ---


def test_uv_download_failure_becomes_an_issue_not_a_traceback(tmp_path, monkeypatch):
    """`ensure_uv` rzuca `UvDownloadError`; uzytkownik ma zobaczyc Issue.

    Celowo BEZ zaslepki `create_build_env` — podmieniony jest dopiero
    `ensure_uv`, wiec wyjatek przechodzi przez prawdziwa warstwe runtime.
    """
    root = _project(tmp_path, {"main.py": "print(1)"})
    issue = Issue("uv_download_failed", Severity.BLOCKER)

    def _boom(_progress):
        raise UvDownloadError(issue, OSError("brak polaczenia"))

    monkeypatch.setattr(cli, "check_preconditions", lambda **_kw: ())
    monkeypatch.setattr(cli, "materialize_workspace", lambda plan, converted: tmp_path / "ws")
    monkeypatch.setattr("exelent.runtime.env.ensure_uv", _boom)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["uv_download_failed"]


# --- carried finding 2: env.failed_packages must reach the user ---


def test_failed_packages_are_reported_as_a_warning(tmp_path, monkeypatch, stub_build):
    root = _project(tmp_path, {"main.py": "import requests\nprint(1)"})
    monkeypatch.setattr(
        cli,
        "create_build_env",
        lambda source, packages, progress: BuildEnv(
            uv=Path("uv.exe"),
            venv=Path("venv"),
            python=Path("python.exe"),
            failed_packages=("requests", "nie-ma-takiej-paczki"),
        ),
    )

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is True, "brak jednej paczki nie przerywa builda"
    failed = [i for i in result.issues if i.code == "packages_failed"]
    assert len(failed) == 1
    assert failed[0].severity is Severity.WARNING
    assert "requests" in failed[0].data["packages"]
    assert "nie-ma-takiej-paczki" in failed[0].data["packages"]


def test_no_failed_packages_means_no_warning(tmp_path, stub_build):
    root = _project(tmp_path, {"main.py": "print(1)"})
    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert [i.code for i in result.issues if i.code == "packages_failed"] == []


def test_failed_packages_survive_a_failed_build(tmp_path, monkeypatch, stub_build):
    """Ostrzezenie o paczkach nie moze zniknac tylko dlatego, ze build padl."""
    log = tmp_path / "build.log"
    log.write_text("PermissionError: [WinError 32] used by another process", encoding="utf-8")
    stub_build.result = BuildResult(ok=False, log_path=log)
    monkeypatch.setattr(
        cli,
        "create_build_env",
        lambda source, packages, progress: BuildEnv(
            uv=Path("uv.exe"),
            venv=Path("venv"),
            python=Path("python.exe"),
            failed_packages=("requests",),
        ),
    )

    result = cli.run_build(_project(tmp_path, {"main.py": "print(1)"}), noop_progress)

    codes = [i.code for i in result.issues]
    assert "packages_failed" in codes
    assert "file_in_use" in codes, "log nadal ma byc tlumaczony przez explain_log"


# --- analysis warnings must not be dropped either ---


def test_analysis_warnings_reach_the_result(tmp_path, stub_build):
    code = "import os\nprint('sk-AAAABBBBCCCCDDDDEEEEFFFF')\n"
    root = _project(tmp_path, {"main.py": code})
    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert "secrets_in_code" in [i.code for i in result.issues]


# --- open point: can run_build ever reach make_plan with no entry point? ---


def test_empty_directory_is_stopped_by_a_blocker(tmp_path, stub_build):
    root = _project(tmp_path, {})
    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok is False
    assert [i.code for i in result.issues] == ["no_python_found"]


def test_only_python_file_has_a_syntax_error_still_has_an_entry(tmp_path, stub_build):
    """Zepsuty skladniowo `.py` nadal jest plikiem glownym — `make_plan` nie
    dostaje `None` i nie rzuca `ValueError`."""
    root = _project(tmp_path, {"main.py": "def ( to nie jest python\n"})
    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok is True
    assert "no_entry_point" not in [i.code for i in result.issues]


def test_txt_that_cannot_be_converted_is_a_blocker(tmp_path, stub_build):
    root = _project(tmp_path, {"kod.txt": "def ( to nie jest python\n"})
    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok is False
    assert result.issues and all(i.severity is Severity.BLOCKER for i in result.issues)


def test_missing_entry_without_a_blocker_is_reported_not_crashed(tmp_path, monkeypatch):
    """Ostatnia linia obrony: gdyby analiza kiedykolwiek oddala `entry=None`
    bez BLOCKERa, uzytkownik ma dostac Issue, a nie `ValueError`."""
    root = _project(tmp_path, {"main.py": "print(1)"})
    empty = ProjectAnalysis(root=root, scan=ScanResult(root=root), suggested_name="p")
    monkeypatch.setattr(cli, "analyze_project", lambda _root: empty)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["no_entry_point"]


# --- overrides plumbed from the command line ---


def test_overrides_reach_the_plan(tmp_path, stub_build):
    root = _project(tmp_path, {"main.py": "print(1)"})
    cli.run_build(
        root,
        noop_progress,
        exe_name="Inna Nazwa",
        dest_dir=tmp_path / "out",
        output_mode=OutputMode.ONEDIR,
        app_kind=AppKind.WINDOWED,
    )
    plan, _env = stub_build.seen
    assert plan.exe_name == "Inna Nazwa"
    assert plan.dest_dir == tmp_path / "out"
    assert plan.output_mode is OutputMode.ONEDIR
    assert plan.app_kind is AppKind.WINDOWED


def test_precondition_failure_short_circuits(tmp_path, monkeypatch, stub_build):
    root = _project(tmp_path, {"main.py": "print(1)"})
    monkeypatch.setattr(
        cli, "check_preconditions", lambda **_kw: (Issue("no_network", Severity.BLOCKER),)
    )
    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok is False
    assert [i.code for i in result.issues] == ["no_network"]


# --- main() ---


def test_main_returns_zero_and_prints_artifact(tmp_path, monkeypatch, capsys):
    artifact = tmp_path / "out" / "p.exe"
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda *a, **kw: BuildResult(ok=True, artifact=artifact, size_bytes=5 * 1024**2),
    )
    code = cli.main([str(tmp_path), "--name", "p", "--out", str(tmp_path / "out")])
    assert code == 0
    assert str(artifact) in capsys.readouterr().out


def test_main_reports_a_onedir_artifact_without_crashing(tmp_path, monkeypatch, capsys):
    """ONEDIR oddaje katalog, nie plik — `size_bytes` musi byc policzone."""
    folder = tmp_path / "out" / "p"
    folder.mkdir(parents=True)
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda *a, **kw: BuildResult(ok=True, artifact=folder, size_bytes=12 * 1024**2),
    )
    assert cli.main([str(tmp_path)]) == 0
    assert "12.0 MB" in capsys.readouterr().out


def test_main_returns_one_and_lists_issue_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda *a, **kw: BuildResult(
            ok=False, issues=(Issue("no_network", Severity.BLOCKER),), log_path=tmp_path / "b.log"
        ),
    )
    assert cli.main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "no_network" in err
    assert "b.log" in err


def test_main_surfaces_warnings_of_a_successful_build(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda *a, **kw: BuildResult(
            ok=True,
            artifact=tmp_path / "p.exe",
            issues=(Issue("packages_failed", Severity.WARNING, {"packages": "requests"}),),
        ),
    )
    assert cli.main([str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "packages_failed" in captured.out + captured.err
