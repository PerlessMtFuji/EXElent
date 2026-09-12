"""Ścieżki robocze, identyfikatory sesji i sprzątanie (B14).

Ścieżki są krótkie i czysto ASCII — chroni to przed limitem 260 znaków
w Windows i przed narzędziami, które gubią się na znakach spoza ASCII.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from contextlib import suppress
from pathlib import Path

from exelent.constants import APP_NAME

# Identyfikator TEJ instancji programu — raz na proces, wchodzi w nazwę
# katalogu roboczego i logu. Dwie instancje tego samego projektu dostają
# osobne katalogi i nie kasują sobie danych (A13).
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

    W trybie jednoplikowym hashujemy PLIK, nie katalog — inaczej dwa pliki
    w tym samym folderze dzieliłyby katalog roboczy. Identyfikator sesji
    izoluje równoległe instancje (A13).
    """
    return state_dir() / "b" / f"{path_hash(single_file or source)}-{_SESSION_ID}"


def _pid_file() -> Path:
    """Plik PID tej sesji — pozwala innym instancjom odróżnić żywą sesję
    od osieroconej (B14)."""
    return state_dir() / "b" / f".pid-{_SESSION_ID}"


def register_session() -> None:
    """Zapisuje PID bieżącej sesji. Woła się przy starcie GUI/CLI."""
    pid_path = _pid_file()
    with suppress(OSError):
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")


def _unregister_session() -> None:
    with suppress(OSError):
        _pid_file().unlink(missing_ok=True)


def _is_pid_alive(pid: int) -> bool:
    """Czy proces o podanym PID żyje (Windows + POSIX)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Proces istnieje, ale nie mamy uprawnień — żyje.
        return True
    except OSError:
        return False
    return True


def clean_current_session() -> None:
    """Usuwa katalogi robocze TEJ sesji i jej plik PID.

    Best-effort: sprzątanie przy zamykaniu okna nie może być powodem błędu.
    """
    base = state_dir() / "b"
    if not base.exists():
        return
    for directory in base.glob(f"*-{_SESSION_ID}"):
        shutil.rmtree(directory, ignore_errors=True)
    _unregister_session()


def clean_stale_sessions() -> None:
    """Sprząta katalogi robocze sesji, których proces już nie żyje (B14).

    Sprawdza pliki `.pid-*` w katalogu buildów. Jeśli PID jest martwy,
    usuwa katalog roboczy i plik PID. Żywe sesje — nietknięte.
    """
    base = state_dir() / "b"
    if not base.exists():
        return
    for pid_file in base.glob(".pid-*"):
        sid = pid_file.name[len(".pid-"):]
        if sid == _SESSION_ID:
            continue
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            # Uszkodzony plik PID — bezpiecznie usunąć.
            pid = -1
        if _is_pid_alive(pid):
            continue
        # Sesja osierocona — sprzątnij jej katalogi.
        for directory in base.glob(f"*-{sid}"):
            if directory.name.startswith(".pid-"):
                continue
            shutil.rmtree(directory, ignore_errors=True)
        with suppress(OSError):
            pid_file.unlink(missing_ok=True)


def tools_dir() -> Path:
    return state_dir() / "tools"


def logs_dir() -> Path:
    return state_dir() / "logs"
