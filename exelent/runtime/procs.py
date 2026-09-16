"""Child-process termination shared by the three places that need it.

A cancelled build (PyInstaller spawns its own children), cancelled preflight
(uv), and emergency window shutdown all have the same obligation: leave no
background processes behind. Without `/T`, orphans remain and keep workspace
files open.
"""

from __future__ import annotations

import subprocess

# Without this, GUI users see a black console window flash on every
# command-line tool invocation.
CREATE_NO_WINDOW = 0x08000000


def kill_tree(pid: int) -> int:
    """Terminate a process and all its descendants.

    Return taskkill's exit code so the caller can detect failed termination
    (the process may still hold workspace files open).
    """
    result = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    return result.returncode
