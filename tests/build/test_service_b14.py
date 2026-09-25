"""B14: usługa rdzenia, sesje i sprzątanie.

Testy weryfikują:
- `execute_build` mieszka w `build.service`, nie w `cli`
- Backend jest wstrzykiwany przez parametr
- Sprzątanie osieroconych sesji oparte na PID
- Staging publikacji sprzątany przy błędzie weryfikacji
- Numer próby builda izoluje logi ponowionych prób
- Weryfikacja integralności uv
- Sprzątanie logów sesji
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from exelent.build.service import execute_build
from exelent.models import BuildPlan, BuildResult, OutputMode
from exelent.runtime import noop_progress
from exelent.runtime.env import BuildEnv

# --- B14: execute_build z wstrzykniętym backendem ---


class _CountingBackend:
    """Backend, który liczy wywołania i oddaje stały wynik."""

    calls: int = 0

    def build(self, plan, env, progress, cancel):
        type(self).calls += 1
        return BuildResult(ok=True, artifact=plan.dest_dir / f"{plan.exe_name}.exe", size_bytes=42)


def _stub_service(monkeypatch, tmp_path):
    """Zasłania sieć i dysk w `service` (odpowiednik `stub_build` z test_cli)."""
    from exelent.build import service

    monkeypatch.setattr(service, "check_preconditions", lambda **_kw: ())
    monkeypatch.setattr(service, "materialize_workspace", lambda plan, cancel=None: tmp_path / "ws")
    monkeypatch.setattr(
        service,
        "create_build_env",
        lambda source, packages, progress, **_kw: BuildEnv(
            uv=Path("uv.exe"), venv=Path("venv"), python=Path("python.exe")
        ),
    )
    monkeypatch.setattr(service, "validate_target_syntax", lambda *_a, **_kw: None)


def test_injected_backend_is_used_instead_of_pyinstaller(tmp_path, monkeypatch):
    """B14: backend wstrzyknięty przez parametr jest używany zamiast domyślnego."""
    _stub_service(monkeypatch, tmp_path)
    _CountingBackend.calls = 0
    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")

    plan = BuildPlan(
        root=root,
        entry=root / "main.py",
        app_kind="console",
        output_mode=OutputMode.ONEDIR,
        exe_name="test",
        dest_dir=tmp_path / "out",
    )
    result = execute_build(plan, noop_progress, backend=_CountingBackend())
    assert _CountingBackend.calls == 1
    assert result.ok is True


def test_default_backend_is_pyinstaller_when_none_given(tmp_path, monkeypatch):
    """Bez parametru `backend` usługa tworzy PyInstallerBackend."""
    from exelent.build import service

    _stub_service(monkeypatch, tmp_path)
    seen_backend = []

    def spy(plan, carried, progress, cancel, backend):
        seen_backend.append(type(backend).__name__)
        # Nie uruchamiamy prawdziwego buildu
        return BuildResult(ok=True, artifact=plan.dest_dir / "x.exe", size_bytes=1)

    monkeypatch.setattr(service, "_build", spy)

    root = tmp_path / "proj"
    root.mkdir()
    plan = BuildPlan(
        root=root,
        entry=root / "main.py",
        app_kind="console",
        output_mode=OutputMode.ONEDIR,
        exe_name="test",
        dest_dir=tmp_path / "out",
    )
    execute_build(plan, noop_progress)
    assert seen_backend == ["PyInstallerBackend"]


def test_execute_build_lives_in_service_not_cli():
    """B14: GUI nie importuje orkiestracji z adaptera konsolowego."""
    from exelent.build import service
    from exelent.ui import worker

    # worker.py importuje z service, nie z cli
    assert worker.execute_build is service.execute_build


# --- B14: sprzątanie sesji ---


def test_register_session_creates_pid_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exelent.runtime import paths

    paths.register_session()
    pid_path = paths._pid_file()
    assert pid_path.exists()
    assert pid_path.read_text(encoding="utf-8").strip() == str(os.getpid())


def test_clean_stale_sessions_removes_dead_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exelent.runtime import paths

    # Symuluj osierocony katalog i plik PID z martwym PID
    base = tmp_path / paths.APP_NAME / "b"
    base.mkdir(parents=True)
    dead_sid = "deadbeef"
    (base / f"abc12345-{dead_sid}").mkdir()
    (base / f"abc12345-{dead_sid}" / "src").mkdir()
    (base / f".pid-{dead_sid}").write_text("999999999", encoding="utf-8")

    paths.clean_stale_sessions()

    assert not (base / f"abc12345-{dead_sid}").exists()
    assert not (base / f".pid-{dead_sid}").exists()


def test_clean_stale_sessions_preserves_alive_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exelent.runtime import paths

    base = tmp_path / paths.APP_NAME / "b"
    base.mkdir(parents=True)
    alive_sid = "alive123"
    work = base / f"abc12345-{alive_sid}"
    work.mkdir()
    # PID bieżącego procesu — na pewno żyje
    (base / f".pid-{alive_sid}").write_text(str(os.getpid()), encoding="utf-8")

    paths.clean_stale_sessions()

    assert work.exists(), "katalog żywej sesji nie powinien być usunięty"
    assert (base / f".pid-{alive_sid}").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows uses process handles, not signals")
def test_windows_pid_probe_never_sends_a_signal(monkeypatch):
    from exelent.runtime import paths

    def forbidden(*args):
        pytest.fail("Sprawdzenie PID nie może wysyłać sygnału")

    monkeypatch.setattr(os, "kill", forbidden)
    assert paths._is_pid_alive(os.getpid())
    assert not paths._is_pid_alive(999999999)


def test_damaged_pid_record_does_not_authorize_cleanup(tmp_path, monkeypatch):
    from exelent.runtime import paths

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    base = paths.state_dir() / "b"
    work = base / "abc12345-damaged"
    work.mkdir(parents=True)
    (base / ".pid-damaged").write_text("not a pid", encoding="utf-8")
    paths.clean_stale_sessions()
    assert work.is_dir()


def test_clean_stale_sessions_skips_current_session(tmp_path, monkeypatch):
    """Nie ruszamy katalogu bieżącej sesji, nawet gdyby PID się nie zgadzał."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exelent.runtime import paths

    base = tmp_path / paths.APP_NAME / "b"
    base.mkdir(parents=True)
    sid = paths._SESSION_ID
    work = base / f"abc12345-{sid}"
    work.mkdir()
    (base / f".pid-{sid}").write_text("999999999", encoding="utf-8")

    paths.clean_stale_sessions()

    assert work.exists()


