"""From ProjectAnalysis (guessing) to BuildPlan (decision).

Shared entry point for CLI and GUI. Build never guesses — it receives a ready plan.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import uuid
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path

from exelent.analysis.apptype import package_submodule_collections
from exelent.analysis.entrypoint import local_module_names
from exelent.build.launcher import LAUNCHER_FILENAME
from exelent.deps.resolve import resolve_extra_modules
from exelent.models import (
    AppKind,
    BuildPlan,
    Issue,
    OutputMode,
    ProjectAnalysis,
    ResourceEntry,
    Severity,
    SourceEntry,
    _classify_resource,
    should_exclude_resource,
)

# --- B05: collecting manifest and constraint paths from requirements file ---


def _collect_manifest_paths(
    requirements_path: Path | None,
    root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Collects manifest and constraint paths from the `-r`/`-c` tree in requirements.

    Returns (manifest_paths, constraint_paths) as tuples of paths RELATIVE
    to the project root. The paths are needed to copy the files to the
    workspace and pass them to uv with correct path bases.
    """
    if requirements_path is None:
        return (), ()

    manifests: list[str] = []
    constraints: list[str] = []
    seen: set[Path] = set()

    def _walk(path: Path, *, is_constraint: bool = False) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            return
        if is_constraint:
            constraints.append(rel)
        else:
            manifests.append(rel)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            lowered = line.lower()
            if lowered.startswith(("-r ", "--requirement ")):
                ref = line.split(None, 1)[1].strip()
                _walk(path.parent / ref, is_constraint=False)
            elif lowered.startswith(("-c ", "--constraint ")):
                ref = line.split(None, 1)[1].strip()
                _walk(path.parent / ref, is_constraint=True)

    _walk(requirements_path)
    return tuple(manifests), tuple(constraints)


_ILLEGAL = re.compile(r'[/\\:*?"<>|]')

# Delete-on-close: Windows removes the file when the last handle is closed,
# even if the process is killed between creation and cleanup.
# Outside Windows the constant does not exist and a plain `unlink` in `finally` remains.
_O_TEMPORARY = getattr(os, "O_TEMPORARY", 0)


def sanitize_exe_name(name: str) -> str:
    cleaned = _ILLEGAL.sub("-", name).strip().rstrip(".")
    return cleaned or "program"


def onefile_limitation_issues(output_mode: OutputMode) -> tuple[Issue, ...]:
    """Warnings related to MANUAL output mode selection (B01).

    The recommended mode is ONEDIR — resources sit next to the EXE and reading
    via a relative path works, while writes land next to the EXE and persist.
    ONEFILE unpacks bundled files to a temporary directory (`_MEIPASS`) which
    vanishes on exit; the working directory is anchored to the persistent EXE
    directory, so WRITES do not disappear, but READING a resource via
    `open('config.json')` may fail to find the file. This cannot be proven
    upfront (we don't know whether the program reads resources), so every
    manual ONEFILE selection gets a visible limitation instead of a silent
    safety guarantee. The core returns a code; PL/EN text is assembled by `i18n`.
    """
    if output_mode is OutputMode.ONEFILE:
        return (Issue("onefile_no_resource_guarantee", Severity.WARNING),)
    return ()


