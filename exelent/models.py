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
    # Skąd pochodzi ta zależność: "manifest", "import", "dynamic", "user".
    # Pusty string = nieznane (starszy kod).
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
class ConversionResult:
    ok: bool
    code: str | None = None
    encoding: str = "utf-8"
    steps: tuple[str, ...] = ()
    error_line: int | None = None
    error_text: str | None = None
    # Dla linii wyniku k (0-based) — numer linii w ORYGINALNYM TXT (1-based).
    # Zdejmowanie otoczki (ogrodzenia, etykieta, puste linie na brzegach)
    # przesuwa numeracje, wiec `error_line` bez tej mapy wskazywalby linie w
    # wycietym kodzie, ktorej uzytkownik nie znajdzie w swoim pliku.
    line_map: tuple[int, ...] = ()


@dataclass(frozen=True)
class ProjectAnalysis:
    root: Path
    scan: ScanResult
    entry_candidates: tuple[EntryCandidate, ...] = ()
    entry_certain: bool = True
    app_kind: AppKind = AppKind.CONSOLE
    app_kind_certain: bool = True
    # ONEDIR jest zachowawczym domyslnym trybem (B01): zasoby leza obok EXE
    # (odczyt przez wzgledna sciezke dziala), a zapis trafia obok EXE i zostaje.
    # ONEFILE to swiadomy reczny wybor obarczony ograniczeniem odczytu zasobow —
    # patrz `planning.onefile_limitation_issues`.
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
    """Plik zaakceptowany przez analizę (B08).

    Hash utrwala treść w momencie akceptacji; weryfikacja przed buildem łapie
    zmiany po analizie. `rel_path` jest znormalizowany do `/` — ścieżka
    względna do korzenia projektu."""

    rel_path: str
    sha256: str


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
    single_file: Path | None = None
    extra_sources: tuple[Path, ...] = ()
    total_download_bytes: int = 0
    # Konwersje TXT -> PY jako niemutowalne pary (nazwa_pliku, kod). Build
    # wykonuje DOKŁADNIE zaakceptowany plan. Krotka par zamiast dict, bo
    # ``frozen=True`` nie chroni modyfikowalnego słownika w środku.
    converted: tuple[tuple[str, str], ...] = ()
    # Inwentarz zaakceptowanych plików źródłowych i zasobów (B08). Materialization
    # kopiuje TYLKO te pliki i weryfikuje hash; nowe pliki dodane po analizie
    # nie wchodzą do builda bez ponownej analizy.
    source_inventory: tuple[SourceEntry, ...] = ()
    # Uwagi wykryte przy budowaniu planu (B07: kolizje zasobów, B05: niezgodności).
    # Rozdzielone od `BuildResult.issues` — te powstają PRZED startem builda.
    plan_issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    artifact: Path | None = None
    # Plik EXE do URUCHOMIENIA. Dla ONEFILE to to samo co ``artifact``; dla
    # ONEDIR ``artifact`` jest KATALOGIEM, a EXE leży w środku.
    executable_path: Path | None = None
    size_bytes: int = 0
    duration_s: float = 0.0
    log_path: Path | None = None
    issues: tuple[Issue, ...] = ()
