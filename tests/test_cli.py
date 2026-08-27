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
from exelent.runtime.env import BuildEnv, BuildEnvError


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
    # Bez tej asercji test przechodzil takze przy CALKOWICIE rozwalonym
    # buildzie: "brak ostrzezenia o paczkach" jest prawda takze wtedy, gdy
    # nie ma zadnego wyniku. Zielony z niewlasciwego powodu.
    assert result.ok is True, [i.code for i in result.issues]
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
    assert result.ok is True, [i.code for i in result.issues]
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


# --- Critical C1/C2: `run_build` jest granica wyjatkow, nie zbiorem trzech lapek ---


def test_workspace_copy_failure_becomes_an_issue_not_a_traceback(tmp_path, monkeypatch, stub_build):
    """Dokladnie lancuch z komentarza w pyinstaller.py: uzytkownik anuluje
    build, plik zostaje niedokasowany, a `copytree(dirs_exist_ok=False)`
    wywala `FileExistsError [WinError 183]` przy kolejnej probie."""
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _boom(_plan, _converted):
        raise FileExistsError(17, "Cannot create a file when that file already exists")

    monkeypatch.setattr(cli, "materialize_workspace", _boom)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert result.issues, "cicha porazka bez zadnego Issue jest gorsza niz traceback"


def test_a_locked_source_file_is_diagnosed_by_its_windows_error(tmp_path, monkeypatch, stub_build):
    """Kod bledu systemu niesie diagnoze — nie ma powodu gubic jej tylko
    dlatego, ze wyjatek przyszedl z kopiowania, a nie z logu PyInstallera."""
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _boom(_plan, _converted):
        raise PermissionError(13, "Access is denied", str(root / "main.py"), 32)

    monkeypatch.setattr(cli, "materialize_workspace", _boom)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert "file_in_use" in [i.code for i in result.issues]


def test_env_setup_failure_reaches_the_user_as_an_issue(tmp_path, monkeypatch, stub_build):
    root = _project(tmp_path, {"main.py": "print(1)"})
    issue = Issue("env_setup_failed", Severity.BLOCKER, {"step": "create_env"})

    def _boom(_source, _packages, _progress):
        raise BuildEnvError(issue, RuntimeError("uv venv padlo"))

    monkeypatch.setattr(cli, "create_build_env", _boom)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["env_setup_failed"]


def test_an_unexpected_backend_failure_is_reported_not_raised(tmp_path, monkeypatch, stub_build):
    """Granica musi byc szeroka. Waskie lapki na dwa wymyslone z nazwy typy
    zostawiaja kazdy inny wyjatek na twarzy laika."""
    root = _project(tmp_path, {"main.py": "print(1)"})

    class _Exploding:
        def build(self, plan, env, progress, cancel):
            raise RuntimeError("cos, czego nikt nie przewidzial")

    monkeypatch.setattr(cli, "PyInstallerBackend", _Exploding)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["unexpected_error"]


def test_failed_packages_survive_an_unexpected_crash(tmp_path, monkeypatch, stub_build):
    """Ta sama zasada co przy porazce builda: czesciowa instalacja jest czesto
    prawdziwa przyczyna tego, co padlo linijke pozniej."""
    root = _project(tmp_path, {"main.py": "print(1)"})
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

    class _Exploding:
        def build(self, plan, env, progress, cancel):
            raise RuntimeError("bum")

    monkeypatch.setattr(cli, "PyInstallerBackend", _Exploding)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert "packages_failed" in [i.code for i in result.issues]


# --- Important I1: BLOCKER zawsze przed przeniesionym ostrzezeniem ---


def test_blockers_are_listed_before_carried_warnings(tmp_path, monkeypatch, stub_build):
    """`explain_log` obiecuje w docstringu 'Blockers sort first' — zadanie 20
    pokazuje pierwszy Issue najbardziej prominentnie. Doklejenie ostrzezen
    analizy z przodu robi z 'w kodzie jest klucz dostepu' naglowek awarii
    builda, ktora naprawde spowodowal zablokowany plik."""
    root = _project(tmp_path, {"main.py": "import os\nprint('sk-AAAABBBBCCCCDDDDEEEEFFFF')\n"})
    log = tmp_path / "build.log"
    log.write_text("PermissionError: [WinError 32] used by another process", encoding="utf-8")
    stub_build.result = BuildResult(ok=False, log_path=log)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    codes = [i.code for i in result.issues]
    assert "secrets_in_code" in codes and "file_in_use" in codes
    assert result.issues[0].severity is Severity.BLOCKER
    assert codes.index("file_in_use") < codes.index("secrets_in_code")