# --- B14: staging cleanup przy błędzie weryfikacji ---


def test_staging_cleaned_when_verification_throws(tmp_path):
    """B14: jeśli `_is_complete` rzuci wyjątek, staging jest usuwany."""
    from unittest.mock import patch

    from exelent.build.publish import publish_artifact

    source = tmp_path / "source.exe"
    source.write_bytes(b"\x00" * 100)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    def _boom(*args, **kwargs):
        raise OSError(22, "source vanished")

    with patch("exelent.build.publish._is_complete", side_effect=_boom):
        result, issues = publish_artifact(source, dest_dir, "test", is_onedir=False)

    assert result is None
    assert any(i.code == "publish_incomplete" for i in issues)
    assert not list(dest_dir.glob(".exelent-publish-*")), "staging powinien być sprzątnięty"


# --- B14: numer próby builda izoluje logi ---


def test_each_execute_build_gets_a_new_build_seq(tmp_path, monkeypatch):
    """Ponowiona próba dostaje inny numer — logi się nie nadpisują."""
    from exelent.build.pyinstaller import log_path_for
    from exelent.runtime.paths import build_seq

    _stub_service(monkeypatch, tmp_path)
    log_paths = []

    class _LogRecorder:
        def build(self, plan, env, progress, cancel):
            log_paths.append(log_path_for(plan))
            return BuildResult(ok=True, artifact=plan.dest_dir / "x.exe", size_bytes=1)

    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")
    plan = BuildPlan(
        root=root,
        entry=root / "main.py",
        app_kind="console",
        output_mode=OutputMode.ONEDIR,
        exe_name="test",
        dest_dir=tmp_path / "out",
    )

    seq_before = build_seq()
    execute_build(plan, noop_progress, backend=_LogRecorder())
    seq_after_first = build_seq()
    execute_build(plan, noop_progress, backend=_LogRecorder())
    seq_after_second = build_seq()

    assert seq_after_first > seq_before
    assert seq_after_second > seq_after_first
    assert len(log_paths) == 2
    assert log_paths[0] != log_paths[1], "logi muszą mieć różne ścieżki"


# --- B14: weryfikacja integralności uv ---


def test_corrupted_uv_is_redownloaded(tmp_path, monkeypatch):
    """Istniejący, ale uszkodzony uv.exe jest usuwany — nie blokuje bootstrapu."""
    from exelent.runtime import bootstrap

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = bootstrap.uv_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"truncated junk")  # za mały, brak nagłówka PE

    assert not bootstrap._is_valid_uv(target)


def test_valid_uv_passes_check(tmp_path):
    """Plik z nagłówkiem MZ i rozsądnym rozmiarem przechodzi walidację."""
    from exelent.runtime.bootstrap import _UV_MIN_SIZE, _is_valid_uv

    fake = tmp_path / "uv.exe"
    # Nagłówek PE + padding do minimalnego rozmiaru
    fake.write_bytes(b"MZ" + b"\x00" * (_UV_MIN_SIZE + 1))

    assert _is_valid_uv(fake)


# --- B14: sprzątanie logów sesji ---


