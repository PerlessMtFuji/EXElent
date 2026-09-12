"""Od ProjectAnalysis (zgadywanie) do BuildPlan (decyzja).

Wspólny punkt dla CLI i GUI. Build nigdy nie zgaduje — dostaje gotowy plan.
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

# --- B05: zbieranie ścieżek manifestów i constraints z pliku requirements ---


def _collect_manifest_paths(
    requirements_path: Path | None,
    root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Zbiera ścieżki manifestów i constraints z drzewa `-r`/`-c` w requirements.

    Zwraca (manifest_paths, constraint_paths) jako krotki ścieżek WZGLĘDNYCH
    do korzenia projektu. Ścieżki są potrzebne do przekopiowania plików do
    workspace i przekazania ich do uv z poprawnymi bazami ścieżek.
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

# Delete-on-close: Windows usuwa plik w momencie zamknięcia ostatniego uchwytu,
# także wtedy, gdy proces zostanie ubity między utworzeniem a sprzątaniem.
# Poza Windows stała nie istnieje i zostaje zwykły `unlink` w `finally`.
_O_TEMPORARY = getattr(os, "O_TEMPORARY", 0)


def sanitize_exe_name(name: str) -> str:
    cleaned = _ILLEGAL.sub("-", name).strip().rstrip(".")
    return cleaned or "program"


def onefile_limitation_issues(output_mode: OutputMode) -> tuple[Issue, ...]:
    """Ostrzezenia zwiazane z RECZNYM wyborem trybu wyjscia (B01).

    Zalecany tryb to ONEDIR — zasoby leza obok EXE i odczyt przez wzgledna
    sciezke dziala, a zapis trafia obok EXE i zostaje. ONEFILE rozpakowuje
    dolaczone pliki do katalogu tymczasowego (`_MEIPASS`), ktory znika przy
    zakonczeniu; katalog roboczy programu jest zakotwiczony w trwalym katalogu
    EXE, wiec ZAPIS nie ginie, ale ODCZYT zasobu przez `open('config.json')`
    moze nie znalezc pliku. Nie da sie tego udowodnic z gory (nie wiemy, czy
    program czyta zasoby), wiec kazdy reczny wybor ONEFILE dostaje widoczne
    ograniczenie zamiast zapewnienia o bezpieczenstwie — zamiast go po cichu
    ukrywac. Rdzen zwraca kod; tekst PL/EN sklada `i18n`.
    """
    if output_mode is OutputMode.ONEFILE:
        return (Issue("onefile_no_resource_guarantee", Severity.WARNING),)
    return ()


def _is_writable(path: Path) -> bool:
    """Czy da się utworzyć plik w `path` — bez zostawiania po sobie śladu.

    Dlaczego w ogóle zapis, skoro §7 specyfikacji mówi o nienaruszalności
    katalogu użytkownika: §7 chroni **katalog źródłowy**, a sondowane są
    wyłącznie kandydaci z `_dest_candidates` — czyli katalogi, w których za
    chwilę i tak powstanie folder `<Nazwa>-EXE`. Katalog źródłowy nie trafia
    tam nigdy: gdy leży w korzeniu dysku i jest własnym rodzicem, `_dest_
    candidates` pomija go w całości.

    Dlaczego nie `os.access(path, os.W_OK)`: na Windows odzwierciedla ono
    jedynie atrybut „tylko do odczytu", którego katalogi praktycznie nie
    używają, i całkowicie ignoruje listy ACL oraz blokady OneDrive. Zwróciłoby
    „można pisać" dla katalogu, do którego zapis i tak padnie — a wtedy build
    umiera po kilkunastu minutach pracy zamiast od razu wybrać Pulpit.

    Zapis jest tak zaprojektowany, żeby nie mógł zaszkodzić:
    - nazwa jest losowa, a flaga `O_EXCL` gwarantuje, że sonda nigdy nie
      nadpisze (ani nie skasuje) istniejącego pliku użytkownika,
    - `O_TEMPORARY` każe systemowi skasować plik przy zamknięciu uchwytu, więc
      nawet zabity w połowie proces nie zostawia śmiecia,
    - `unlink` w `finally` sprząta tam, gdzie `O_TEMPORARY` nie istnieje.
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


