"""Safe publication of the finished artifact to the destination directory.

A subsequent build NEVER overwrites an existing file or directory — when names
collide a free one is chosen. Staging on the target volume and an atomic rename
guarantee that a crash does not leave half-copied files.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from exelent.diagnostics.patterns import map_os_error
from exelent.models import Issue, Severity

# Prefix for the staging directory/file. A leading dot so it does not stand
# out in Explorer, and a recognizable slug so this session's leftovers can be
# unambiguously distinguished from user files.
_STAGING_PREFIX = ".exelent-publish-"


def _tree_signature(path: Path) -> tuple[int, int]:
    """(file count, total bytes) — a cheap completeness check for the copy.

    We do not compare byte-for-byte: for a ONEDIR artifact that is hundreds of
    files and several hundred MB. Matching file count and total size is enough
    to catch a copy interrupted halfway (missing files, truncated file)."""
    if path.is_file():
        return 1, path.stat().st_size
    count = 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            count += 1
            total += item.stat().st_size
    return count, total


def _unique_target(dest_dir: Path, stem: str, suffix: str, start_at: int = 1) -> Path | None:
    """First free name: `stem+suffix`, then `stem (2)+suffix`, etc.

    `start_at` allows resuming numbering after losing a race for a name, so we
    do not restart checking from the beginning after every collision."""
    n = start_at
    while n < start_at + 10_000:
        name = f"{stem}{suffix}" if n == 1 else f"{stem} ({n}){suffix}"
        candidate = dest_dir / name
        if not candidate.exists():
            return candidate
        n += 1
    return None


def publish_artifact(
    source: Path, dest_dir: Path, exe_name: str, *, is_onedir: bool, cancel=None
) -> tuple[Path | None, tuple[Issue, ...]]:
    """Copies `source` to `dest_dir` under a free name and returns the result path.

    Returns `(path, ())` on success or `(None, issues)` on failure.
    Never modifies or deletes anything already present in `dest_dir`.
    """
    suffix = "" if is_onedir else ".exe"

    # B10: cancellation BEFORE copying does not create staging.
    if cancel is not None and cancel.cancelled:
        return None, (Issue("build_cancelled", Severity.INFO),)

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, _os_error_issues(exc, dest_dir)

    staging = dest_dir / f"{_STAGING_PREFIX}{uuid.uuid4().hex}"
    try:
        if is_onedir:
            shutil.copytree(source, staging)
        else:
            shutil.copy2(source, staging)
    except OSError as exc:
        _remove_quietly(staging)
        return None, _os_error_issues(exc, source)

    # B10: cancellation AFTER copying but BEFORE finalization — staging is
    # complete but not published. We clean it up; the previous artifact
    # remains untouched.
    if cancel is not None and cancel.cancelled:
        _remove_quietly(staging)
        return None, (Issue("build_cancelled", Severity.INFO),)

    try:
        complete = _is_complete(source, staging, exe_name, is_onedir)
    except OSError:
        _remove_quietly(staging)
        return None, (Issue("publish_incomplete", Severity.BLOCKER, {"name": exe_name}),)

    if not complete:
        _remove_quietly(staging)
        return None, (Issue("publish_incomplete", Severity.BLOCKER, {"name": exe_name}),)

    start_at = 1
    for _ in range(100):
        target = _unique_target(dest_dir, exe_name, suffix, start_at=start_at)
        if target is None:
            break
        try:
            staging.rename(target)
            return target, ()
        except FileExistsError:
            start_at = _next_index(target, exe_name, suffix) + 1
            continue
        except OSError as exc:
            _remove_quietly(staging)
            return None, _os_error_issues(exc, target)

    _remove_quietly(staging)
    return None, (Issue("publish_incomplete", Severity.BLOCKER, {"name": exe_name}),)


def _is_complete(source: Path, staging: Path, exe_name: str, is_onedir: bool) -> bool:
    if _tree_signature(source) != _tree_signature(staging):
        return False
    return not (is_onedir and not (staging / f"{exe_name}.exe").exists())


def _next_index(target: Path, stem: str, suffix: str) -> int:
    """Number extracted from the name `stem (n)+suffix`; 1 for `stem+suffix`."""
    name = target.name
    plain = f"{stem}{suffix}"
    if name == plain:
        return 1
    inner = name[len(stem) + 2 : len(name) - len(suffix) - 1]  # `stem (` … `)suffix`
    try:
        return int(inner)
    except ValueError:
        return 1


def _os_error_issues(exc: OSError, related: Path) -> tuple[Issue, ...]:
    mapped = map_os_error(exc)
    if mapped:
        return mapped
    return (Issue("publish_failed", Severity.BLOCKER, {"path": str(related)}),)


def _remove_quietly(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