def test_clean_stale_sessions_removes_dead_session_logs(tmp_path, monkeypatch):
    """Logi osieroconych sesji są usuwane razem z katalogami."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from exelent.runtime import paths

    base = tmp_path / paths.APP_NAME / "b"
    base.mkdir(parents=True)
    log_dir = tmp_path / paths.APP_NAME / "logs"
    log_dir.mkdir(parents=True)

    dead_sid = "deadbeef"
    (base / f"abc12345-{dead_sid}").mkdir()
    (base / f".pid-{dead_sid}").write_text("999999999", encoding="utf-8")
    # Logi z dwóch prób builda
    (log_dir / f"prog-abc12345-{dead_sid}.1.log").write_text("log1", encoding="utf-8")
    (log_dir / f"prog-abc12345-{dead_sid}.2.log").write_text("log2", encoding="utf-8")

    paths.clean_stale_sessions()

    assert not (base / f"abc12345-{dead_sid}").exists()
    assert not list(log_dir.glob(f"*-{dead_sid}.*"))


# --- Sprzatanie: ponownie uzyty PID, sierocie katalogi, nieudane usuwanie ---


def _stale_base(tmp_path, monkeypatch):
    from exelent.runtime import paths

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    base = paths.state_dir() / "b"
    base.mkdir(parents=True)
    return paths, base


def test_reused_pid_does_not_keep_a_dead_session_alive(tmp_path, monkeypatch):
    """Po restarcie Windows ten sam PID dostaje inny proces.

    Plik PID zapisany PRZED startem obecnego wlasciciela PID nie moze nalezec
    do tego procesu — sesja jest martwa, choc PID "zyje".
    """
    paths, base = _stale_base(tmp_path, monkeypatch)
    sid = "reused01"
    work = base / f"abc12345-{sid}"
    work.mkdir()
    pid_file = base / f".pid-{sid}"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    started = paths._process_start_time(os.getpid())
    assert started is not None
    os.utime(pid_file, (started - 3600, started - 3600))

    paths.clean_stale_sessions()

    assert not work.exists()
    assert not pid_file.exists()


def test_process_start_time_is_known_for_this_process():
    import time

    from exelent.runtime import paths

    started = paths._process_start_time(os.getpid())
    assert started is not None
    assert started <= time.time()


def test_old_orphan_directories_without_a_session_are_removed(tmp_path, monkeypatch):
    """Katalogi bez pliku PID (stary format bez sufiksu sesji albo sesja,
    ktorej rekord zniknal) nie naleza do nikogo — po okresie karencji znikaja."""
    import time

    paths, base = _stale_base(tmp_path, monkeypatch)
    old = time.time() - paths.ORPHAN_GRACE_SECONDS - 60
    legacy = base / "130ba923"
    orphan = base / "64fb0274-52249378"
    for directory in (legacy, orphan):
        (directory / "venv").mkdir(parents=True)
        os.utime(directory, (old, old))
    log_dir = paths.logs_dir()
    log_dir.mkdir(parents=True)
    (log_dir / "prog-64fb0274-52249378.1.log").write_text("x", encoding="utf-8")

    paths.clean_stale_sessions()

    assert not legacy.exists()
    assert not orphan.exists()
    assert not list(log_dir.glob("*-52249378.*"))


def test_fresh_orphan_directories_are_left_alone(tmp_path, monkeypatch):
    """Karencja chroni katalog, ktorego wlasciciel nie zdolal zapisac PID."""
    paths, base = _stale_base(tmp_path, monkeypatch)
    fresh = base / "abc12345-nopidfil"
    fresh.mkdir()

    paths.clean_stale_sessions()

    assert fresh.exists()


def test_orphan_sweep_never_touches_a_live_session(tmp_path, monkeypatch):
    import time

    paths, base = _stale_base(tmp_path, monkeypatch)
    sid = "alive456"
    work = base / f"abc12345-{sid}"
    work.mkdir()
    old = time.time() - paths.ORPHAN_GRACE_SECONDS - 60
    os.utime(work, (old, old))
    (base / f".pid-{sid}").write_text(str(os.getpid()), encoding="utf-8")

    paths.clean_stale_sessions()

    assert work.exists()


def test_failed_removal_keeps_the_session_record_for_a_retry(tmp_path, monkeypatch):
    """Zablokowany plik (np. uruchomiony EXE z dist) nie moze osierocic katalogu:
    rekord sesji zostaje, zeby nastepne uruchomienie sprobowalo ponownie."""
    import shutil

    paths, base = _stale_base(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "_SESSION_ID", "locked01")
    paths.register_session()
    work = base / "abc12345-locked01"
    work.mkdir()
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **kw: None)

    paths.clean_current_session()

    assert work.exists()
    assert paths._pid_file().exists()


def test_clean_current_session_can_keep_logs_for_the_console(tmp_path, monkeypatch):
    """CLI wypisuje sciezke logu — log zostaje, a rekord sesji pozwala
    posprzatac go przy nastepnym uruchomieniu."""
    paths, base = _stale_base(tmp_path, monkeypatch)
    monkeypatch.setattr(paths, "_SESSION_ID", "console1")
    paths.register_session()
    work = base / "abc12345-console1"
    (work / "venv").mkdir(parents=True)
    log_dir = paths.logs_dir()
    log_dir.mkdir(parents=True)
    log = log_dir / "prog-abc12345-console1.1.log"
    log.write_text("x", encoding="utf-8")

    paths.clean_current_session(keep_logs=True)

    assert not work.exists()
    assert log.exists()
    assert paths._pid_file().exists()