# Katalogi, ktore sa lokalnym oknem na dysk w chmurze. Wrzucenie tam 40 MB
# EXE uruchamia wysylke — a §7 specyfikacji wymienia "zsynchronizowana z
# chmura" obok "tylko do odczytu" jako powod, dla ktorego dane miejsce nie
# nadaje sie na wynik builda. Dopasowanie jest po CALEJ nazwie segmentu albo
# po jej poczatku ZAKONCZONYM spacja ("OneDrive - Firma"): katalog projektu
# nazwany "dropbox-klon" nie ma z Dropboxem nic wspolnego.
_CLOUD_DIR_NAMES = (
    "onedrive",
    "dropbox",
    "google drive",
    "icloud drive",
    "nextcloud",
    "creative cloud files",
)

# OneDrive publikuje swoja lokalizacje w srodowisku, wiec dziala takze wtedy,
# gdy uzytkownik zmienil nazwe katalogu.
_CLOUD_ENV_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")

# Pulpit uzytkownika wg Windows. Znany folder, nie zgadywana nazwa — patrz
# `_known_folder_desktop`.
_FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def _home_dir() -> Path:
    return Path(os.path.expanduser("~"))


def _known_folder_desktop() -> Path | None:
    r"""Prawdziwa sciezka Pulpitu prosto z Windows.

    Zgadywanie nazwy nie dziala w obie strony. Na dysku pulpit nazywa sie
    ZAWSZE `Desktop` — polskie „Pulpit" to nazwa wyswietlana z `desktop.ini`,
    wiec ramie sprawdzajace `~/Pulpit` bylo martwym kodem. Odwrotnie przy
    OneDrive Known Folder Move, wlaczanym domyslnie w polskim OOBE: pulpit
    przenosi sie do `%USERPROFILE%\OneDrive\Pulpit`, a `~/Desktop` potrafi
    zniknac. `_collect_artifact` robi `mkdir(parents=True)`, wiec zgadniety
    katalog po prostu POWSTAJE, EXE laduje w miejscu, ktorego uzytkownik nie
    oglada, a build melduje sukces. Znany folder zna obie sytuacje.
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
        if ole32.CLSIDFromString(_FOLDERID_DESKTOP, ctypes.byref(guid)) != 0:
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


def _desktop_dir() -> Path | None:
    """Pulpit, ale tylko jesli naprawde istnieje na dysku."""
    known = _known_folder_desktop()
    if known is not None and known.exists():
        return known
    guess = _home_dir() / "Desktop"
    return guess if guess.exists() else None


def _looks_like_cloud_name(name: str) -> bool:
    low = name.lower()
    return any(low == cloud or low.startswith(cloud + " ") for cloud in _CLOUD_DIR_NAMES)


def is_cloud_synced(path: Path) -> bool:
    """Czy sciezka lezy w katalogu synchronizowanym z chmura.

    Publiczna, bo tego samego rozroznienia potrzebuje diagnostyka: WinError
    1920 na pliku w OneDrive to plik trzymany w chmurze, a nie antywirus.
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
    """Kandydaci na katalog wynikowy, od najlepszego. Flaga: „omijaj chmure".

    Rodzic katalogu zrodlowego jest pierwszy, bo wynik ma lezec obok projektu.
    Odpada, gdy projekt lezy w korzeniu dysku: `Path("F:/").parent` to znowu
    `Path("F:/")`, wiec „obok" nie istnieje, a sonda zapisywalnosci pisalaby
    wprost do katalogu zrodlowego — dokladnie tego, czego zabrania §7. Wynik
    ladowalby w jego wnetrzu i przy kazdej kolejnej przebudowie byl kopiowany
    razem z projektem, wiec EXE puchloby z buildu na build.

    Chmury omijamy tylko przy rodzicu. Pulpit jest miejscem WYBRANYM przez
    projekt, bo uzytkownik na niego patrzy; gdy Windows przeniosl go do
    OneDrive, to nadal jest ten Pulpit i odsylanie kogos zamiast tego do
    katalogu domowego byloby gorsza usluga niz wysylka do chmury.
    """
    root = Path(root)
    candidates: list[tuple[Path, bool]] = []
    if root.parent != root:
        candidates.append((root.parent, True))
    desktop = _desktop_dir()
    if desktop is not None:
        candidates.append((desktop, False))
    candidates.append((_home_dir(), False))
    return tuple(candidates)


