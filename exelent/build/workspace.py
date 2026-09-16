"""Project working copy.

The build never touches the user's directory: the intended user does not use
Git and cannot undo changes. Everything happens on a copy in %LOCALAPPDATA%.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from exelent.constants import EXCLUDED_DIRS, MAX_SCAN_BYTES, MAX_SCAN_FILES
from exelent.models import BuildPlan, Issue, IssueError, Severity
from exelent.runtime.paths import work_dir_for

# B10: how often to check the cancellation token while copying. Checking every
# file is cheap, but avoid needless overhead when there are only five files.
_CANCEL_CHECK_INTERVAL = 1


def workspace_for(root: Path, single_file: Path | None = None) -> Path:
    """Location of the working copy for the project at `root`.

    This is the single source of truth. The path used to be assembled twice —
    here and in `pyinstaller.py` — from the same components but independently.
    Changing one definition then started a build in a directory without code,
    which became visible only after many minutes of PyInstaller work.
    """
    return work_dir_for(root, single_file) / "src"


def _copy_and_verify(source: Path, target: Path, expected_hash: str) -> str | None:
    """Copy a file and verify its hash (B08).

    Return `None` on success, or the filename if the hash does not match.
    An empty `expected_hash` (the file could not be read during analysis)
    skips verification — copying still happens because lack of a hash means
    lack of evidence, not evidence of absence.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if not expected_hash:
        return None
    h = hashlib.sha256()
    with open(target, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    if h.hexdigest() != expected_hash:
        return source.name
    return None


def _check_cancel(cancel) -> None:
    """B10: interrupted copying produces `build_cancelled`, not an I/O error."""
    if cancel is not None and cancel.cancelled:
        raise IssueError(Issue("build_cancelled", Severity.INFO))


def _validate_rel_path(rel_path: str) -> bool:
    """Whether a relative path is safe to materialize (B08).

    Reject paths containing `..`, absolute paths, and other attempts to escape
    the workspace. Do not trust `relative_to` alone — inspect the raw text.
    """
    if not rel_path:
        return False
    # Absolute paths (Windows: `C:\\`, `\\\\server`, `/root`).
    if rel_path.startswith(("/", "\\")) or (len(rel_path) >= 2 and rel_path[1] == ":"):
        return False
    # `..` segments anywhere in the path.
    parts = rel_path.replace("\\", "/").split("/")
    return ".." not in parts


def materialize_workspace(plan: BuildPlan, cancel=None) -> Path:
    """Create a project working copy with inventory verification (B08).

    Copy ONLY files accepted by analysis (from the plan inventory), not the
    whole directory. New files added after analysis do not enter the build
    without another analysis pass. Write TXT->PY conversions from the plan.

    `cancel` (B10) interrupts copying between files. Cancellation before the
    copy creates no workspace; cancellation during copying cleans it up.

    When the inventory is empty (an older plan without B08), fall back to
    copying explicit plan fields — safer than copytree, though unverified."""
    _check_cancel(cancel)
    workspace = workspace_for(plan.root, plan.single_file)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)

    changed: list[str] = []
    # B08: the same limits as scanning — materialization may not copy more
    # files or bytes than analysis accepted.
    copied_files = 0
    copied_bytes = 0

    if plan.source_inventory:
        # B08: inventory copying — accepted files ONLY.
        inventory_lookup = {e.rel_path: e.sha256 for e in plan.source_inventory}
        for i, entry in enumerate(plan.source_inventory):
            if i % _CANCEL_CHECK_INTERVAL == 0:
                _check_cancel(cancel)
            # B08: path-traversal protection — a path with `..` or an absolute
            # path may not escape the workspace.
            if not _validate_rel_path(entry.rel_path):
                changed.append(f"{entry.rel_path} (disallowed path)")
                continue
            source = plan.root / entry.rel_path
            if not source.is_file():
                changed.append(f"{entry.rel_path} (deleted)")
                continue
            # B08: symlinks may escape the accepted scope — verify that the
            # target remains within the project root.
            if source.is_symlink():
                try:
                    real = source.resolve(strict=True)
                    root_real = plan.root.resolve(strict=True)
                    if root_real not in real.parents and real != root_real:
                        changed.append(f"{entry.rel_path} (symlink outside project)")
                        continue
                except OSError:
                    changed.append(f"{entry.rel_path} (unavailable symlink)")
                    continue
            target = workspace / entry.rel_path
            mismatch = _copy_and_verify(source, target, entry.sha256)
            if mismatch:
                changed.append(f"{entry.rel_path} (changed)")
            else:
                copied_files += 1
                try:
                    copied_bytes += target.stat().st_size
                except OSError:
                    pass
            # B08: shared limits — materialization copies no more than scanning.
            if copied_files > MAX_SCAN_FILES or copied_bytes > MAX_SCAN_BYTES:
                raise IssueError(
                    Issue("scan_truncated", Severity.BLOCKER, {"files": str(copied_files)})
                )
        # Ensure the entry file is in the workspace even if it did not enter
        # the inventory (TXT conversion -> a new .py file).
        entry_rel = plan.entry.relative_to(plan.root).as_posix()
        if entry_rel not in inventory_lookup and plan.entry.is_file():
            target = workspace / entry_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.entry, target)
    else:
        # Fallback: no inventory — copy explicit plan fields.
        all_sources: list[Path] = []
        if plan.single_file is not None:
            all_sources.append(plan.single_file)
        all_sources.extend(plan.extra_sources)
        # Add ALL .py files from the root for a project (not single-file mode).
        # Filter excluded directories just like the scanner (B08 fallback).
        if plan.single_file is None:
            for dirpath, dirnames, filenames in plan.root.walk():
                dirnames[:] = [
                    d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")
                ]
                for name in filenames:
                    if name.endswith((".py", ".pyw")):
                        all_sources.append(dirpath / name)
        for source in (*all_sources, *plan.data_files):
            try:
                rel = source.relative_to(plan.root)
            except ValueError:
                continue
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied_files += 1
            try:
                copied_bytes += target.stat().st_size
            except OSError:
                pass
            # B08: shared limits — materialization copies no more than scanning.
            if copied_files > MAX_SCAN_FILES or copied_bytes > MAX_SCAN_BYTES:
                raise IssueError(
                    Issue("scan_truncated", Severity.BLOCKER, {"files": str(copied_files)})
                )

    if changed:
        raise IssueError(
            Issue(
                "source_changed_after_analysis",
                Severity.BLOCKER,
                {"files": ", ".join(changed[:5])},
            )
        )

    for name, code in plan.converted:
        # `name` is a RELATIVE path (for example `pkg/help.py`), so recreate
        # the destination directory. Otherwise a conversion from a subfolder
        # lands at the root and two files with the same name overwrite one another.
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")

    # B05: copy manifests and constraints into the workspace so uv can expand
    # `-r`/`-c` using the correct path bases.
    for rel in (*plan.manifest_paths, *plan.constraint_paths):
        source = plan.root / rel
        if source.is_file():
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    return workspace
