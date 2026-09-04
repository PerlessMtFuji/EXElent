"""Sprowadzenie uv na dysk użytkownika. Jeden statyczny plik, który potrafi
pobrać przenośnego CPythona z tkinterem i pip-em oraz stworzyć izolowane
środowisko — czyli całą brudną robotę bootstrapu."""

from __future__ import annotations

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

UV_URL = (
    f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
)


class UvDownloadError(IssueError):
    """Nie udało się sprowadzić uv. Niesie ze sobą `Issue` dla warstwy
    prezentacji — nigdy surowego tekstu do pokazania użytkownikowi."""


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


def _download(url: str, progress: ProgressFn) -> bytes:
    """Pobiera `url` w całości, meldując po każdej porcji.

    Bajty są tu DOKŁADNE, nie zgadywane: `Content-Length` podaje sumę, a
    czytanie porcjami daje licznik. To jedyne pobranie w programie, które
    wie o sobie wszystko — instalacja paczek musi tę wiedzę składać z linii uv.
    """
    buffer = io.BytesIO()
    started = time.monotonic()
    with urllib.request.urlopen(url, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        while chunk := response.read(64 * 1024):
            buffer.write(chunk)
            read += len(chunk)
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
    return buffer.getvalue()


def _atomic_write(dest: Path, data: bytes) -> None:
    """Zapisuje `data` pod `dest` tak, że proces przerwany w połowie nigdy
    nie zostawia obciętego pliku pod finalną ścieżką.

    `ensure_uv` uznaje istnienie `dest` za dowód poprawnego cache — gdybyśmy
    pisali wprost do `dest`, zabity w połowie zapisu proces zostawiłby tam
    obcięty plik, który kolejne uruchomienie potraktowałoby jako gotowego
    uv.exe, i każdy późniejszy build psułby się w sposób niemożliwy do
    zdiagnozowania. Zapis do pliku tymczasowego w tym samym katalogu, a
    potem `os.replace` (atomowy w obrębie jednego wolumenu na Windows),
    eliminuje to okno.
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


def _download_and_extract_uv(url: str, dest: Path, progress: ProgressFn) -> None:
    payload = _download(url, progress)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            if name.endswith("uv.exe"):
                data = archive.read(name)
                break
        else:
            raise FileNotFoundError("archiwum uv nie zawiera uv.exe")
    _atomic_write(dest, data)


def ensure_uv(progress: ProgressFn) -> Path:
    target = uv_path()
    if target.exists():
        return target
    try:
        _download_and_extract_uv(UV_URL, target, progress)
    except (urllib.error.URLError, OSError, zipfile.BadZipFile, FileNotFoundError) as exc:
        raise UvDownloadError(Issue("uv_download_failed", Severity.BLOCKER), exc) from exc
    return target
