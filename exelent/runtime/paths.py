"""Wszystkie ścieżki robocze są krótkie i czysto ASCII — chroni to przed
limitem 260 znaków w Windows i przed narzędziami, które gubią się na
znakach spoza ASCII."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from exelent.constants import APP_NAME


def state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_NAME


def path_hash(source: Path) -> str:
    normalized = str(Path(source).resolve()).lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:8]


def work_dir_for(source: Path, single_file: Path | None = None) -> Path:
    """Katalog roboczy dla tego przebiegu.

    W trybie jednoplikowym hashujemy PLIK, nie katalog. Inaczej `a.py` i
    `b.py` lezace w Pobranych dziela jeden katalog roboczy i drugi build
    kasuje srodowisko pierwszego — a `path_hash` jest jedyna rzecza, ktora
    te przebiegi rozdziela.
    """
    return state_dir() / "b" / path_hash(single_file or source)


def tools_dir() -> Path:
    return state_dir() / "tools"


def logs_dir() -> Path:
    return state_dir() / "logs"
