"""Working paths, session identifiers and cleanup (B14).

Paths are short and pure ASCII — this protects against the 260-character
limit on Windows and against tools that choke on non-ASCII characters.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import shutil
import time
import uuid
from contextlib import suppress
from pathlib import Path

from exelent.constants import APP_NAME

# Per-process instance identifier. Isolates workspaces and logs between
# parallel instances of the same project.
_SESSION_ID = uuid.uuid4().hex[:8]

# A working directory with no session record (legacy name without a session
# suffix, or a record lost to a crash) belongs to nobody once it is this old.
# The grace period protects an instance that failed to write its PID file.
ORPHAN_GRACE_SECONDS = 24 * 3600

# Filesystem timestamp resolution (FAT: 2 s) when comparing a process start
# time with the moment its PID file was written.
_CLOCK_SLACK_SECONDS = 2.0

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


def _process_start_time(pid: int) -> float | None:
    """Start time of process ``pid`` as a Unix timestamp; None when unknown."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        filetime_p = ctypes.POINTER(wintypes.FILETIME)
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *(filetime_p,) * 4)
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        # PROCESS_QUERY_LIMITED_INFORMATION: enough for GetProcessTimes.
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            # FILETIME counts 100 ns intervals since 1601-01-01.
            return (created - 116444736000000000) / 10_000_000
        finally:
            kernel.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        ticks = int(stat.rpartition(")")[2].split()[19])
        boot = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text(encoding="ascii").splitlines()
            if line.startswith("btime ")
        )
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _is_session_alive(pid: int, recorded_at: float) -> bool:
    """Whether the process that wrote a PID file at ``recorded_at`` still runs.

    A live PID alone is not proof: after a reboot Windows hands the same number
    to an unrelated process. The owner must have started before it wrote its
    PID file, so a process that started later is somebody else.
    """
    if not _is_pid_alive(pid):
        return False
    started = _process_start_time(pid)
    if started is None:
        return True  # Unknown start time does not prove the session is gone.
    return started <= recorded_at + _CLOCK_SLACK_SECONDS


def _remove_dirs(directories) -> bool:
    """Remove directories best-effort; True when none of them remains."""
    for directory in directories:
        shutil.rmtree(directory, ignore_errors=True)
    return not any(directory.exists() for directory in directories)


def clean_current_session(*, keep_logs: bool = False) -> None:
    """Remove working directories and logs of THIS session plus its PID file.

    With ``keep_logs`` the logs and the PID file stay: the console has just
    printed the log path, and the next start removes both once this process
    is gone. The PID file also stays when a directory could not be removed
    (e.g. a file locked by a still-running built EXE), so the next start
    retries instead of orphaning the directory.

    Best-effort: cleanup on window close must not cause an error.
    """
    base = state_dir() / "b"
    if not base.exists():
        return
    removed = _remove_dirs(list(base.glob(f"*-{_SESSION_ID}")))
    if keep_logs:
        return
    _clean_session_logs(_SESSION_ID)
    if removed:
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
    """Clean up working directories and logs nobody will use again.

    A session whose process is gone (see ``_is_session_alive``) loses its
    directories, logs and PID file; its PID file stays when a directory
    resists removal, so a later start retries. Directories with no session
    record at all are removed once older than ``ORPHAN_GRACE_SECONDS``.
    Live sessions are untouched.
    """
    base = state_dir() / "b"
    if not base.exists():
        return
    known: set[str] = {_SESSION_ID}
    for pid_file in base.glob(".pid-*"):
        sid = pid_file.name[len(".pid-") :]
        known.add(sid)
        if sid == _SESSION_ID:
            continue
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            recorded_at = pid_file.stat().st_mtime
        except (OSError, ValueError):
            continue  # Corrupted record does not prove the session can be removed.
        if _is_session_alive(pid, recorded_at):
            continue
        if not _remove_dirs([d for d in base.glob(f"*-{sid}") if d.is_dir()]):
            continue
        _clean_session_logs(sid)
        with suppress(OSError):
            pid_file.unlink(missing_ok=True)
    _clean_orphan_dirs(base, known)


def _clean_orphan_dirs(base: Path, known_sessions: set[str]) -> None:
    """Remove old working directories whose session has no PID file."""
    cutoff = time.time() - ORPHAN_GRACE_SECONDS
    for directory in base.iterdir():
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        _, _, sid = directory.name.partition("-")
        if sid in known_sessions:
            continue
        try:
            if directory.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        if sid and not directory.exists():
            _clean_session_logs(sid)


def tools_dir() -> Path:
    return state_dir() / "tools"


def logs_dir() -> Path:
    return state_dir() / "logs"
