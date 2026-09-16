"""Bootstrap uv onto the user's disk. A single static file that can download
a portable CPython with tkinter and pip and create an isolated environment
— i.e. all the dirty work of bootstrapping."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import suppress
from pathlib import Path

from exelent.constants import MIN_FREE_DISK_BYTES, UV_VERSION
from exelent.models import Issue, IssueError, Severity
from exelent.runtime import Progress, ProgressFn
from exelent.runtime.paths import state_dir, tools_dir

# Timeout for reading a single chunk from the server. The whole operation may
# take longer (many chunks), but NO single chunk may hang forever — otherwise
# closing the window waits until the server deigns to respond.
_DOWNLOAD_READ_TIMEOUT = 30

# How often we check the cancellation token during download.
_CANCEL_CHECK_BYTES = 256 * 1024

UV_URL = (
    f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
)
UV_ZIP_SHA256 = "0d051779fbcb173b183efeae1c3e96148764fd82709bbbf0966df3efe48b67c5"


class UvDownloadError(IssueError):
    """Failed to download uv. Carries an `Issue` for the presentation layer
    — never raw text to show the user."""


def uv_path() -> Path:
    return tools_dir() / f"uv-{UV_VERSION}" / "uv.exe"


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _has_network(host: str = "pypi.org", port: int = 443, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_preconditions(*, need_network: bool) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    free = _free_bytes(state_dir())
    if free < MIN_FREE_DISK_BYTES:
        issues.append(
            Issue(
                "low_disk_space",
                Severity.BLOCKER,
                {
                    "free_gb": f"{free / 1024**3:.1f}",
                    "needed_gb": f"{MIN_FREE_DISK_BYTES / 1024**3:.0f}",
                },
            )
        )
    if need_network and not _has_network():
        issues.append(Issue("no_network", Severity.BLOCKER))
    return tuple(issues)


def _download(url: str, progress: ProgressFn, cancel=None) -> bytes:
    """Download ``url`` in full, reporting progress after each chunk.

    ``cancel`` aborts the download between chunks. A timeout on each
    ``read`` prevents a hanging session.
    """
    buffer = io.BytesIO()
    started = time.monotonic()
    with urllib.request.urlopen(url, timeout=_DOWNLOAD_READ_TIMEOUT) as response:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        since_check = 0
        while chunk := response.read(64 * 1024):
            buffer.write(chunk)
            read += len(chunk)
            since_check += len(chunk)
            elapsed = time.monotonic() - started
            speed = read / elapsed if elapsed > 0 else 0.0
            remaining = max(total - read, 0)
            progress(
                Progress(
                    phase="download_uv",
                    fraction=read / total if total else 0.0,
                    done_bytes=read,
                    total_bytes=total,
                    speed_bps=speed,
                    eta_s=remaining / speed if speed > 0 and total else None,
                )
            )
            if cancel is not None and since_check >= _CANCEL_CHECK_BYTES:
                since_check = 0
                if cancel.cancelled:
                    raise IssueError(Issue("build_cancelled", Severity.INFO))
    return buffer.getvalue()


def _atomic_write(dest: Path, data: bytes) -> None:
    """Write ``data`` to ``dest`` atomically (tmpfile + ``os.replace``).

    An interrupted process never leaves a truncated file at the final path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".uv-download-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
        os.replace(tmp_name, dest)
    except BaseException:
        with suppress(OSError):
            os.remove(tmp_name)
        raise


def _download_and_extract_uv(url: str, dest: Path, progress: ProgressFn, cancel=None) -> None:
    payload = _download(url, progress, cancel=cancel)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != UV_ZIP_SHA256:
        raise UvDownloadError(Issue("uv_download_failed", Severity.BLOCKER))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            if name.endswith("uv.exe"):
                data = archive.read(name)
                break
        else:
            raise FileNotFoundError("uv archive does not contain uv.exe")
    _atomic_write(dest, data)


# uv.exe is ~30 MB; a file smaller than 1 MB is corrupted (truncated write,
# antivirus intervention). The PE header ("MZ") confirms binary format.
_UV_MIN_SIZE = 1024 * 1024


def _is_valid_uv(path: Path) -> bool:
    """Whether the file looks like a valid uv executable."""
    try:
        size = path.stat().st_size
        if size < _UV_MIN_SIZE:
            return False
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def ensure_uv(progress: ProgressFn, cancel=None) -> Path:
    """Ensure uv is on disk. Verifies integrity of an existing file.

    A cancelled token before start prevents the download. The shared cache
    is safe: writes are atomic (``_atomic_write``), and uv manages its own
    package cache without needing additional locks.
    """
    if cancel is not None and cancel.cancelled:
        raise IssueError(Issue("build_cancelled", Severity.INFO))
    target = uv_path()
    if target.exists():
        if _is_valid_uv(target):
            return target
        # Corrupted file — delete and re-download.
        with suppress(OSError):
            target.unlink(missing_ok=True)
    try:
        _download_and_extract_uv(UV_URL, target, progress, cancel=cancel)
    except (urllib.error.URLError, OSError, zipfile.BadZipFile, FileNotFoundError) as exc:
        raise UvDownloadError(Issue("uv_download_failed", Severity.BLOCKER), exc) from exc
    return target
