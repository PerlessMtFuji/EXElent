"""Buduje EXElent.exe — czyli program pakujący pakuje sam siebie.

Uruchom: `python build_exelent.py`

Skrypt tylko składa wywołanie PyInstallera; sama lista argumentów jest
osobną funkcją, żeby dało się ją sprawdzić testem bez uruchamiania
kilkuminutowego builda.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from exelent.constants import APP_NAME

ROOT = Path(__file__).parent
ICON = Path("assets") / f"{APP_NAME.lower()}.ico"


def build_command(root: Path = ROOT) -> list[str]:
    """Wywołanie PyInstallera budujące EXElent z katalogu `root`."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        # UPX pakuje sekcje EXE tak, jak robią to programy pakujące złośliwy
        # kod, więc heurystyki antywirusów reagują na sam fakt jego użycia.
        # Wyłączony w całym projekcie — także tutaj, bo to plik, który laik
        # ma pobrać z internetu i uruchomić.
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
