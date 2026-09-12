"""Struktury danych przepływające między warstwami. Wszystkie niemutowalne.

Rdzeń nigdy nie zwraca tekstu dla użytkownika — zwraca Issue z kodem,
który warstwa prezentacji tłumaczy przez exelent.i18n.
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


def _freeze_data(data: Mapping[str, str]) -> MappingProxyType[str, str]:
    """Zamraża ``data`` Issue, żeby ``frozen=True`` nie kłamało.

    ``frozen=True`` na dataclasie blokuje przypisanie do atrybutu, ale NIE
    chroni modyfikowalnego obiektu wewnątrz: ``issue.data["key"] = "val"``
    przechodzi, gdy ``data`` jest zwykłym ``dict``. ``MappingProxyType`` jest
    widokiem tylko-do-odczytu na istniejącym ``dict`` — podnosi ``TypeError``
    przy próbie zmiany i kosztuje jedno opakowanie, nie kopię."""
    if isinstance(data, MappingProxyType):
        return data
    return MappingProxyType(dict(data))


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    data: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        # frozen=True → object.__setattr__. Zamrażamy `data` przy tworzeniu,
        # niezależnie od tego, co wołający przekazał.
        if not isinstance(self.data, MappingProxyType):
            object.__setattr__(self, "data", _freeze_data(self.data))


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


class ResourceKind(str, Enum):
    """Rodzaj zasobu wykrytego przez skaner (B07)."""

    DATA = "data"
    IMAGE = "image"
    CONFIG = "config"
    DATABASE = "database"


# Pliki, które wyglądają jak zasoby, ale prawie na pewno NIE powinny trafić
# do paczki: pliki testowe, generowane, IDE, build artifacts. Case-insensitive.
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
    """Rodzaj zasobu po sufiksie pliku."""
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return ResourceKind.DATABASE
    if suffix in {".json", ".ini", ".cfg", ".yaml", ".yml", ".toml", ".xml"}:
        return ResourceKind.CONFIG
    if suffix in {".png", ".jpg", ".jpeg", ".ico", ".bmp", ".gif"}:
        return ResourceKind.IMAGE
    return ResourceKind.DATA


@dataclass(frozen=True)
class ResourceEntry:
    """Zasób kandydujący do dołączenia do paczki (B07).

    `rel_path` jest ścieżką względną do korzenia projektu, znormalizowaną
    do `/`. `size_bytes` pozwala oszacować wpływ na rozmiar EXE. `kind`
    rozróżnia konfigurację od bazy danych od obrazu — użytkownik może
    zdecydować, że bazy danych nie powinny trafić do EXE. `included` to
    domyślna decyzja analizy; GUI pozwala ją zmienić.
    """

    rel_path: str
    size_bytes: int = 0
    kind: ResourceKind = ResourceKind.DATA
    included: bool = True


def should_exclude_resource(name: str, suffix: str) -> bool:
    """Czy plik o danej nazwie i sufiksie powinien być domyślnie wykluczony (B07)."""
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
    # B07: inwentarz zasobów kandydujących do dołączenia do paczki. Każdy
    # wpis ma klasyfikację (obraz, baza, konfiguracja), rozmiar i domyślną
    # decyzję; GUI pozwala zmienić `included` przed buildem.
    resource_inventory: tuple[ResourceEntry, ...] = ()
    # Uwagi wykryte przy budowaniu planu (B07: kolizje zasobów, B05: niezgodności).
    # Rozdzielone od `BuildResult.issues` — te powstają PRZED startem builda.
    plan_issues: tuple[Issue, ...] = ()
    # B08: identyfikator planu — UUID4 wygenerowany w `make_plan`. Łączy
    # raport, log i artefakt z DOKŁADNIE tym planem, który je stworzył.
    # Pusty string = starszy plan bez identyfikatora.
    plan_id: str = ""
    # B08: ścieżki manifestów zachowane z analizy. Kopiowane do workspace
    # i przekazywane do uv z poprawnymi bazami ścieżek (B05).
    manifest_paths: tuple[str, ...] = ()
    # B08: ścieżki plików constraints zachowane z analizy (B05).
    constraint_paths: tuple[str, ...] = ()


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
    # B06: rozstrzygnięte wersje paczek zainstalowanych w środowisku builda
    # (nazwa, wersja). Umożliwiają odtworzenie problemu i weryfikację
    # zgodności. Zapisywane w raporcie JSON.
    resolved_versions: tuple[tuple[str, str], ...] = ()
    # B08: identyfikator planu, który stworzył ten wynik.
    plan_id: str = ""
