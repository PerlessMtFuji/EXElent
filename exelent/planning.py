"""Od ProjectAnalysis (zgadywanie) do BuildPlan (decyzja).

Wspólny punkt dla CLI i GUI. Build nigdy nie zgaduje — dostaje gotowy plan.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from contextlib import suppress
from pathlib import Path

from exelent.models import AppKind, BuildPlan, OutputMode, ProjectAnalysis

_ILLEGAL = re.compile(r'[/\\:*?"<>|]')

# Delete-on-close: Windows usuwa plik w momencie zamknięcia ostatniego uchwytu,
# także wtedy, gdy proces zostanie ubity między utworzeniem a sprzątaniem.
# Poza Windows stała nie istnieje i zostaje zwykły `unlink` w `finally`.
_O_TEMPORARY = getattr(os, "O_TEMPORARY", 0)


def sanitize_exe_name(name: str) -> str:
    cleaned = _ILLEGAL.sub("-", name).strip().rstrip(".")
    return cleaned or "program"


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
        if not candidate.exists() or not _is_writable(candidate):
            continue
        if avoid_cloud and is_cloud_synced(candidate):
            # Chmura jest gorsza niz dysk lokalny, ale nieskonczenie lepsza
            # niz brak miejsca docelowego — zapamietujemy ja na wypadek, gdyby
            # zaden kandydat lokalny sie nie znalazl.
            cloudy = cloudy or candidate
            continue
        return candidate / folder

    # Zaden kandydat nie przeszedl sondy. Chmura bije brak miejsca; dalej
    # pierwsze miejsce WYBRANE przez projekt (Pulpit, a gdy go nie ma —
    # katalog domowy), nigdy katalog zrodlowy. `_dest_candidates` zawsze
    # konczy sie katalogiem domowym, wiec ten wybor istnieje.
    fallback = cloudy or next(path for path, avoid_cloud in candidates if not avoid_cloud)
    return fallback / folder


def make_plan(
    analysis: ProjectAnalysis,
    *,
    exe_name: str | None = None,
    entry: Path | None = None,
    icon: Path | None = None,
    dest_dir: Path | None = None,
    output_mode: OutputMode | None = None,
    app_kind: AppKind | None = None,
) -> BuildPlan:
    chosen_entry = entry or analysis.entry
    if chosen_entry is None:
        raise ValueError("brak pliku glownego — analiza nie znalazla kodu Pythona")

    name = sanitize_exe_name(exe_name or analysis.suggested_name)

    return BuildPlan(
        root=analysis.root,
        entry=Path(chosen_entry),
        app_kind=app_kind or analysis.app_kind,
        output_mode=output_mode or analysis.output_mode,
        exe_name=name,
        dest_dir=Path(dest_dir) if dest_dir else default_dest_dir(analysis.root, name),
        icon=Path(icon) if icon else analysis.suggested_icon,
        packages=tuple(d.package for d in analysis.dependencies if not d.optional),
        data_files=analysis.scan.data_files,
        # Policzone raz, w zadaniu 8, na prawdziwych treściach plików
        # (łącznie z tymi skonwertowanymi z `.txt`, których nie ma na dysku).
        hidden_imports=analysis.hidden_imports,
    )