def _is_writable(path: Path) -> bool:
    """Whether a file can be created in `path` — without leaving any trace.

    Why a write at all, given that spec section 7 speaks of source directory
    immutability: section 7 protects the **source directory**, and we only
    probe candidates from `_dest_candidates` — directories where a
    `<Name>-EXE` folder is about to be created anyway. The source directory
    never ends up there: when it sits at the drive root and is its own parent,
    `_dest_candidates` skips it entirely.

    Why not `os.access(path, os.W_OK)`: on Windows it reflects only the
    "read-only" attribute, which directories practically never use, and
    completely ignores ACLs and OneDrive locks. It would return "writable"
    for a directory where writing will fail anyway — and then the build dies
    after several minutes of work instead of immediately choosing the Desktop.

    The write is designed so it cannot cause harm:
    - the name is random and the `O_EXCL` flag guarantees the probe never
      overwrites (or deletes) an existing user file,
    - `O_TEMPORARY` tells the OS to delete the file when the handle is closed,
      so even a half-killed process leaves no garbage,
    - `unlink` in `finally` cleans up where `O_TEMPORARY` does not exist.
    """
    probe = Path(path) / f".exelent-probe-{uuid.uuid4().hex}.tmp"
    try:
        handle = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_RDWR | _O_TEMPORARY)
    except OSError:
        return False
    try:
        os.close(handle)
    finally:
        with suppress(OSError):
            os.unlink(probe)
    return True


# Directories that are local windows onto a cloud drive. Dropping a 40 MB EXE
# there triggers an upload — and spec section 7 lists "cloud-synced" alongside
# "read-only" as a reason a location is unsuitable for build output. Matching
# is by FULL segment name or by its prefix ENDING with a space ("OneDrive - Corp"):
# a project directory named "dropbox-clone" has nothing to do with Dropbox.
_CLOUD_DIR_NAMES = (
    "onedrive",
    "dropbox",
    "google drive",
    "icloud drive",
    "nextcloud",
    "creative cloud files",
)

# OneDrive publishes its location in the environment, so it works even when
# the user has renamed the directory.
_CLOUD_ENV_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")

# Known Windows folders — GUIDs per KNOWNFOLDERID. Used to query
# SHGetKnownFolderPath instead of guessing the directory name (see docstring
# of `_known_folder_desktop`).
_FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
_FOLDERID_DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"


def _home_dir() -> Path:
    return Path(os.path.expanduser("~"))


