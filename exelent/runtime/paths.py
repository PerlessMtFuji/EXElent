"""Working paths, session identifiers and cleanup (B14).

Paths are short and pure ASCII — this protects against the 260-character
limit on Windows and against tools that choke on non-ASCII characters.
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

# Per-process instance identifier. Isolates workspaces and logs between
# parallel instances of the same project.
_SESSION_ID = uuid.uuid4().hex[:8]

# Build attempt number within this session. Each call to execute_build gets
# its own number so that retry logs do not overwrite each other.
_build_counter = itertools.count(1)
_current_build_seq: int = 0


def session_id() -> str:
    return _SESSION_ID


def next_build_seq() -> int:
    """New build attempt number. Call at the start of ``execute_build``."""
    global _current_build_seq
    _current_build_seq = next(_build_counter)
    return _current_build_seq


def build_seq() -> int:
    """Current build attempt number in this session."""
    return _current_build_seq


def state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_NAME


def path_hash(source: Path) -> str:
    normalized = str(Path(source).resolve()).lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:8]


def work_dir_for(source: Path, single_file: Path | None = None) -> Path:
    """Working directory for this run.

    In single-file mode we hash the FILE, not the directory — otherwise two
    files in the same folder would share a working directory. The session
    identifier isolates parallel instances.
    """
    return state_dir() / "b" / f"{path_hash(single_file or source)}-{_SESSION_ID}"


def _pid_file() -> Path:
    """PID file for this session — lets other instances tell a live session
    from an orphaned one."""
    return state_dir() / "b" / f".pid-{_SESSION_ID}"


def register_session() -> None:
    """Write the current session's PID. Called at GUI/CLI startup."""
    pid_path = _pid_file()
    with suppress(OSError):
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")


def _unregister_session() -> None:
    with suppress(OSError):
        _pid_file().unlink(missing_ok=True)


def _is_pid_alive(pid: int) -> bool:
    """Whether the process with the given PID is alive (Windows + POSIX)."""
    if pid <= 0 or pid > 0xFFFFFFFF:
        return True  # Corrupted record does not prove the session can be removed.
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
        # SYNCHRONIZE: read state without the right to terminate the process.
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: PID does not exist.
        try:
            # WAIT_OBJECT_0 means terminated. Timeout or failure -> keep the session.
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permissions — it's alive.
        return True
    except OSError:
        return False
    return True


def clean_current_session() -> None:
    """Remove working directories and logs of THIS session plus its PID file.

    Best-effort: cleanup on window close must not cause an error.
    """
    base = state_dir() / "b"
    if not base.exists():
        return
    for directory in base.glob(f"*-{_SESSION_ID}"):
        shutil.rmtree(directory, ignore_errors=True)
    _clean_session_logs(_SESSION_ID)
    _unregister_session()


def _clean_session_logs(sid: str) -> None:
    """Remove build logs of session ``sid``."""
    log_base = logs_dir()
    if not log_base.exists():
        return
    for log_file in log_base.glob(f"*-{sid}.*.log"):
        with suppress(OSError):
            log_file.unlink(missing_ok=True)
    # Compat: logs without an attempt number (old format).
    for log_file in log_base.glob(f"*-{sid}.log"):
        with suppress(OSError):
            log_file.unlink(missing_ok=True)


def clean_stale_sessions() -> None:
    """Clean up working directories and logs of sessions whose process is dead.

    Checks `.pid-*` files in the build directory. If the PID is dead,
    removes directories, logs and the PID file. Live sessions are untouched.
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
