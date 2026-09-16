"""Run built programs so a timeout actually bounds the elapsed time.

`subprocess.run(..., capture_output=True, timeout=T)` does not guarantee that.
After the timeout it kills the direct child and then drains the pipe, which
stays open until a grandchild that inherited the handles exits. A ONEFILE EXE
has exactly this shape: the bootloader unpacks `_MEI...` and starts the real
program inside it. Measured on this machine, a 3-second timeout with a child
living for 30 seconds returned after 30.1 seconds.

The effect in a golden test was worse than a failure: a windowed-program
regression made the test hang instead of fail, occupying the nightly CI runner
without producing a result.
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import suppress
from pathlib import Path

# How long to drain pipes after killing the tree. This normally takes a fraction
# of a second. It has its own bound because if `taskkill` fails (an elevated
# process or a CI image without `taskkill`), an unkilled process keeps the pipe
# open and an unbounded `communicate()` waits for the parent's full lifetime.
# Measured at 300.1 seconds with `timeout=3`. The test must fail, never hang.
DRAIN_TIMEOUT = 10.0


def kill_tree(process: subprocess.Popen) -> None:
    """Kill the entire process tree, not only its parent."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:  # pragma: no cover - Windows project, but keep fallback behavior honest
        process.kill()
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=30)


def _tasklist(filter_expression: str) -> str:
    listing = subprocess.run(
        ["tasklist", "/FI", filter_expression],
        capture_output=True,
        text=True,
        check=False,
    )
    return listing.stdout


def is_running(pid: int) -> bool:
    output = _tasklist(f"PID eq {pid}")
    return "No tasks" not in output and str(pid) in output


def is_running_name(name: str) -> bool:
    output = _tasklist(f"IMAGENAME eq {name}")
    return "No tasks" not in output and name.lower() in output.lower()


def run_bounded(
    command,
    *,
    timeout: float,
    input: str | None = None,
    cwd: Path | None = None,
    allow_timeout: bool = False,
) -> subprocess.CompletedProcess:
    """Run a program and return on time even while its child remains alive.

    `allow_timeout=True` means the timeout is expected, as for a windowed
    program waiting for user input, and returns a result whose `returncode` is
    `None`. By default an overrun is a failure: the test fails instead of
    hanging.
    """
    process = subprocess.Popen(
        [str(part) for part in command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
    )
    try:
        out, err = process.communicate(input=input, timeout=timeout)
        return subprocess.CompletedProcess(process.args, process.returncode, out, err)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            # The dead tree normally closes its pipes immediately. If killing
            # failed, give up the output rather than hang: a result without a
            # log can be investigated, while a stuck CI run cannot.
            out, err = process.communicate(timeout=DRAIN_TIMEOUT)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        if allow_timeout:
            return subprocess.CompletedProcess(process.args, None, out, err)
        raise subprocess.TimeoutExpired(process.args, timeout, output=out, stderr=err) from None
