"""B10: cancel the whole process with a shared token, timeouts, and kill_tree.

The tests reproduce cancellation in every pipeline phase: bootstrap,
materialization, validation, and publication. Events provide synchronization
instead of arbitrary sleeps.
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
    """Create a plan with `n_files` entries in its inventory."""
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    entry = root / "main.py"
    entry.write_text("print('ok')\n", encoding="utf-8")

    inventory: list[SourceEntry] = []
    for i in range(n_files):
        name = f"mod{i}.py"
        (root / name).write_text(f"# module {i}\n", encoding="utf-8")
        import hashlib

        h = hashlib.sha256(f"# module {i}\n".encode()).hexdigest()
        inventory.append(SourceEntry(rel_path=name, sha256=h))

    # Add the entry point to the inventory.
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


# --- B10: token cancelled before start ---


def test_cancelled_token_before_materialize_does_not_copy(tmp_path, monkeypatch):
    """A token cancelled before start does not create a workspace (B10)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    plan = _plan_with_inventory(tmp_path)
    token = CancelToken()
    token.cancel()

    with pytest.raises(IssueError) as exc_info:
        materialize_workspace(plan, cancel=token)

    assert exc_info.value.issue.code == "build_cancelled"


def test_cancelled_token_before_ensure_uv_does_not_download(monkeypatch, tmp_path):
    """A token cancelled before `ensure_uv` downloads nothing (B10)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    token = CancelToken()
    token.cancel()

    with pytest.raises(IssueError) as exc_info:
        ensure_uv(noop_progress, cancel=token)

    assert exc_info.value.issue.code == "build_cancelled"


# --- B10: cancellation stops materialize_workspace copying ---


def test_cancel_during_materialize_stops_copying(tmp_path, monkeypatch):
    """A token set after the first file stops copying (B10)."""
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
    # Fewer than all 11 files were copied (10 modules plus main.py).
    assert len(copied) < 11


# --- B10: cancellation in publish_artifact cleans staging ---


def test_cancel_before_publish_does_not_create_staging(tmp_path):
    """Cancellation before copying creates no staging directory (B10)."""
    source = tmp_path / "source.exe"
    source.write_bytes(b"\x00" * 100)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    token = CancelToken()
    token.cancel()

    result, issues = publish_artifact(source, dest_dir, "test", is_onedir=False, cancel=token)

    assert result is None
    assert any(i.code == "build_cancelled" for i in issues)
    # No staging directory remains.
    assert not list(dest_dir.glob(".exelent-publish-*"))


def test_cancel_after_copy_before_rename_cleans_staging(tmp_path):
    """Cancellation after copying but before finalization removes staging (B10).

    The commit point is the atomic rename. Before it, staging is removed; after
    it, the artifact remains. The test cancels after copy2/copytree.
    """
    source = tmp_path / "source.exe"
    source.write_bytes(b"\x00" * 100)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    token = CancelToken()
    original_copy2 = shutil.copy2

    def copy_then_cancel(src, dst, **kwargs):
        result = original_copy2(src, dst, **kwargs)
        token.cancel()  # cancel immediately after copying
        return result

    with patch("exelent.build.publish.shutil.copy2", side_effect=copy_then_cancel):
        result, issues = publish_artifact(source, dest_dir, "test", is_onedir=False, cancel=token)

    assert result is None
    assert any(i.code == "build_cancelled" for i in issues)
    # Staging was removed.
    assert not list(dest_dir.glob(".exelent-publish-*"))


# --- B10: execute_build with a cancelled token ---


def test_precancelled_build_returns_immediately(tmp_path, monkeypatch):
    """A token cancelled before start performs no work (B10)."""
    from exelent.build import service

    monkeypatch.setattr(service, "check_preconditions", lambda **_kw: ())

    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")

    def _should_not_run(plan, cancel=None):
        raise RuntimeError("must not be called")

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


# --- B10: validate_target_syntax cancellation ---


def test_validate_cancellation_returns_none(tmp_path):
    """Cancelled validation returns None and the build finishes as cancelled (B10)."""
    from exelent.build.validate import validate_target_syntax

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "main.py").write_text("print(1)\n", encoding="utf-8")

    token = CancelToken()
    token.cancel()

    # Cancellation before start returns None.
    result = validate_target_syntax(
        Path("python.exe"),  # will not be invoked
        workspace,
        python_version="3.12",
        cancel=token,
    )
    assert result is None