# --- Critical C3: granica wyjatkow obejmuje ANALIZE, nie tylko sam build ---


def test_an_unreadable_source_file_is_an_issue_not_a_traceback(tmp_path, monkeypatch, stub_build):
    """`analyze_project` czyta KAZDY plik uzytkownika bez straznika.

    Runda 1 przesunela granice wyjatkow tak, ze obejmuje build — ale analiza
    stoi przed nia i jest pierwsza linia `run_build`. Jeden plik z odmowa
    dostepu (ACL, plik OneDrive dostepny tylko w chmurze) daje laikowi surowy
    traceback. Potwierdzone `icacls /deny` na tej maszynie.
    """
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _denied(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr("exelent.analysis.project._read", _denied)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["access_denied"]


# --- Important I6: make_plan i check_preconditions tez stoja poza granica ---


def test_an_unknown_override_is_reported_not_raised(tmp_path, stub_build):
    """GUI (zadania 19/20) jest wolajacym, ktory podaje kwargi. Literowka w
    nazwie opcji nie moze konczyc sie `TypeError` na wierzchu."""
    root = _project(tmp_path, {"main.py": "print(1)"})

    result = cli.run_build(root, noop_progress, nie_ma_takiej_opcji=1)

    assert result.ok is False
    assert [i.code for i in result.issues] == ["unexpected_error"]


def test_a_failing_precondition_probe_is_reported_not_raised(tmp_path, monkeypatch, stub_build):
    """`check_preconditions` robi `shutil.disk_usage` — to potrafi rzucic."""
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _boom(**_kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cli, "check_preconditions", _boom)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["disk_full"]


def test_a_failing_dest_probe_is_reported_not_raised(tmp_path, monkeypatch, stub_build):
    """`make_plan` robi teraz wiecej I/O niz przed runda 1: sonda
    zapisywalnosci na wielu kandydatach i wywolanie Win32."""
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _boom(_path):
        raise OSError(1920, "The file cannot be accessed by the system")

    monkeypatch.setattr("exelent.planning._is_writable", _boom)

    result = cli.run_build(root, noop_progress)

    assert result.ok is False
    # Asercja na KONKRETNY kod, nie na "sa jakies Issue": ta slabsza wersja
    # przeszla by rowniez z bledna diagnoza, czyli z defektem na wierzchu.
    # WinError 1920 bez dowodu na chmure ma zostac NEUTRALNY — nazwanie tego
    # antywirusem byloby pewna siebie bzdura, a `unexpected_error` gubiloby
    # informacje, ktora system podal wprost.
    assert [i.code for i in result.issues] == ["access_denied"]


# --- Minor M13: BLOCKER analizy nie moze gubic jej ostrzezen ---


def test_analysis_warnings_are_not_dropped_by_a_blocker(tmp_path, monkeypatch, stub_build):
    """Reszta `run_build` niesie `carried` wszedzie — ta jedna sciezka nie."""
    root = _project(tmp_path, {"main.py": "print(1)"})
    analysis = ProjectAnalysis(
        root=root,
        scan=ScanResult(root=root),
        suggested_name="p",
        issues=(
            Issue("scan_truncated", Severity.WARNING, {"files": "5000"}),
            Issue("no_python_found", Severity.BLOCKER, {"dir": "p"}),
        ),
    )
    monkeypatch.setattr(cli, "analyze_project", lambda _root: analysis)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["no_python_found", "scan_truncated"]


# --- Minor M11: sciezka do logu nie moze zginac razem z wyjatkiem ---


def test_the_log_path_survives_a_crash_after_the_log_was_written(tmp_path, monkeypatch, stub_build):
    """Zadanie 20 podpina pod "Zapisz raport" wlasnie `result.log_path`."""
    from exelent.build.pyinstaller import log_path_for

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = _project(tmp_path, {"main.py": "print(1)"})

    class _WritesLogThenExplodes:
        def build(self, plan, env, progress, cancel):
            log = log_path_for(plan)
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("PyInstaller: cokolwiek\n", encoding="utf-8")
            raise RuntimeError("bum juz po zapisaniu logu")

    monkeypatch.setattr(cli, "PyInstallerBackend", _WritesLogThenExplodes)

    result = cli.run_build(root, noop_progress, exe_name="p", dest_dir=tmp_path / "out")

    assert result.ok is False
    assert result.log_path is not None, "uzytkownik nie ma czego dolaczyc do zgloszenia"
    assert result.log_path.exists()
    assert "PyInstaller" in result.log_path.read_text(encoding="utf-8")


def test_a_log_from_a_previous_build_is_never_passed_off_as_this_one(
    tmp_path, monkeypatch, stub_build
):
    """Log poprzedniej, zupelnie innej awarii jest gorszy niz brak logu:
    uzytkownik dolaczylby go do zgloszenia, a zadanie 20 pokazaloby przycisk
    "Zapisz raport" nad trescia, ktora nie ma nic wspolnego z tym bledem."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = _project(tmp_path, {"main.py": "print(1)"})

    # Sciezka LICZONA, nie przepisana: recznie zlozone `logs_dir() / "p.log"`
    # przestalo byc czymkolwiek, gdy M18 dodalo do nazwy skrot sciezki
    # projektu — test pisal wtedy plik, ktorego nikt nie czyta, i przechodzil
    # rowniez z calkowicie skasowanym `_clear_stale_log`.
    stale = _log_path(root, exe_name="p", dest_dir=tmp_path / "out")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("log poprzedniego builda", encoding="utf-8")

    class _Exploding:
        def build(self, plan, env, progress, cancel):
            raise RuntimeError("bum przed zapisaniem czegokolwiek")

    monkeypatch.setattr(cli, "PyInstallerBackend", _Exploding)

    result = cli.run_build(root, noop_progress, exe_name="p", dest_dir=tmp_path / "out")

    assert result.log_path is None


# --- Minor M12: ok=True bez artefaktu to sprzecznosc, nie komunikat o porazce ---


def test_run_build_never_reports_success_without_an_artifact(tmp_path, stub_build):
    stub_build.result = BuildResult(ok=True, artifact=None, size_bytes=0)
    root = _project(tmp_path, {"main.py": "print(1)"})

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert "artifact_vanished" in [i.code for i in result.issues]


def test_main_does_not_call_a_result_that_says_ok_a_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_build", lambda *a, **kw: BuildResult(ok=True, artifact=None))

    code = cli.main([str(tmp_path)])

    err = capsys.readouterr().err
    assert code == 1
    assert "nie powiodl" not in err.lower(), "komunikat przeczy fladze ok=True"
    assert "bez pliku wynikowego" in err.lower()


# --- Critical C4: etap analizy nie dostaje diagnoz z tabeli pisanej na logi ---


def _log_path(root, **overrides):
    """Sciezka logu wyliczona tak, jak zrobi to `run_build` — bez zgadywania nazwy."""
    from exelent.analysis.project import analyze_project
    from exelent.build.pyinstaller import log_path_for
    from exelent.planning import make_plan

    return log_path_for(make_plan(analyze_project(root), **overrides))


def test_a_cloud_only_file_is_not_blamed_on_the_antivirus(tmp_path, monkeypatch, stub_build):
    """OneDrive Files On-Demand jest wlaczone domyslnie. Plik trzymany tylko w
    chmurze daje przy odczycie WinError 1920, a rada "wylacz antywirusa" jest
    wtedy pewna siebie i BLEDNA: laik traci godzine, a build dalej pada."""
    onedrive = tmp_path / "OneDrive"
    root = onedrive / "projekt"
    root.mkdir(parents=True)
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    monkeypatch.setenv("OneDrive", str(onedrive))

    def _cloud_denied(path):
        raise PermissionError(13, "The file cannot be accessed by the system", str(path), 1920)

    monkeypatch.setattr("exelent.analysis.project._read", _cloud_denied)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    codes = [i.code for i in result.issues]
    assert result.ok is False
    assert "antivirus_blocked" not in codes, "zla rada jest gorsza niz brak rady"
    assert "cloud_file_unavailable" in codes


def test_the_same_error_outside_the_cloud_stays_neutral(tmp_path, monkeypatch, stub_build):
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _denied(path):
        raise PermissionError(13, "The file cannot be accessed by the system", str(path), 1920)

    monkeypatch.setattr("exelent.analysis.project._read", _denied)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert [i.code for i in result.issues] == ["access_denied"]


# --- Important I8: build, ktory nie ruszyl, nie moze niszczyc logu poprzedniego ---


def test_a_precondition_failure_leaves_the_previous_log_alone(tmp_path, monkeypatch, stub_build):
    """Zadanie 20 podpina pod "Zapisz raport" wlasnie `log_path`. Proba builda
    bez internetu nic nie buduje, wiec nie ma czego kasowac."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = _project(tmp_path, {"main.py": "print(1)"})
    overrides = {"exe_name": "p", "dest_dir": tmp_path / "out"}

    previous = _log_path(root, **overrides)
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_text("log poprzedniego przebiegu", encoding="utf-8")

    monkeypatch.setattr(
        cli, "check_preconditions", lambda **_kw: (Issue("no_network", Severity.BLOCKER),)
    )

    result = cli.run_build(root, noop_progress, **overrides)

    assert [i.code for i in result.issues] == ["no_network"]
    assert previous.exists(), "porazka przed startem builda skasowala cudzy log"
    assert previous.read_text(encoding="utf-8") == "log poprzedniego przebiegu"


# --- Minor M15: nie diagnozujemy po TYPIE wyjatku nad wolaniem pelnym I/O ---


def test_a_value_error_from_the_dest_probe_is_not_called_a_missing_entry(
    tmp_path, monkeypatch, stub_build
):
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _boom(_path):
        raise ValueError("embedded null byte")

    monkeypatch.setattr("exelent.planning._is_writable", _boom)

    result = cli.run_build(root, noop_progress)

    codes = [i.code for i in result.issues]
    assert "no_entry_point" not in codes, "pewna siebie i bledna diagnoza"
    assert codes == ["unexpected_error"]


# --- Minor M17: sciezka artifact_vanished nie moze gubic wiedzy backendu ---


def test_a_vanished_artifact_keeps_what_the_backend_already_knew(tmp_path, monkeypatch, stub_build):
    log = tmp_path / "b.log"
    log.write_text("cos z builda", encoding="utf-8")
    stub_build.result = BuildResult(
        ok=True,
        artifact=None,
        duration_s=12.5,
        log_path=log,
        issues=(Issue("recursion_limit", Severity.WARNING),),
    )
    root = _project(tmp_path, {"main.py": "print(1)"})

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    codes = [i.code for i in result.issues]
    assert result.ok is False
    assert "artifact_vanished" in codes
    assert "recursion_limit" in codes, "backend wiedzial cos wiecej i to zginelo"
    assert result.duration_s == 12.5
    assert result.log_path == log


# --- Minor M18: log nalezy do PROJEKTU, nie do samej nazwy EXE ---


def test_two_projects_with_the_same_exe_name_do_not_share_one_log(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    a = _project(tmp_path, {"main.py": "print(1)"}, name="projekt-a")
    b = _project(tmp_path, {"main.py": "print(2)"}, name="projekt-b")

    log_a = _log_path(a, exe_name="program", dest_dir=tmp_path / "o1")
    log_b = _log_path(b, exe_name="program", dest_dir=tmp_path / "o2")

    assert log_a != log_b, "build jednego projektu kasuje log drugiego"


# --- Critical C5: przebieg, ktory nie zaczal budowac, nie ma wlasnego logu ---


def test_a_precondition_failure_does_not_hand_over_the_previous_log(
    tmp_path, monkeypatch, stub_build
):
    """I8 slusznie przestal KASOWAC cudzy log, ale ten sam przebieg zaczal go
    PODAWAC jako swoj: `_fail` liczy log ze znanego juz `plan`. Zadanie 20
    podpina pod `log_path` przycisk "Zapisz raport", wiec uzytkownik dolaczylby
    do zgloszenia log zupelnie innej awarii. Obie wlasnosci sa prawdziwe naraz:
    nie niszcz cudzego logu i nie podawaj go za swoj."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = _project(tmp_path, {"main.py": "print(1)"})
    overrides = {"exe_name": "p", "dest_dir": tmp_path / "out"}

    previous = _log_path(root, **overrides)
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_text("log poprzedniej, zupelnie innej awarii", encoding="utf-8")

    monkeypatch.setattr(
        cli, "check_preconditions", lambda **_kw: (Issue("no_network", Severity.BLOCKER),)
    )

    result = cli.run_build(root, noop_progress, **overrides)

    assert result.log_path is None, "cudzy log podany jako log tego przebiegu"
    assert previous.exists(), "a jednoczesnie nie wolno go skasowac"


# --- Minor M19: siatka bezpieczenstwa nie moze zakladac ksztaltu tego, co lapie ---


def test_the_safety_net_survives_an_exception_with_a_non_text_filename(
    tmp_path, monkeypatch, stub_build
):
    """`OSError.filename` bywa bajtami (albo deskryptorem). Siatka, ktora sama
    rzuca `TypeError`, przestaje byc siatka — uzytkownik dostaje traceback."""
    root = _project(tmp_path, {"main.py": "print(1)"})

    def _denied_with_bytes(path):
        raise PermissionError(13, "Access is denied", str(path).encode(), 5)

    monkeypatch.setattr("exelent.analysis.project._read", _denied_with_bytes)

    result = cli.run_build(root, noop_progress, dest_dir=tmp_path / "out")

    assert result.ok is False
    assert [i.code for i in result.issues] == ["access_denied"]
