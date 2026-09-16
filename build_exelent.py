"""Builds EXElent.exe — the packaging tool packaging itself.

Run: `python build_exelent.py`

The script only assembles the PyInstaller invocation; the argument list
is a separate function so it can be verified by a test without running
the multi-minute build.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from exelent.constants import APP_NAME

ROOT = Path(__file__).parent
ICON = Path("assets") / f"{APP_NAME.lower()}.ico"


def build_command(root: Path = ROOT) -> list[str]:
    """PyInstaller invocation that builds EXElent from directory `root`."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        # UPX compresses EXE sections the same way malware packers do,
        # so antivirus heuristics react to the mere fact of its use.
        # Disabled project-wide — including here, because this is the file
        # a non-technical user downloads from the internet and runs.
        "--noupx",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(root / "dist"),
        "--workpath",
        str(root / "build"),
        "--specpath",
        str(root / "build"),
    ]
    icon = root / ICON
    if icon.exists():
        command += ["--icon", str(icon)]
    command.append(str(root / "exelent" / "__main__.py"))
    return command


def main() -> int:
    return subprocess.run(build_command(), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