def _known_folder(folderid: str) -> Path | None:
    """Real Known Folder path straight from the Windows Shell API.

    Guessing the name does not work both ways. On disk the desktop is ALWAYS
    called `Desktop` — the Polish "Pulpit" is a display name from `desktop.ini`,
    so a branch checking `~/Pulpit` was dead code. Conversely, with OneDrive
    Known Folder Move (enabled by default in the Polish OOBE) the desktop
    moves to `%USERPROFILE%\\OneDrive\\Pulpit`, and `~/Desktop` may vanish.
    `_collect_artifact` calls `mkdir(parents=True)`, so a guessed directory
    simply APPEARS, the EXE lands in a place the user never looks at, and the
    build reports success. The Known Folder knows both situations.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Guid(ctypes.Structure):
            _fields_ = (
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            )

        ole32 = ctypes.windll.ole32
        guid = _Guid()
        if ole32.CLSIDFromString(folderid, ctypes.byref(guid)) != 0:
            return None
        buffer = ctypes.c_wchar_p()
        if (
            ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(guid), 0, None, ctypes.byref(buffer)
            )
            != 0
        ):
            return None
        try:
            return Path(buffer.value) if buffer.value else None
        finally:
            ole32.CoTaskMemFree(buffer)
    except (AttributeError, OSError, ValueError):
        return None


def _known_folder_desktop() -> Path | None:
    """Desktop via Windows Known Folder — thin wrapper for compatibility."""
    return _known_folder(_FOLDERID_DESKTOP)


def _desktop_dir() -> Path | None:
    """Desktop, but only if it actually exists on disk."""
    known = _known_folder_desktop()
    if known is not None and known.exists():
        return known
    guess = _home_dir() / "Desktop"
    return guess if guess.exists() else None


def _downloads_dir() -> Path | None:
    """Downloads, but only if it actually exists on disk.

    On Windows, Downloads may be relocated by OneDrive KFM, so we ask
    the Shell API first and only then try ~/Downloads.
    """
    known = _known_folder(_FOLDERID_DOWNLOADS)
    if known is not None and known.exists():
        return known
    guess = _home_dir() / "Downloads"
    return guess if guess.exists() else None


def _is_home_or_above(path: Path) -> bool:
    """Whether the path is the user's home directory or its parent.

    The home directory (e.g. C:\\Users\\MeMeMe) is not a place where a
    non-technical user expects to find the result — they only see it after
    opening Explorer and manually navigating into the profile. Desktop and
    Downloads are visible immediately.
    """
    return _home_dir().is_relative_to(path)


def _looks_like_cloud_name(name: str) -> bool:
    low = name.lower()
    return any(low == cloud or low.startswith(cloud + " ") for cloud in _CLOUD_DIR_NAMES)


def is_cloud_synced(path: Path) -> bool:
    """Whether the path lies in a cloud-synced directory.

    Public because the same distinction is needed by diagnostics: WinError
    1920 on a file in OneDrive means a cloud-only file, not antivirus.
    """
    path = Path(path)
    if any(_looks_like_cloud_name(part) for part in path.parts):
        return True
    for variable in _CLOUD_ENV_VARS:
        value = os.environ.get(variable)
        if not value:
            continue
        with suppress(OSError, ValueError):
            if path == Path(value) or path.is_relative_to(Path(value)):
                return True
    return False


def _dest_candidates(root: Path) -> tuple[tuple[Path, bool], ...]:
    """Candidates for the output directory, best first. Flag: "avoid cloud".

    The source directory's parent comes first because the result should sit
    next to the project. It is excluded in two situations:

    1. The project sits at the drive root: `Path("F:/").parent` is again
       `Path("F:/")`, so "next to" does not exist, and the writability probe
       would write directly into the source directory — exactly what spec
       section 7 forbids.

    2. The parent is the user's home directory or above (e.g. C:\\Users
       or C:\\Users\\MeMeMe): a non-technical user does not look inside
       the profile manually and would not find the EXE there. Desktop and
       Downloads are visible immediately.

    Cloud directories are avoided only for the parent. Desktop is a location
    CHOSEN by the project because the user looks at it; when Windows moved it
    into OneDrive, it is still the Desktop and sending someone to the home
    directory instead would be a worse service than an upload to the cloud.
    """
    root = Path(root)
    candidates: list[tuple[Path, bool]] = []
    if root.parent != root and not _is_home_or_above(root.parent):
        candidates.append((root.parent, True))
    desktop = _desktop_dir()
    if desktop is not None:
        candidates.append((desktop, False))
    downloads = _downloads_dir()
    if downloads is not None:
        candidates.append((downloads, False))
    candidates.append((_home_dir(), False))
    return tuple(candidates)


def default_dest_dir(root: Path, exe_name: str) -> Path:
    folder = f"{sanitize_exe_name(exe_name)}-EXE"
    # The candidate list is built ONCE. Every Desktop query is a Win32
    # `SHGetKnownFolderPath` call, and every candidate check is also a
    # writability probe — which, when Desktop is in OneDrive, is a sync
    # event. The fallback path used to query the same thing a second time.
    candidates = _dest_candidates(root)
    cloudy: Path | None = None

    for candidate, avoid_cloud in candidates:
        if not candidate.exists():
            continue
        # The cloud check goes BEFORE the writability probe because it is free:
        # it reads names and environment variables, does not touch the disk.
        # The reverse order meant that for a project kept in OneDrive, every
        # plan preview created and deleted a file in a synced directory — a
        # sync event every time the user just looked at screen 2, in a
        # directory that would be rejected anyway.
        if avoid_cloud and is_cloud_synced(candidate):
            # Cloud is worse than local disk but infinitely better than having
            # no destination at all — we remember it in case no local candidate
            # is found. The probe will wait until this choice actually matters.
            cloudy = cloudy or candidate
            continue
        if not _is_writable(candidate):
            continue
        return candidate / folder

    # No candidate passed the probe. Cloud beats no destination; then the first
    # location CHOSEN by the project (Desktop, or when absent — home directory),
    # never the source directory. `_dest_candidates` always ends with the home
    # directory, so this choice exists.
    # The cloud candidate was not probed before — here for the first time it
    # matters whether we can write to it. If not, the first CHOSEN location
    # by the project remains: the same as before deferring the probe.
    if cloudy is not None and _is_writable(cloudy):
        return cloudy / folder

    fallback = next(path for path, avoid_cloud in candidates if not avoid_cloud)
    return fallback / folder


def _dedup(items: Iterable[str]) -> tuple[str, ...]:
    """Unique items, preserving first-occurrence order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def _detect_asset_collisions(analysis: ProjectAnalysis, exe_name: str) -> list[Issue]:
    """Detects asset collisions with generated files (B07).

    Checks (case-insensitive, because Windows):
    - asset vs launcher (_exelent_launcher.py)
    - asset vs EXE name (e.g. program.exe)
    - asset vs icon in workspace (_exelent_icon.ico)
    - duplicate asset paths (e.g. Data.json and data.json on Windows)
    """
    issues: list[Issue] = []
    root = analysis.root
    reserved = {
        LAUNCHER_FILENAME.lower(),
        f"{exe_name}.exe".lower(),
        "_exelent_icon.ico",
    }

    seen: dict[str, Path] = {}
    for data_path in analysis.scan.data_files:
        try:
            rel = data_path.relative_to(root).as_posix()
        except ValueError:
            continue
        key = rel.lower()

        # Collision with files generated by the build.
        base_name = data_path.name.lower()
        if base_name in reserved and data_path.parent == root:
            issues.append(
                Issue(
                    "asset_collides_with_generated",
                    Severity.WARNING,
                    {"file": rel, "generated": base_name},
                )
            )

        # Duplicate path (case-insensitive).
        if key in seen:
            existing = seen[key].relative_to(root).as_posix()
            issues.append(
                Issue(
                    "asset_path_collision",
                    Severity.BLOCKER,
                    {"file_a": existing, "file_b": rel},
                )
            )
        else:
            seen[key] = data_path

    return issues


