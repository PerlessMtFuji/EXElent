"""Data structures flowing between layers. All immutable.

The core never returns user-facing text — it returns an Issue with a code,
which the presentation layer translates via exelent.i18n.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType


class AppKind(str, Enum):
    WINDOWED = "windowed"
    CONSOLE = "console"


class OutputMode(str, Enum):
    ONEFILE = "onefile"
    ONEDIR = "onedir"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class VerificationStatus(str, Enum):
    """Whether the finished artifact was actually launched and checked."""

    NOT_RUN = "not_run"
    PASSED = "passed"


def _freeze_data(data: Mapping[str, str]) -> MappingProxyType[str, str]:
    """Freezes Issue ``data`` so that ``frozen=True`` does not lie.

    ``frozen=True`` on a dataclass blocks attribute assignment but does NOT
    protect a mutable object inside: ``issue.data["key"] = "val"`` succeeds
    when ``data`` is a plain ``dict``. ``MappingProxyType`` is a read-only
    view over an existing ``dict`` — it raises ``TypeError`` on mutation
    and costs one wrapper, not a copy."""
    if isinstance(data, MappingProxyType):
        return data
    return MappingProxyType(dict(data))


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    data: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        # frozen=True -> object.__setattr__. We freeze `data` at creation,
        # regardless of what the caller passed.
        if not isinstance(self.data, MappingProxyType):
            object.__setattr__(self, "data", _freeze_data(self.data))


class IssueError(RuntimeError):
    """Exception that carries ready-made `Issue` objects — never raw text.

    Exists so that `run_build` has ONE catch for all failures that the layer
    below can already name. Three narrow handlers for three types invented
    by name is a pattern the next contributor will forget to extend — and
    then the end user gets a traceback instead of a sentence.

    `issues` may be longer than one element: the throwing layer often knows
    both the fact ("build environment was not created") and the cause
    recognized from the tool's error stream ("certificate verification failed").
    """

    def __init__(
        self,
        issue: Issue,
        cause: BaseException | None = None,
        *,
        extra: Sequence[Issue] = (),
    ) -> None:
        super().__init__(f"{issue.code}: {cause}" if cause is not None else issue.code)
        self.issue = issue
        self.issues: tuple[Issue, ...] = (issue, *extra)


@dataclass(frozen=True)
class EntryCandidate:
    path: Path
    score: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dependency:
    import_name: str
    package: str
    optional: bool = False
    heavy: bool = False
    # Where this dependency comes from: "manifest", "import", "dynamic", "user".
    # Empty string = unknown (legacy code).
    origin: str = ""


@dataclass(frozen=True)
class ScanResult:
    root: Path
    py_files: tuple[Path, ...] = ()
    text_candidates: tuple[Path, ...] = ()
    data_files: tuple[Path, ...] = ()
    icon_files: tuple[Path, ...] = ()
    requirements: Path | None = None
    pyproject: Path | None = None
    file_count: int = 0
    total_bytes: int = 0
    truncated: bool = False
    single_file: Path | None = None


@dataclass(frozen=True)
class CodeBlockSpan:
    """Boundaries of a single code block in the original TXT (1-based, inclusive).

    Used when TXT conversion extracts multiple fenced blocks (```python)
    and merges them into one PY file. Shows the user where each part of
    the result originates and how they were combined (B02)."""

    start_line: int
    end_line: int


@dataclass(frozen=True)
class ConversionResult:
    ok: bool
    code: str | None = None
    encoding: str = "utf-8"
    steps: tuple[str, ...] = ()
    error_line: int | None = None
    error_text: str | None = None
    # For output line k (0-based) — line number in the ORIGINAL TXT (1-based).
    # Stripping the wrapper (fences, label, empty lines at edges) shifts
    # numbering, so `error_line` without this map would point at a line in
    # the extracted code that the user cannot find in their file.
    line_map: tuple[int, ...] = ()
    # Boundaries of code blocks extracted from TXT (B02). Empty when the input
    # had no fences or contained only one block. When there is more than one —
    # the presentation layer shows their boundaries and explains how they were combined.
    code_blocks: tuple[CodeBlockSpan, ...] = ()


@dataclass(frozen=True)
class ProjectAnalysis:
    root: Path
    scan: ScanResult
    entry_candidates: tuple[EntryCandidate, ...] = ()
    entry_certain: bool = True
    app_kind: AppKind = AppKind.CONSOLE
    app_kind_certain: bool = True
    # ONEDIR is the conservative default mode (B01): resources sit next to the EXE
    # (reading via relative path works), and writes land next to the EXE and persist.
    # ONEFILE is a deliberate manual choice burdened with a resource-read limitation —
    # see `planning.onefile_limitation_issues`.
    output_mode: OutputMode = OutputMode.ONEDIR
    dependencies: tuple[Dependency, ...] = ()
    hidden_imports: tuple[str, ...] = ()
    converted: Mapping[str, str] = field(default_factory=dict)
    suggested_name: str = "program"
    suggested_icon: Path | None = None
    issues: tuple[Issue, ...] = ()
    single_file: Path | None = None
    extra_sources: tuple[Path, ...] = ()

    @property
    def entry(self) -> Path | None:
        return self.entry_candidates[0].path if self.entry_candidates else None


@dataclass(frozen=True)
class SourceEntry:
    """File accepted by analysis (B08).

    The hash captures content at acceptance time; verification before build
    catches changes after analysis. `rel_path` is normalized to `/` — a path
    relative to the project root."""

    rel_path: str
    sha256: str


class ResourceKind(str, Enum):
    """Kind of resource detected by the scanner (B07)."""

    DATA = "data"
    IMAGE = "image"
    CONFIG = "config"
    DATABASE = "database"


# Files that look like resources but almost certainly should NOT go into the
# package: test files, generated files, IDE files, build artifacts. Case-insensitive.
_RESOURCE_EXCLUDE_NAMES = frozenset(
    {
        "thumbs.db",
        "desktop.ini",
        ".ds_store",
        ".gitkeep",
        ".gitignore",
    }
)
_RESOURCE_EXCLUDE_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".egg-info",
        ".dist-info",
        ".bak",
        ".tmp",
        ".swp",
        ".swo",
        ".log",
        ".orig",
    }
)


def _classify_resource(suffix: str) -> ResourceKind:
    """Resource kind by file suffix."""
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return ResourceKind.DATABASE
    if suffix in {".json", ".ini", ".cfg", ".yaml", ".yml", ".toml", ".xml"}:
        return ResourceKind.CONFIG
    if suffix in {".png", ".jpg", ".jpeg", ".ico", ".bmp", ".gif"}:
        return ResourceKind.IMAGE
    return ResourceKind.DATA


@dataclass(frozen=True)
class ResourceEntry:
    """Resource candidate for inclusion in the package (B07).

    `rel_path` is a path relative to the project root, normalized to `/`.
    `size_bytes` allows estimating the impact on EXE size. `kind` distinguishes
    config from database from image — the user may decide that databases should
    not go into the EXE. `included` is the default decision from analysis;
    the GUI allows changing it.
    """

    rel_path: str
    size_bytes: int = 0
    kind: ResourceKind = ResourceKind.DATA
    included: bool = True


def should_exclude_resource(name: str, suffix: str) -> bool:
    """Whether a file with the given name and suffix should be excluded by default (B07)."""
    if name.lower() in _RESOURCE_EXCLUDE_NAMES:
        return True
    return suffix.lower() in _RESOURCE_EXCLUDE_SUFFIXES


@dataclass(frozen=True)
class BuildPlan:
    root: Path
    entry: Path
    app_kind: AppKind
    output_mode: OutputMode
    exe_name: str
    dest_dir: Path
    icon: Path | None = None
    packages: tuple[str, ...] = ()
    data_files: tuple[Path, ...] = ()
    hidden_imports: tuple[str, ...] = ()
    # Subpackage trees that PyInstaller should recursively collect
    # (``--collect-submodules``).  Derived from PACKAGE_COLLECT_SUBMODULES when
    # a known library (e.g. scipy) is among the detected imports.
    collect_submodules: tuple[str, ...] = ()
    python_version: str = "3.12"
    single_file: Path | None = None
    extra_sources: tuple[Path, ...] = ()
    total_download_bytes: int = 0
    # TXT -> PY conversions as immutable pairs (filename, code). Build executes
    # EXACTLY the accepted plan. Tuple of pairs instead of dict because
    # ``frozen=True`` does not protect a mutable dict inside.
    converted: tuple[tuple[str, str], ...] = ()
    # Inventory of accepted source files and resources (B08). Materialization
    # copies ONLY these files and verifies hashes; new files added after analysis
    # do not enter the build without re-analysis.
    source_inventory: tuple[SourceEntry, ...] = ()
    # B07: resource inventory with candidates for package inclusion. Each entry
    # has a classification (image, database, config), size, and a default
    # decision; the GUI allows changing `included` before the build.
    resource_inventory: tuple[ResourceEntry, ...] = ()
    # Issues detected while building the plan (B07: asset collisions, B05: incompatibilities).
    # Separate from `BuildResult.issues` — these arise BEFORE the build starts.
    plan_issues: tuple[Issue, ...] = ()
    # B08: plan identifier — UUID4 generated in `make_plan`. Links the report,
    # log, and artifact to EXACTLY the plan that created them.
    # Empty string = legacy plan without an identifier.
    plan_id: str = ""
    # B08: manifest paths preserved from analysis. Copied to workspace and
    # passed to uv with correct path bases (B05).
    manifest_paths: tuple[str, ...] = ()
    # B08: constraint file paths preserved from analysis (B05).
    constraint_paths: tuple[str, ...] = ()
    # Packages detected in code or added manually that the manifest does not
    # declare. When uv receives `-r`, these specs must still go into the joint
    # install, otherwise the finished EXE is missing an imported module.
    supplemental_packages: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    artifact: Path | None = None
    # EXE file to LAUNCH. For ONEFILE this is the same as ``artifact``; for
    # ONEDIR ``artifact`` is a DIRECTORY and the EXE sits inside.
    executable_path: Path | None = None
    size_bytes: int = 0
    duration_s: float = 0.0
    log_path: Path | None = None
    issues: tuple[Issue, ...] = ()
    # B06: resolved versions of packages installed in the build environment
    # (name, version). Enable problem reproduction and compatibility
    # verification. Saved in the JSON report.
    resolved_versions: tuple[tuple[str, str], ...] = ()
    # B08: identifier of the plan that created this result.
    plan_id: str = ""
    # PyInstaller success alone means the artifact was created. Only a controlled
    # behavior test can set PASSED; clicking "Run" in the GUI does not know the
    # user application's exit code and does not elevate this status.
    verification: VerificationStatus = VerificationStatus.NOT_RUN
