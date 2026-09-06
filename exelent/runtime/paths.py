"""Wszystkie ścieżki robocze są krótkie i czysto ASCII — chroni to przed
limitem 260 znaków w Windows i przed narzędziami, które gubią się na
znakach spoza ASCII."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from exelent.constants import APP_NAME

# Identyfikator TEJ instancji programu. Powstaje raz na proces i wchodzi w
# nazwe katalogu roboczego oraz logu (A13). Bez niego dwie instancje EXElenta
# budujace ten sam projekt dziela `state/b/<hash>` — a `materialize_workspace`
# zaczyna od `rmtree(workspace)`, wiec jedna kasuje kopie kodu drugiej w
# polowie builda. W obrebie jednej instancji identyfikator jest staly, wiec
# kolejne buildy tego samego projektu nadal reuzywaja srodowiska.
_SESSION_ID = uuid.uuid4().hex[:8]


def session_id() -> str:
    return _SESSION_ID


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

    W nazwie jest tez identyfikator sesji, wiec dwie rownolegle instancje tego
    samego projektu nie kasuja sobie katalogow (A13).
    """
    return state_dir() / "b" / f"{path_hash(single_file or source)}-{_SESSION_ID}"


def clean_current_session() -> None:
    """Usuwa katalogi robocze TEJ sesji (dla wszystkich projektow tej instancji).

    Sprzata wylacznie biezaca sesje — katalogi innej, moze wciaz budujacej
    instancji zostaja nietkniete (A09/A13). Best-effort: sprzatanie po
    zamknieciu okna nie moze byc powodem bledu."""
    base = state_dir() / "b"
    if not base.exists():
        return
    for directory in base.glob(f"*-{_SESSION_ID}"):
        shutil.rmtree(directory, ignore_errors=True)


def tools_dir() -> Path:
    return state_dir() / "tools"


def logs_dir() -> Path:
    return state_dir() / "logs"