def _file_hash(path: Path) -> str:
    """SHA-256 of a file — captures content at acceptance time (B08)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _build_source_inventory(analysis: ProjectAnalysis) -> tuple[SourceEntry, ...]:
    """Inventory of files accepted by analysis (B08).

    Contains Python sources, resources, icon, and manifests — each with a hash.
    TXT conversions are not on disk, so they have no entry — their content is
    captured in `plan.converted`.
    """
    root = analysis.root
    entries: list[SourceEntry] = []
    seen: set[str] = set()

    # Python sources (excluding conversions — those exist only in memory).
    converted_paths = {root / rel for rel in analysis.converted}
    for path in analysis.scan.py_files:
        if path in converted_paths:
            continue
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    # Additional sources from import closure (single-file mode).
    for path in analysis.extra_sources:
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    # Resources.
    for path in analysis.scan.data_files:
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    # Icon.
    if analysis.suggested_icon is not None:
        rel = analysis.suggested_icon.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(analysis.suggested_icon)))

    # Original TXT files (conversion source — needed for eventual verification).
    for path in analysis.scan.text_candidates:
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    return tuple(sorted(entries, key=lambda e: e.rel_path))


def _build_resource_inventory(analysis: ProjectAnalysis) -> tuple[ResourceEntry, ...]:
    """Explicit resource inventory with exclusions (B07).

    Every file from `scan.data_files` is classified, measured, and filtered.
    Excluded files (IDE artifacts, logs, temporary files) get `included=False` —
    the GUI displays them grayed out and allows restoring.
    """
    root = analysis.root
    entries: list[ResourceEntry] = []
    seen: set[str] = set()

    for path in analysis.scan.data_files:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in seen:
            continue
        seen.add(rel)

        suffix = path.suffix.lower()
        name = path.name
        kind = _classify_resource(suffix)

        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        included = not should_exclude_resource(name, suffix)
        entries.append(
            ResourceEntry(
                rel_path=rel,
                size_bytes=size,
                kind=kind,
                included=included,
            )
        )

    return tuple(sorted(entries, key=lambda e: e.rel_path))


def _local_module_names(analysis: ProjectAnalysis) -> set[str]:
    """Top-level names of local modules — including those converted from `.txt`
    that do not exist on disk. Prevents treating a manually added `mypkg.sub`
    as a missing package from PyPI."""
    paths = [*analysis.scan.py_files, *(analysis.root / rel for rel in analysis.converted)]
    return local_module_names(analysis.root, {p: "" for p in paths})


def make_plan(
    analysis: ProjectAnalysis,
    *,
    exe_name: str | None = None,
    entry: Path | None = None,
    icon: Path | None = None,
    dest_dir: Path | None = None,
    output_mode: OutputMode | None = None,
    app_kind: AppKind | None = None,
    total_download_bytes: int = 0,
    extra_modules: Sequence[str] = (),
) -> BuildPlan:
    chosen_entry = entry or analysis.entry
    if chosen_entry is None:
        raise ValueError("no main file — analysis found no Python code")

    name = sanitize_exe_name(exe_name or analysis.suggested_name)

    # B07: asset collisions with files generated by the build.
    plan_issues = _detect_asset_collisions(analysis, name)

    # Modules added manually on screen 2: cases that the static scan cannot
    # see (dynamic import, plugin). Merged with what analysis found —
    # build executes EXACTLY the plan, so additions must already be in it.
    extra_hidden, extra_deps = resolve_extra_modules(extra_modules, _local_module_names(analysis))

    # Packages whose internal submodules escape PyInstaller's default analysis
    # (e.g. scipy._external.array_api_compat).  Derived from the detected
    # import names — both from static analysis and manually added modules.
    all_import_names = {d.import_name for d in analysis.dependencies} | set(extra_modules)
    collect_subs = package_submodule_collections(all_import_names)

    # B05/B08: manifest and constraint paths to copy to workspace.
    manifest_paths, constraint_paths = _collect_manifest_paths(
        analysis.scan.requirements, analysis.root
    )

    return BuildPlan(
        root=analysis.root,
        entry=Path(chosen_entry),
        app_kind=app_kind or analysis.app_kind,
        output_mode=output_mode or analysis.output_mode,
        exe_name=name,
        dest_dir=Path(dest_dir) if dest_dir else default_dest_dir(analysis.root, name),
        icon=Path(icon) if icon else analysis.suggested_icon,
        packages=_dedup(
            [d.package for d in analysis.dependencies if not d.optional]
            + [d.package for d in extra_deps]
        ),
        supplemental_packages=_dedup(
            [d.package for d in analysis.dependencies if not d.optional and d.origin != "manifest"]
            + [d.package for d in extra_deps]
        ),
        data_files=analysis.scan.data_files,
        # Computed once, in task 8, on real file contents (including those
        # converted from `.txt` that do not exist on disk), plus manual
        # additions by the user.
        hidden_imports=_dedup([*analysis.hidden_imports, *extra_hidden]),
        collect_submodules=collect_subs,
        single_file=analysis.single_file,
        extra_sources=analysis.extra_sources,
        total_download_bytes=total_download_bytes,
        # Conversions travel IN THE PLAN so the build can be executed from
        # the plan alone, without re-analyzing the sources.
        converted=tuple(analysis.converted.items()),
        # The inventory captures the list of accepted files with hashes (B08).
        # Materialization copies ONLY these files and verifies hashes.
        source_inventory=_build_source_inventory(analysis),
        # B07: explicit resource inventory with classification and exclusions.
        resource_inventory=_build_resource_inventory(analysis),
        plan_issues=tuple(plan_issues),
        # B08: unique plan identifier — links the report to the plan.
        plan_id=uuid.uuid4().hex,
        # B05/B08: preserved manifests for passing to uv.
        manifest_paths=manifest_paths,
        constraint_paths=constraint_paths,
    )