def default_dest_dir(root: Path, exe_name: str) -> Path:
    folder = f"{sanitize_exe_name(exe_name)}-EXE"
    # Lista kandydatow powstaje RAZ. Kazde pytanie o Pulpit to wywolanie Win32
    # `SHGetKnownFolderPath`, a kazdy sprawdzany kandydat to jeszcze sonda
    # zapisywalnosci — czyli, gdy Pulpit lezy w OneDrive, zdarzenie
    # synchronizacji. Sciezka awaryjna pytala o to samo po raz drugi.
    candidates = _dest_candidates(root)
    cloudy: Path | None = None

    for candidate, avoid_cloud in candidates:
        if not candidate.exists():
            continue
        # Pytanie o chmure idzie PRZED sonda zapisywalnosci, bo jest darmowe:
        # czyta nazwe i zmienne srodowiskowe, nie dotyka dysku. Odwrotna
        # kolejnosc oznaczala, ze dla projektu trzymanego w OneDrive kazdy
        # podglad planu tworzyl i kasowal plik w katalogu synchronizowanym —
        # czyli zdarzenie wysylki za kazdym razem, gdy uzytkownik tylko patrzy
        # na ekran 2, w katalogu, ktory i tak zaraz odpadal.
        if avoid_cloud and is_cloud_synced(candidate):
            # Chmura jest gorsza niz dysk lokalny, ale nieskonczenie lepsza
            # niz brak miejsca docelowego — zapamietujemy ja na wypadek, gdyby
            # zaden kandydat lokalny sie nie znalazl. Sonda poczeka do chwili,
            # w ktorej ten wybor naprawde bedzie potrzebny.
            cloudy = cloudy or candidate
            continue
        if not _is_writable(candidate):
            continue
        return candidate / folder

    # Zaden kandydat nie przeszedl sondy. Chmura bije brak miejsca; dalej
    # pierwsze miejsce WYBRANE przez projekt (Pulpit, a gdy go nie ma —
    # katalog domowy), nigdy katalog zrodlowy. `_dest_candidates` zawsze
    # konczy sie katalogiem domowym, wiec ten wybor istnieje.
    # Kandydat w chmurze nie byl dotad sondowany — tutaj po raz pierwszy ma
    # znaczenie, czy da sie do niego pisac. Gdy nie da, zostaje pierwsze
    # miejsce WYBRANE przez projekt: to samo, co przed odlozeniem sondy.
    if cloudy is not None and _is_writable(cloudy):
        return cloudy / folder

    fallback = next(path for path, avoid_cloud in candidates if not avoid_cloud)
    return fallback / folder


