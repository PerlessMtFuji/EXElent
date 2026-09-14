"""Ile to zajmie: w EXE i w pobieraniu. To dwie różne liczby.

Rozmiar POBIERANIA bierze się z rozwiązanych wersji, braków cache i z PyPI
(zadania 16–17). Rozmiar EXE jest szacunkiem z widełkami, bo PyInstaller
wyrzuca z paczki to, czego kod nie dotyka: ten sam `pandas` waży inaczej w
skrypcie czytającym jeden CSV, a inaczej w programie używającym połowy API.

Zgłoszenie 7 mówi dokładnie o tym, że liczby wzięte z sufitu wprowadzają w
błąd. Dlatego każdy wpis niesie `measured` — datę pomiaru albo słowo
„tymczasowe". Zadanie 15 zamienia wszystkie „tymczasowe" na daty.
"""

from __future__ import annotations

import functools
import json
import re
import tempfile
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from packaging.tags import Tag, compatible_tags, cpython_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from exelent.constants import TARGET_PYTHON
from exelent.runtime.env import run_uv
from exelent.runtime.uvlog import PACKAGE, UNCACHED_PACKAGE, WOULD_DOWNLOAD, parse_line

# Znacznik ABI koła, którego naprawdę użyje build: CPython w wersji docelowej,
# 64-bitowy Windows. Koło dla innej wersji albo innego systemu opisuje plik,
# którego nigdy nie pobierzemy.
_PLATFORM = "win_amd64"
_UV_PLATFORM = "x86_64-pc-windows-msvc"
_PYPI = "https://pypi.org/pypi/{name}/{version}/json"
_MAX_PARALLEL = 8

# Powyżej tylu megabajtów górnych widełek rozmiar przestaje być informacją,
# a staje się ostrzeżeniem (razem z uwagą o dłuższym budowaniu).
LARGE_WARNING_MB = 300

# Ile waży EXE z pustego skryptu `print('x')` — sam interpreter, biblioteka
# standardowa i loader PyInstallera. ZMIERZONE 2026-09-04: 10,5 MB.
# Wchodzi do szacunku, bo zdanie mówi „gotowy program zajmie", a nie „paczki
# dołożą": bez tej stałej szacunek zaniżał wynik o stałe 10 MB.
BASE_EXE_MB = 11

# Powyżej tylu megabajtów górnego wkładu paczka jest „ciężka" — to zastępuje
# dawny płaski `HEAVY_PACKAGES`.
HEAVY_THRESHOLD_MB = 15


@dataclass(frozen=True)
class Contribution:
    """Wkład paczki do gotowego EXE, w megabajtach.

    `measured` to data pomiaru w formacie `YYYY-MM-DD` albo słowo
    „tymczasowe". Test `test_every_entry_declares_where_its_number_came_from`
    pilnuje, że pole nigdy nie jest puste — liczba bez źródła jest tym,
    przeciwko czemu ten moduł powstał.
    """

    low_mb: int
    high_mb: int
    measured: str


# Wpisy z datą są ZMIERZONE dwoma prawdziwymi buildami każdy (patrz
# `tests/test_exe_contribution_measurement.py`):
#   - dolny koniec: skrypt, który paczkę tylko importuje i dotyka jednej
#     rzeczy — PyInstaller wyrzuca wtedy większą część drzewa,
#   - górny koniec: skrypt, który paczki naprawdę używa, plus 25% zapasu.
# Zapas nie jest wzięty z sufitu: na jedynym zmierzonym POŁĄCZENIU paczek
# (matplotlib + pandas + scipy, 172,4 MB) suma samych pomiarów schodziła
# ~20% poniżej wyniku, bo złożenie wciąga więcej niż każda paczka osobno.
#
# `tymczasowe` znaczy: NIE ZMIERZONE, liczba orientacyjna. Zostały takie
# `torch`, `tensorflow` i `transformers` — ich pomiar to kilka gigabajtów
# pobierania i świadomie go nie wykonano.
EXE_CONTRIBUTION: dict[str, Contribution] = {
    "torch": Contribution(300, 900, "tymczasowe"),
    "tensorflow": Contribution(250, 700, "tymczasowe"),
    "transformers": Contribution(60, 200, "tymczasowe"),
    "scipy": Contribution(18, 51, "2026-09-04"),
    "opencv-python": Contribution(53, 67, "2026-09-04"),
    "matplotlib": Contribution(27, 93, "2026-09-04"),
    "pandas": Contribution(20, 26, "2026-09-04"),
    "numpy": Contribution(11, 15, "2026-09-04"),
    "PySide6": Contribution(16, 21, "2026-09-04"),
    "PyQt5": Contribution(10, 36, "2026-09-04"),
    "PyQt6": Contribution(7, 18, "2026-09-04"),
    "librosa": Contribution(94, 119, "2026-09-04"),
    "moviepy": Contribution(49, 62, "2026-09-04"),
}


