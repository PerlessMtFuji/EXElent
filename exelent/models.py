"""Struktury danych przepływające między warstwami. Wszystkie niemutowalne.

Rdzeń nigdy nie zwraca tekstu dla użytkownika — zwraca Issue z kodem,
który warstwa prezentacji tłumaczy przez exelent.i18n.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


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


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    data: Mapping[str, str] = field(default_factory=dict)


class IssueError(RuntimeError):
    """Wyjatek, ktory niesie gotowe `Issue` — nigdy surowego tekstu.

    Istnieje po to, zeby `run_build` mialo JEDNA lapke na wszystkie awarie,
    ktore warstwa nizej potrafi juz nazwac. Trzy waskie handlery na trzy typy
    wymyslone z nazwy to wzorzec, o ktorego rozszerzeniu nastepny wspolpracownik
    zapomni — i wtedy laik dostaje traceback zamiast zdania.

    `issues` moze byc dluzsze niz jeden element: warstwa rzucajaca czesto zna
    zarowno fakt ("srodowisko builda nie powstalo"), jak i przyczyne rozpoznana
    ze strumienia bledow narzedzia ("certyfikat nie przeszedl weryfikacji").
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


@dataclass(frozen=True)
class ScanResult:
    root: Path
    py_files: tuple[Path, ...] = ()
    text_candidates: tuple[Path, ...] = ()
    data_files: tuple[Path, ...] = ()
    icon_files: tuple[Path, ...] = ()
    requirements: Path | None = None
    file_count: int = 0
    total_bytes: int = 0
    truncated: bool = False


@dataclass(frozen=True)
class ConversionResult:
    ok: bool
    code: str | None = None
    encoding: str = "utf-8"
    steps: tuple[str, ...] = ()
    error_line: int | None = None
    error_text: str | None = None


@dataclass(frozen=True)
class ProjectAnalysis:
    root: Path
    scan: ScanResult
    entry_candidates: tuple[EntryCandidate, ...] = ()
    entry_certain: bool = True
    app_kind: AppKind = AppKind.CONSOLE
    app_kind_certain: bool = True
    output_mode: OutputMode = OutputMode.ONEFILE
    dependencies: tuple[Dependency, ...] = ()
    hidden_imports: tuple[str, ...] = ()
    converted: Mapping[str, str] = field(default_factory=dict)
    suggested_name: str = "program"
    suggested_icon: Path | None = None
    issues: tuple[Issue, ...] = ()

    @property
    def entry(self) -> Path | None:
        return self.entry_candidates[0].path if self.entry_candidates else None


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
    python_version: str = "3.12"


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    artifact: Path | None = None
    size_bytes: int = 0
    duration_s: float = 0.0
    log_path: Path | None = None
    issues: tuple[Issue, ...] = ()