def _dedup(items: Iterable[str]) -> tuple[str, ...]:
    """Unikalne, z zachowaniem kolejności pierwszego wystąpienia."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def _detect_asset_collisions(analysis: ProjectAnalysis, exe_name: str) -> list[Issue]:
    """Wykrywa kolizje zasobów z wygenerowanymi plikami (B07).

    Sprawdzenia (case-insensitive, bo Windows):
    - zasób vs launcher (_exelent_launcher.py)
    - zasób vs nazwa EXE (np. program.exe)
    - zasób vs ikona w workspace (_exelent_icon.ico)
    - duplikaty ścieżek zasobów (np. Data.json i data.json na Windows)
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

        # Kolizja z plikami generowanymi przez build.
        base_name = data_path.name.lower()
        if base_name in reserved and data_path.parent == root:
            issues.append(
                Issue(
                    "asset_collides_with_generated",
                    Severity.WARNING,
                    {"file": rel, "generated": base_name},
                )
            )

        # Duplikat ścieżki (case-insensitive).
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
    """SHA-256 pliku — utrwala treść w momencie akceptacji (B08)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _build_source_inventory(analysis: ProjectAnalysis) -> tuple[SourceEntry, ...]:
    """Inwentarz plików zaakceptowanych przez analizę (B08).

    Zawiera źródła Pythona, zasoby, ikonę i manifesty — każdy z hashem.
    Konwersje TXT nie są na dysku, więc nie mają wpisu — ich treść jest
    utrwalona w `plan.converted`.
    """
    root = analysis.root
    entries: list[SourceEntry] = []
    seen: set[str] = set()

    # Źródła Pythona (bez konwersji — te istnieją tylko w pamięci).
    converted_paths = {root / rel for rel in analysis.converted}
    for path in analysis.scan.py_files:
        if path in converted_paths:
            continue
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    # Dodatkowe źródła z domknięcia importów (tryb jednoplikowy).
    for path in analysis.extra_sources:
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    # Zasoby.
    for path in analysis.scan.data_files:
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    # Ikona.
    if analysis.suggested_icon is not None:
        rel = analysis.suggested_icon.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(analysis.suggested_icon)))

    # Oryginalne TXT-y (źródło konwersji — potrzebne do ewentualnej weryfikacji).
    for path in analysis.scan.text_candidates:
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            entries.append(SourceEntry(rel_path=rel, sha256=_file_hash(path)))

    return tuple(sorted(entries, key=lambda e: e.rel_path))


def _build_resource_inventory(analysis: ProjectAnalysis) -> tuple[ResourceEntry, ...]:
    """Jawny inwentarz zasobów z wykluczeniami (B07).

    Każdy plik z `scan.data_files` jest klasyfikowany, mierzony i filtrowany.
    Pliki wykluczone (artefakty IDE, logi, pliki tymczasowe) dostają
    `included=False` — GUI wyświetla je wyszarzone i pozwala przywrócić.
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
    """Nazwy najwyższego poziomu modułów lokalnych — także tych skonwertowanych
    z `.txt`, których nie ma na dysku. Chronią przed potraktowaniem ręcznie
    dopisanego `mojpakiet.sub` jako brakującej paczki z PyPI."""
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
        raise ValueError("brak pliku glownego — analiza nie znalazla kodu Pythona")

    name = sanitize_exe_name(exe_name or analysis.suggested_name)

    # B07: kolizje zasobów z plikami generowanymi przez build.
    plan_issues = _detect_asset_collisions(analysis, name)

    # Moduły dopisane ręcznie na ekranie 2: przypadki, których statyczny skan nie
    # widzi (import dynamiczny, wtyczka). Scalane z tym, co znalazła analiza —
    # build wykonuje DOKŁADNIE plan, więc dopisania muszą być już w nim.
    extra_hidden, extra_deps = resolve_extra_modules(extra_modules, _local_module_names(analysis))

    # B05/B08: ścieżki manifestów i constraints do przekopiowania do workspace.
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
        data_files=analysis.scan.data_files,
        # Policzone raz, w zadaniu 8, na prawdziwych treściach plików
        # (łącznie z tymi skonwertowanymi z `.txt`, których nie ma na dysku),
        # plus ręczne dopisania użytkownika.
        hidden_imports=_dedup([*analysis.hidden_imports, *extra_hidden]),
        single_file=analysis.single_file,
        extra_sources=analysis.extra_sources,
        total_download_bytes=total_download_bytes,
        # Konwersje wędrują W PLANIE, żeby build dało się wykonać z samego
        # planu, bez ponownej analizy źródeł.
        converted=tuple(analysis.converted.items()),
        # Inwentarz utrwala listę zaakceptowanych plików z hashami (B08).
        # Materializacja kopiuje TYLKO te pliki i weryfikuje hash.
        source_inventory=_build_source_inventory(analysis),
        # B07: jawny inwentarz zasobów z klasyfikacją i wykluczeniami.
        resource_inventory=_build_resource_inventory(analysis),
        plan_issues=tuple(plan_issues),
        # B08: unikalny identyfikator planu — łączy raport z planem.
        plan_id=uuid.uuid4().hex,
        # B05/B08: zachowane manifesty do przekazania uv.
        manifest_paths=manifest_paths,
        constraint_paths=constraint_paths,
    )