def _canonical(name: str) -> str:
    """Kanoniczna forma nazwy dystrybucji (PEP 503): małe litery, `-_.` scalone."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _base_name(spec: str) -> str:
    """Sama nazwa paczki z całej specyfikacji.

    `pandas==2.2.3` -> `pandas`, `uvicorn[standard]>=0.20` -> `uvicorn`. Bez
    tego tabela wkładów, kluczowana nazwą, nie rozpoznawała przypiętej wersji
    i szacunek dla `pandas==2.2.3` wynosił zero."""
    return re.split(r"[<>=!~;\[ @]", spec.strip(), maxsplit=1)[0].strip()


# Tabela wkładów wg formy kanonicznej, żeby `PySide6>=6.7`, `opencv_python`
# czy `pandas==2.2.3` trafiały w ten sam wpis co bare `PySide6`/`opencv-python`.
_CONTRIBUTION_BY_CANONICAL: dict[str, Contribution] = {
    _canonical(name): contribution for name, contribution in EXE_CONTRIBUTION.items()
}


def _contribution_for(spec: str) -> Contribution | None:
    return _CONTRIBUTION_BY_CANONICAL.get(_canonical(_base_name(spec)))


def is_heavy(package: str) -> bool:
    entry = _contribution_for(package)
    return entry is not None and entry.high_mb >= HEAVY_THRESHOLD_MB


def estimate_exe_size(packages: Iterable[str]) -> tuple[int, int, tuple[str, ...]]:
    """Widełki rozmiaru CAŁEGO EXE i najcięższe paczki, od największej.

    Paczka spoza tabeli nie dokłada NIC — nie zgadujemy jej wkładu. Zgadywanie
    jest dokładnie tym, co wywołało zgłoszenie 7.

    Do sumy wkładów dochodzi `BASE_EXE_MB`, bo zdanie na ekranie mówi „gotowy
    program zajmie", a gotowy program to także interpreter i biblioteka
    standardowa.
    """
    known: list[tuple[str, Contribution]] = []
    for spec in packages:
        contribution = _contribution_for(spec)
        if contribution is not None:
            known.append((_base_name(spec), contribution))
    if not known:
        return 0, 0, ()
    low = BASE_EXE_MB + sum(c.low_mb for _name, c in known)
    high = BASE_EXE_MB + sum(c.high_mb for _name, c in known)
    heaviest = tuple(name for name, _c in sorted(known, key=lambda p: -p[1].high_mb))
    return low, high, heaviest


@functools.lru_cache(maxsize=8)
def _target_tags(python_version: str = TARGET_PYTHON, platform: str = _PLATFORM) -> tuple[Tag, ...]:
    """Tagi wheel w tej samej kolejności preferencji co docelowy CPython."""
    major, minor = (int(part) for part in python_version.split(".")[:2])
    version = (major, minor)
    exact = tuple(cpython_tags(python_version=version, platforms=[platform]))
    universal = tuple(
        compatible_tags(
            python_version=version, interpreter=f"cp{major}{minor}", platforms=[platform]
        )
    )
    return tuple(dict.fromkeys((*exact, *universal)))


def wheel_size(
    payload: dict, *, python_version: str = TARGET_PYTHON, platform: str = _PLATFORM
) -> int:
    """Rozmiar pliku, który uv naprawdę pobierze dla tej wersji.

    Kolejność prób: koło dla naszego ABI i systemu → koło uniwersalne
    (`py3-none-any`) → archiwum źródłowe. Nierozpoznany kształt odpowiedzi
    daje zero, a nie wyjątek: brak liczby jest do przeżycia, wyjątek w tle
    ekranu 2 nie.
    """
    urls = payload.get("urls") or []
    rank = {tag: index for index, tag in enumerate(_target_tags(python_version, platform))}
    compatible: list[tuple[int, dict]] = []
    for candidate in urls:
        if candidate.get("packagetype") != "bdist_wheel":
            continue
        try:
            _name, _version, _build, tags = parse_wheel_filename(candidate.get("filename", ""))
        except (InvalidWheelFilename, TypeError):
            continue
        matches = [rank[tag] for tag in tags if tag in rank]
        if matches:
            compatible.append((min(matches), candidate))
    if compatible:
        _best_rank, best = min(compatible, key=lambda item: item[0])
        return int(best.get("size") or 0)
    for candidate in urls:
        if candidate.get("packagetype") == "sdist":
            return int(candidate.get("size") or 0)
    return 0


def _fetch_release(spec: str, timeout: float) -> dict:
    name, _, version = spec.partition("==")
    with urllib.request.urlopen(_PYPI.format(name=name, version=version), timeout=timeout) as r:
        return json.load(r)


def download_size(specs: Sequence[str], timeout: float = 5.0) -> int:
    """Łączny rozmiar zgodnych archiwów dla przypiętych `nazwa==wersja`.

    Zapytania idą równolegle, bo osiem kolejnych rundtripów do PyPI zajęłoby
    tyle, że ekran 2 zdążyłby się znudzić. KAŻDA porażka jest cicha i daje
    zero — wtedy warstwa wyżej sięga po szacunek z tabeli.
    """

    return sum(distribution_sizes(specs, timeout=timeout).values())


def distribution_sizes(specs: Sequence[str], timeout: float = 5.0) -> dict[str, int]:
    """Rozmiary zgodnych z targetem archiwów, bez gubienia tożsamości paczki."""

    def one(spec: str) -> tuple[str, int]:
        try:
            return spec, wheel_size(_fetch_release(spec, timeout))
        except (OSError, ValueError, KeyError):
            return spec, 0

    if not specs:
        return {}
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(specs))) as pool:
        return dict(pool.map(one, specs))


@dataclass(frozen=True)
class DownloadPlan:
    specs: tuple[str, ...] = ()
    # Pełne drzewo `specs` opisuje środowisko; ta lista zawiera wyłącznie
    # archiwa, których uv nie znalazł w cache i rzeczywiście je pobierze.
    missing_specs: tuple[str, ...] = ()
    would_download: int = 0
    # Transfer sieciowy brakujących archiwów. Nazwa zostaje dla zgodności z
    # istniejącym BuildPlan/progresem, ale nie opisuje rozmiaru EXE.
    total_bytes: int = 0
    # Dolna granica zajętości pełnego, przechodniego środowiska: suma
    # skompresowanych archiwów zgodnych wheel. Po rozpakowaniu środowisko może
    # być większe, dlatego UI nie przedstawia tej wartości jako dokładnej.
    environment_min_bytes: int = 0
    # Składniki spoza paczek projektu. `None` znaczy, że preflight nie mógł
    # tego sprawdzić; False oznacza realny transfer w fazie budowania.
    uv_cached: bool | None = None
    python_cached: bool | None = None
    includes_build_tools: bool = False
    # Odcisk paczek i targetu, dla których policzono wynik. UI odrzuca wynik
    # po ręcznej zmianie modułów lub wersji docelowej.
    request_key: str = ""
    # B12: status wyniku — pozwala odróżnić kompletny wynik od offline/błędu.
    # "complete": policzono, "empty": brak paczek (wciąż OK), "pending": trwa,
    # "offline": brak uv/sieci, "error": błąd resolvera, "cancelled": przerwano.
    status: str = "empty"


def _default_run_dry(uv: Path, python: str | Path, packages: Sequence[str], *, cancel=None) -> str:
    # Pusty target zapobiega uwzględnieniu przypadkowych paczek środowiska,
    # z którego uruchomiono EXElent. Wersja i platforma są jawne, więc uv
    # rozwiązuje dokładnie koła dla finalnego Windows/CPython, także gdy sam
    # EXElent działa na innej wersji Pythona.
    with tempfile.TemporaryDirectory(prefix="exelent-preflight-") as empty_target:
        result = run_uv(
            uv,
            [
                "pip",
                "install",
                "--target",
                empty_target,
                "--python-version",
                str(python),
                "--python-platform",
                _UV_PLATFORM,
                "--dry-run",
                "--verbose",
                "--color",
                "never",
                *packages,
            ],
            cancel=cancel,
        )
    if result.returncode != 0:
        raise ValueError(result.stderr or result.stdout or "uv dry-run failed")
    return result.stderr or ""


def resolve_download_plan(
    uv: Path,
    python: str | Path,
    packages: Sequence[str],
    *,
    run_dry=None,
    measure=None,
    cancel=None,
) -> DownloadPlan:
    """Co naprawdę zostanie pobrane i ile to waży.

    `--dry-run` daje pełne drzewo z PRZYPIĘTYMI wersjami oraz liczbę paczek,
    których brakuje w cache. Bez tej drugiej liczby okno pytałoby o zgodę na
    pobranie stu megabajtów, które już leżą na dysku.

    Rozmiar liczymy tylko wtedy, gdy jest co pobierać. Każda porażka — brak
    uv, brak sieci, nieznany kształt wyjścia — daje pusty plan, a warstwa
    wyżej sięga po szacunek z tabeli.
    """
    # Token dostaje wyłącznie domyślny runner: wstrzyknięty `run_dry` jest
    # atrapą albo cudzą funkcją o własnym kształcie, a dokładanie jej
    # argumentu z zewnątrz zmieniałoby kontrakt punktu wstrzyknięcia.
    runner = run_dry or functools.partial(_default_run_dry, cancel=cancel)
    measurer = measure or distribution_sizes
    try:
        text = runner(uv, python, packages)
    except OSError:
        return DownloadPlan(status="offline")
    except ValueError:
        return DownloadPlan(status="error")

    # Po anulowaniu uv wraca z niczym albo z połową odpowiedzi. Liczby dla
    # użytkownika i tak już nikt nie zobaczy, a każde zapytanie do PyPI
    # przedłuża życie wątku, na który czeka zamykane okno.
    if cancel is not None and cancel.cancelled:
        return DownloadPlan(status="cancelled")

    specs: list[str] = []
    missing: list[str] = []
    would = 0
    for line in text.splitlines():
        event = parse_line(line)
        if event is None:
            continue
        if event.kind == PACKAGE:
            specs.append(event.name)
        elif event.kind == UNCACHED_PACKAGE:
            missing.append(event.name)
        elif event.kind == WOULD_DOWNLOAD:
            would = event.count

    measured = measurer(specs) if specs else {}
    if isinstance(measured, Mapping):
        environment = sum(measured.values())
        transfer = sum(measured.get(spec, 0) for spec in missing) if would else 0
    else:
        # Zachowanie punktu wstrzyknięcia dla prostych atrap z wcześniejszych
        # testów. Produkcyjny measurer zwraca mapę i nie wykonuje dwóch rund.
        scalar_measurer = cast(Callable[[Sequence[str]], int], measurer)
        environment = cast(int, measured)
        transfer = scalar_measurer(missing) if would and missing else 0

    # Starsze uv albo zmieniony format logu może podać samą liczbę bez nazw.
    # Taki wynik jest częściowy: nie przypisujemy wtedy rozmiarów paczek z
    # cache do transferu i nie pokazujemy fałszywie dokładnej wartości.
    missing_sizes_known = not isinstance(measured, Mapping) or all(
        measured.get(spec, 0) > 0 for spec in missing
    )
    status = "complete" if would == len(missing) and missing_sizes_known else "partial"
    return DownloadPlan(
        specs=tuple(specs),
        missing_specs=tuple(missing),
        would_download=would,
        total_bytes=transfer,
        environment_min_bytes=environment,
        status=status,
    )
