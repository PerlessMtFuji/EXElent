"""B10: anulowanie całego procesu — wspólny token, timeouty, kill_tree.

Testy reprodukują mechanizmy anulowania w każdej fazie pipeline'u:
bootstrap, materializacja, walidacja, publikacja. Synchronizowane
zdarzeniami, nie arbitralnym `sleep`.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from exelent.build.backend import CancelToken
from exelent.build.publish import publish_artifact
from exelent.build.workspace import materialize_workspace
from exelent.models import (
    BuildPlan,
    IssueError,
    OutputMode,
    SourceEntry,
)
from exelent.runtime import noop_progress
from exelent.runtime.bootstrap import ensure_uv

# --- helpers ---


def _plan_with_inventory(tmp_path: Path, n_files: int = 5) -> BuildPlan:
    """Plan z inwentarzem `n_files` plików."""
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    entry = root / "main.py"
    entry.write_text("print('ok')\n", encoding="utf-8")

    inventory: list[SourceEntry] = []
    for i in range(n_files):
        name = f"mod{i}.py"
        (root / name).write_text(f"# modul {i}\n", encoding="utf-8")
        import hashlib

        h = hashlib.sha256(f"# modul {i}\n".encode()).hexdigest()
        inventory.append(SourceEntry(rel_path=name, sha256=h))

    # dodaj entry do inwentarza
    import hashlib

    eh = hashlib.sha256(b"print('ok')\n").hexdigest()
    inventory.append(SourceEntry(rel_path="main.py", sha256=eh))

    return BuildPlan(
        root=root,
        entry=entry,
        app_kind="console",
        output_mode=OutputMode.ONEDIR,
        exe_name="test",
        dest_dir=tmp_path / "out",
        source_inventory=tuple(inventory),
    )


# --- B10: anulowany token PRZED startem ---


def test_cancelled_token_before_materialize_does_not_copy(tmp_path, monkeypatch):
    """Anulowany token przed startem nie tworzy workspace (B10)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    plan = _plan_with_inventory(tmp_path)
    token = CancelToken()
    token.cancel()

    with pytest.raises(IssueError) as exc_info:
        materialize_workspace(plan, cancel=token)

    assert exc_info.value.issue.code == "build_cancelled"


def test_cancelled_token_before_ensure_uv_does_not_download(monkeypatch, tmp_path):
    """Anulowany token przed startem ensure_uv nie pobiera (B10)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    token = CancelToken()
    token.cancel()

    with pytest.raises(IssueError) as exc_info:
        ensure_uv(noop_progress, cancel=token)

    assert exc_info.value.issue.code == "build_cancelled"


# --- B10: cancel w materialize_workspace przerywa kopiowanie ---


def test_cancel_during_materialize_stops_copying(tmp_path, monkeypatch):
    """Token ustawiany po pierwszym pliku przerywa kopiowanie (B10)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    plan = _plan_with_inventory(tmp_path, n_files=10)
    token = CancelToken()
    copied = []
    original_copy = shutil.copy2

    def tracking_copy(src, dst, **kwargs):
        copied.append(src)
        if len(copied) >= 2:
            token.cancel()
        return original_copy(src, dst, **kwargs)

    with patch("shutil.copy2", side_effect=tracking_copy), pytest.raises(IssueError) as exc_info:
        materialize_workspace(plan, cancel=token)

    assert exc_info.value.issue.code == "build_cancelled"
    # Nie skopiowaliśmy wszystkich 11 plików (10 modułów + main.py)
    assert len(copied) < 11


# --- B10: cancel w publish_artifact sprząta staging ---


def test_cancel_before_publish_does_not_create_staging(tmp_path):
    """Anulowanie PRZED kopiowaniem nie tworzy stagingu (B10)."""
    source = tmp_path / "source.exe"
    source.write_bytes(b"\x00" * 100)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    token = CancelToken()
    token.cancel()

    result, issues = publish_artifact(source, dest_dir, "test", is_onedir=False, cancel=token)

    assert result is None
    assert any(i.code == "build_cancelled" for i in issues)
    # Żaden staging nie został
    assert not list(dest_dir.glob(".exelent-publish-*"))


def test_cancel_after_copy_before_rename_cleans_staging(tmp_path):
    """Anulowanie PO skopiowaniu, ale PRZED finalizacją sprząta staging (B10).

    Punkt zatwierdzenia: atomic rename. Przed nią staging jest usuwany;
    po niej artefakt zostaje. Test ustawia cancel PO copy2/copytree."""
    source = tmp_path / "source.exe"
    source.write_bytes(b"\x00" * 100)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    token = CancelToken()
    original_copy2 = shutil.copy2

    def copy_then_cancel(src, dst, **kwargs):
        result = original_copy2(src, dst, **kwargs)
        token.cancel()  # cancel ZARAZ PO skopiowaniu
        return result

    with patch("exelent.build.publish.shutil.copy2", side_effect=copy_then_cancel):
        result, issues = publish_artifact(source, dest_dir, "test", is_onedir=False, cancel=token)

    assert result is None
    assert any(i.code == "build_cancelled" for i in issues)
    # Staging został sprzątnięty
    assert not list(dest_dir.glob(".exelent-publish-*"))


# --- B10: cancelled build z execute_build ---


def test_precancelled_build_returns_immediately(tmp_path, monkeypatch):
    """Token anulowany PRZED startem nie uruchamia żadnej pracy (B10)."""
    from exelent.build import service

    monkeypatch.setattr(service, "check_preconditions", lambda **_kw: ())

    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")

    def _should_not_run(plan, cancel=None):
        raise RuntimeError("nie powinno zostac wywolane")

    monkeypatch.setattr(service, "materialize_workspace", _should_not_run)

    token = CancelToken()
    token.cancel()

    result = service.execute_build(
        BuildPlan(
            root=root,
            entry=root / "main.py",
            app_kind="console",
            output_mode=OutputMode.ONEDIR,
            exe_name="test",
            dest_dir=tmp_path / "out",
        ),
        noop_progress,
        token,
    )

    assert result.ok is False
    assert any(i.code == "build_cancelled" for i in result.issues)


# --- B10: validate_target_syntax z cancel ---


def test_validate_cancellation_returns_none(tmp_path):
    """Anulowanie walidacji zwraca None, a build kończy się jako przerwany (B10)."""
    from exelent.build.validate import validate_target_syntax

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "main.py").write_text("print(1)\n", encoding="utf-8")

    token = CancelToken()
    token.cancel()

    # cancel PRZED startem → None
    result = validate_target_syntax(
        Path("python.exe"),  # nie zostanie wywołany
        workspace,
        python_version="3.12",
        cancel=token,
    )
    assert result is None
