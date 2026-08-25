"""Drives PyInstallerBackend.build() through an actual subprocess, using a
fake "PyInstaller" module on sys.path so the tests stay fast and offline —
no real PyInstaller run is needed."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import exelent.build.pyinstaller as pyinstaller_module
from exelent.build.backend import CancelToken
from exelent.build.pyinstaller import PyInstallerBackend
from exelent.models import AppKind, BuildPlan, OutputMode
from exelent.runtime import noop_progress
from exelent.runtime.env import BuildEnv
from exelent.runtime.paths import work_dir_for

_FAKE_MAIN = """\
import os
import sys
import time
from pathlib import Path


def _arg_value(flag):
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        return sys.argv[idx + 1]
    return None


def main():
    distpath = _arg_value("--distpath")
    name = _arg_value("--name")
    onedir = "--onedir" in sys.argv

    lines = os.environ.get("EXELENT_FAKE_LOG_LINES", "")
    for line in [entry for entry in lines.split("|") if entry]:
        print(line, flush=True)

    sleep_s = float(os.environ.get("EXELENT_FAKE_SLEEP", "0"))
    if sleep_s:
        time.sleep(sleep_s)

    if os.environ.get("EXELENT_FAKE_PRODUCE", "1") == "1" and distpath and name:
        dist = Path(distpath)
        dist.mkdir(parents=True, exist_ok=True)
        if onedir:
            target = dist / name
            target.mkdir(parents=True, exist_ok=True)
            (target / (name + ".exe")).write_bytes(b"fake-onedir")
        else:
            (dist / (name + ".exe")).write_bytes(b"fake-onefile")

    sys.exit(int(os.environ.get("EXELENT_FAKE_EXITCODE", "0")))


if __name__ == "__main__":
    main()
