"""B14: usługa rdzenia, sesje i sprzątanie.

Testy weryfikują:
- `execute_build` mieszka w `build.service`, nie w `cli`
- Backend jest wstrzykiwany przez parametr
- Sprzątanie osieroconych sesji oparte na PID
- Staging publikacji sprzątany przy błędzie weryfikacji
"""

from __future__ import annotations

import os
from pathlib import Path

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
