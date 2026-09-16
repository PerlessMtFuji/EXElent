"""`run_bounded`: a timeout that actually bounds elapsed time.

`subprocess.run(..., capture_output=True, timeout=T)` does not: it kills the
direct child and drains the pipe, which closes only after a grandchild that
inherited the handles exits. A ONEFILE EXE has exactly this shape (bootloader
plus real program), so a regression made the golden test hang instead of fail.
Measured result: 3-second timeout, child alive for 30 seconds, return after
30.1 seconds.

These tests prove the mechanism with ordinary Python processes, so they remain
fast and do not build an EXE.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from procutil import is_running, run_bounded

CHILD_LIFETIME = 30
BOUND = 3


def _tree(tmp_path: Path, marker: Path | None = None) -> list[str]:
    """A waiting parent that starts a child, like the ONEFILE bootloader."""
    child = tmp_path / "child.py"
    record = (
        f"import os, pathlib; pathlib.Path(r'{marker}').write_text(str(os.getpid()))\n"
        if marker
        else ""
    )
    child.write_text(f"import time\n{record}time.sleep({CHILD_LIFETIME})\n", encoding="utf-8")
    parent = tmp_path / "parent.py"
    parent.write_text(
        f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, r'{child}'])\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    return [sys.executable, str(parent)]


def test_a_normal_program_returns_its_output(tmp_path):
    script = tmp_path / "ordinary.py"
    script.write_text("print('READY')\n", encoding="utf-8")

    done = run_bounded([sys.executable, str(script)], timeout=30)

    assert done.returncode == 0
    assert "READY" in done.stdout


def test_input_reaches_the_program(tmp_path):
    script = tmp_path / "prompting.py"
    script.write_text("print('HELLO-' + input().strip().upper())\n", encoding="utf-8")

    done = run_bounded([sys.executable, str(script)], timeout=30, input="alice\n")

    assert "HELLO-ALICE" in done.stdout


def test_timeout_bounds_the_call_even_when_a_grandchild_holds_the_pipes(tmp_path):
    started = time.monotonic()

    done = run_bounded(_tree(tmp_path), timeout=BOUND, allow_timeout=True)

    elapsed = time.monotonic() - started
    assert elapsed < CHILD_LIFETIME / 2, f"returned after {elapsed:.1f}s with a {BOUND}s timeout"
    assert done.returncode is None, "the result must expose the timeout"


def test_the_whole_tree_is_dead_afterwards(tmp_path):
    marker = tmp_path / "pid.txt"

    run_bounded(_tree(tmp_path, marker), timeout=BOUND, allow_timeout=True)

    pid = int(marker.read_text(encoding="utf-8").strip())
    assert not is_running(pid), "the grandchild survived cleanup and retained its resources"


def test_an_overrun_is_a_failure_by_default(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded(_tree(tmp_path), timeout=BOUND)


def test_the_call_is_bounded_even_when_the_kill_fails(tmp_path, monkeypatch):
    """The overall bound cannot depend on `taskkill` succeeding.

    If tree termination fails (an elevated process or no `taskkill` in CI), an
    unbounded `communicate` waits for the parent's full lifetime: 300.1 seconds
    in a measured run with a 3-second timeout. The test must fail, never hang.
    """
    import procutil

    monkeypatch.setattr(procutil, "DRAIN_TIMEOUT", 1.0)
    survivors: list[subprocess.Popen] = []
    monkeypatch.setattr(procutil, "kill_tree", survivors.append)

    started = time.monotonic()
    try:
        run_bounded(_tree(tmp_path), timeout=BOUND, allow_timeout=True)
        elapsed = time.monotonic() - started
        assert elapsed < CHILD_LIFETIME / 2, f"returned after {elapsed:.1f}s despite {BOUND}s bound"
    finally:
        for process in survivors:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False
            )