"""


@pytest.fixture
def fake_pyinstaller(monkeypatch, tmp_path):
    """Puts a fake PyInstaller package on PYTHONPATH so `python -m PyInstaller`
    runs our stand-in instead of the real (uninstalled, slow) tool."""
    pkg_root = tmp_path / "fake_pkg"
    package = pkg_root / "PyInstaller"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(_FAKE_MAIN, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(pkg_root))
    monkeypatch.setenv("EXELENT_FAKE_PRODUCE", "1")
    monkeypatch.setenv("EXELENT_FAKE_EXITCODE", "0")
    monkeypatch.delenv("EXELENT_FAKE_SLEEP", raising=False)
    monkeypatch.delenv("EXELENT_FAKE_LOG_LINES", raising=False)
    return pkg_root


def _plan(
    root: Path,
    dest: Path,
    *,
    output_mode: OutputMode = OutputMode.ONEFILE,
    exe_name: str = "Program",
) -> BuildPlan:
    return BuildPlan(
        root=root,
        entry=root / "main.py",
        app_kind=AppKind.CONSOLE,
        output_mode=output_mode,
        exe_name=exe_name,
        dest_dir=dest,
    )


def _env() -> BuildEnv:
    return BuildEnv(uv=Path("uv"), venv=Path("venv"), python=Path(sys.executable))


def _prepare_workspace(tmp_path: Path, monkeypatch, root_name: str = "proj") -> tuple[Path, Path]:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = tmp_path / root_name
    root.mkdir()
    (root / "main.py").write_text("print(1)", encoding="utf-8")
    workspace = work_dir_for(root) / "src"
    workspace.mkdir(parents=True)
    return root, workspace


def test_zero_returncode_with_missing_artifact_is_reported_as_vanished(
    tmp_path, monkeypatch, fake_pyinstaller
):
    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("EXELENT_FAKE_PRODUCE", "0")

    plan = _plan(root, tmp_path / "out")
    result = PyInstallerBackend().build(plan, _env(), noop_progress, CancelToken())

    assert result.ok is False
    assert result.artifact is None
    assert any(i.code == "artifact_vanished" for i in result.issues)
    assert result.log_path is not None and result.log_path.exists()


def test_onefile_build_succeeds_and_writes_log(tmp_path, monkeypatch, fake_pyinstaller):
    root, _ = _prepare_workspace(tmp_path, monkeypatch)

    plan = _plan(root, tmp_path / "out", output_mode=OutputMode.ONEFILE)
    result = PyInstallerBackend().build(plan, _env(), noop_progress, CancelToken())

    assert result.ok is True
    assert result.artifact == tmp_path / "out" / "Program.exe"
    assert result.artifact.read_bytes() == b"fake-onefile"
    assert result.log_path is not None and result.log_path.exists()


def test_onefile_rebuild_replaces_clean_stale_destination(tmp_path, monkeypatch, fake_pyinstaller):
    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "Program.exe").write_bytes(b"old-build")

    plan = _plan(root, dest, output_mode=OutputMode.ONEFILE)
    result = PyInstallerBackend().build(plan, _env(), noop_progress, CancelToken())

    assert result.ok is True
    assert result.artifact.read_bytes() == b"fake-onefile"


def test_onedir_rebuild_replaces_clean_stale_destination(tmp_path, monkeypatch, fake_pyinstaller):
    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    dest = tmp_path / "out"
    stale = dest / "Program"
    stale.mkdir(parents=True)
    (stale / "old.txt").write_text("stale", encoding="utf-8")

    plan = _plan(root, dest, output_mode=OutputMode.ONEDIR)
    result = PyInstallerBackend().build(plan, _env(), noop_progress, CancelToken())

    assert result.ok is True
    target = result.artifact
    assert target == dest / "Program"
    assert (target / "Program.exe").read_bytes() == b"fake-onedir"
    assert not (target / "old.txt").exists()
    assert not (target / "Program").exists()  # replaced in place, not nested


def test_onedir_dest_cannot_be_cleared_reports_dest_in_use(tmp_path, monkeypatch, fake_pyinstaller):
    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    dest = tmp_path / "out"
    stale = dest / "Program"
    stale.mkdir(parents=True)
    locked = stale / "locked.bin"
    locked.write_bytes(b"locked")

    # Deliberately not a `with` block: the handle must stay open across the
    # build() call below to simulate a locked file blocking cleanup.
    handle = open(locked, "rb")  # noqa: SIM115
    try:
        plan = _plan(root, dest, output_mode=OutputMode.ONEDIR)
        result = PyInstallerBackend().build(plan, _env(), noop_progress, CancelToken())
    finally:
        handle.close()

    assert result.ok is False
    assert any(i.code == "dest_in_use" for i in result.issues)
    assert not (stale / "Program").exists()  # never silently nested
    assert locked.exists()  # stale content untouched, not half-merged


def test_cancel_during_silent_subprocess_returns_promptly(tmp_path, monkeypatch, fake_pyinstaller):
    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("EXELENT_FAKE_SLEEP", "6")
    monkeypatch.setenv("EXELENT_FAKE_PRODUCE", "0")

    plan = _plan(root, tmp_path / "out")
    cancel = CancelToken()
    timer = threading.Timer(0.3, cancel.cancel)
    timer.start()
    started = time.monotonic()
    try:
        result = PyInstallerBackend().build(plan, _env(), noop_progress, cancel)
    finally:
        timer.cancel()
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"cancel took too long: {elapsed:.2f}s"
    assert result.ok is False
    assert any(i.code == "build_cancelled" for i in result.issues)
    assert result.log_path is not None and result.log_path.exists()


def test_cancel_incomplete_warning_when_taskkill_fails(tmp_path, monkeypatch, fake_pyinstaller):
    real_kill_tree = pyinstaller_module._kill_tree

    def _fake_kill_tree(pid: int) -> int:
        real_kill_tree(pid)  # still actually terminate the process...
        return 1  # ...but report as if taskkill itself failed

    monkeypatch.setattr(pyinstaller_module, "_kill_tree", _fake_kill_tree)

    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("EXELENT_FAKE_SLEEP", "6")
    monkeypatch.setenv("EXELENT_FAKE_PRODUCE", "0")

    plan = _plan(root, tmp_path / "out")
    cancel = CancelToken()
    timer = threading.Timer(0.2, cancel.cancel)
    timer.start()
    try:
        result = PyInstallerBackend().build(plan, _env(), noop_progress, cancel)
    finally:
        timer.cancel()

    codes = {i.code for i in result.issues}
    assert result.ok is False
    assert "build_cancelled" in codes
    assert "cancel_incomplete" in codes


def test_cancel_returns_within_bound_when_kill_genuinely_fails(
    tmp_path, monkeypatch, fake_pyinstaller
):
    """Round 2, Finding: a child that survives taskkill must not hang
    build() forever. _kill_tree here reports failure AND does not actually
    terminate anything, simulating a genuinely-unkillable process."""
    captured_pid: dict[str, int] = {}

    def _fake_kill_tree_reports_failure_without_killing(pid: int) -> int:
        captured_pid["pid"] = pid
        return 1

    monkeypatch.setattr(
        pyinstaller_module, "_kill_tree", _fake_kill_tree_reports_failure_without_killing
    )

    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("EXELENT_FAKE_SLEEP", "300")
    monkeypatch.setenv("EXELENT_FAKE_PRODUCE", "0")

    plan = _plan(root, tmp_path / "out")
    cancel = CancelToken()
    timer = threading.Timer(0.3, cancel.cancel)
    timer.start()
    started = time.monotonic()
    try:
        result = PyInstallerBackend().build(plan, _env(), noop_progress, cancel)
    finally:
        timer.cancel()
        # Our fake _kill_tree deliberately left the child running -- clean
        # it up for real so the test suite doesn't leak a sleeping process
        # on the developer's machine.
        pid = captured_pid.get("pid")
        if pid is not None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
    elapsed = time.monotonic() - started

    # Generous vs. the 0.3s trigger delay + the 3s kill-wait bound + the 1s
    # reader-join bound (~4.3s worst case) -- bounded, not flaky, and proves
    # build() does not hang indefinitely the way the un-patched code did
    # (reviewer measured 30+ seconds with no return).
    assert elapsed < 10.0, f"build() did not return promptly: {elapsed:.2f}s"

    assert result.ok is False
    codes = {i.code for i in result.issues}
    assert "build_cancelled" in codes
    assert "cancel_incomplete" in codes

    log_text = result.log_path.read_text(encoding="utf-8")
    assert "taskkill returncode=1" in log_text
    assert "still alive" in log_text


def test_failed_returncode_writes_log_but_no_exception(tmp_path, monkeypatch, fake_pyinstaller):
    root, _ = _prepare_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("EXELENT_FAKE_EXITCODE", "1")
    monkeypatch.setenv("EXELENT_FAKE_PRODUCE", "0")

    plan = _plan(root, tmp_path / "out")
    result = PyInstallerBackend().build(plan, _env(), noop_progress, CancelToken())

    assert result.ok is False
    assert result.log_path is not None and result.log_path.exists()
