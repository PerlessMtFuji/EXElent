"""Ścieżki robocze, identyfikatory sesji i sprzątanie (B14).

Ścieżki są krótkie i czysto ASCII — chroni to przed limitem 260 znaków
w Windows i przed narzędziami, które gubią się na znakach spoza ASCII.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import shutil
import uuid
from contextlib import suppress
from pathlib import Path

from exelent.constants import APP_NAME

# Identyfikator instancji — raz na proces. Izoluje workspace i logi między
# równoległymi instancjami tego samego projektu.
_SESSION_ID = uuid.uuid4().hex[:8]

# Numer próby builda w tej sesji. Każde wołanie execute_build dostaje
# osobny numer, dzięki czemu logi ponowionych prób nie nadpisują się.
_build_counter = itertools.count(1)
_current_build_seq: int = 0


def session_id() -> str:
    return _SESSION_ID


def next_build_seq() -> int:
    """Nowy numer próby builda. Wołać na początku ``execute_build``."""
    global _current_build_seq
    _current_build_seq = next(_build_counter)
    return _current_build_seq


def build_seq() -> int:
    """Bieżący numer próby builda w tej sesji."""
    return _current_build_seq


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
    izoluje równoległe instancje.
    """
    return state_dir() / "b" / f"{path_hash(single_file or source)}-{_SESSION_ID}"


def _pid_file() -> Path:
    """Plik PID tej sesji — pozwala innym instancjom odróżnić żywą sesję
    od osieroconej."""
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
    if pid <= 0 or pid > 0xFFFFFFFF:
        return True  # Uszkodzony zapis nie dowodzi, że sesję można usunąć.
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        # SYNCHRONIZE: odczyt stanu bez prawa kończenia procesu.
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: PID nie istnieje.
        try:
            # WAIT_OBJECT_0 oznacza zakończenie. Timeout lub awaria -> zachowaj sesję.
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel.CloseHandle(handle)
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
    """Usuwa katalogi robocze i logi TEJ sesji oraz jej plik PID.

    Best-effort: sprzątanie przy zamykaniu okna nie może być powodem błędu.
    """
    base = state_dir() / "b"
    if not base.exists():
        return
    for directory in base.glob(f"*-{_SESSION_ID}"):
        shutil.rmtree(directory, ignore_errors=True)
    _clean_session_logs(_SESSION_ID)
    _unregister_session()


def _clean_session_logs(sid: str) -> None:
    """Usuwa logi budowań sesji ``sid``."""
    log_base = logs_dir()
    if not log_base.exists():
        return
    for log_file in log_base.glob(f"*-{sid}.*.log"):
        with suppress(OSError):
            log_file.unlink(missing_ok=True)
    # Compat: logi bez numeru próby (stary format).
    for log_file in log_base.glob(f"*-{sid}.log"):
        with suppress(OSError):
            log_file.unlink(missing_ok=True)


def clean_stale_sessions() -> None:
    """Sprząta katalogi robocze i logi sesji, których proces już nie żyje.

    Sprawdza pliki `.pid-*` w katalogu buildów. Jeśli PID jest martwy,
    usuwa katalogi, logi i plik PID. Żywe sesje — nietknięte.
    """
    base = state_dir() / "b"
    if not base.exists():
        return
    for pid_file in base.glob(".pid-*"):
        sid = pid_file.name[len(".pid-") :]
        if sid == _SESSION_ID:
            continue
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = -1
        if _is_pid_alive(pid):
            continue
        for directory in base.glob(f"*-{sid}"):
            if directory.name.startswith(".pid-"):
                continue
            shutil.rmtree(directory, ignore_errors=True)
        _clean_session_logs(sid)
        with suppress(OSError):
            pid_file.unlink(missing_ok=True)


def tools_dir() -> Path:
    return state_dir() / "tools"


def logs_dir() -> Path:
    return state_dir() / "logs"
