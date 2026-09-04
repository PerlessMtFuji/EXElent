"""Ile to zajmie: w EXE i w pobieraniu. To dwie różne liczby.

Rozmiar POBIERANIA jest dokładny — bierze się z rozwiązanych wersji i z PyPI
(zadania 16–17). Rozmiar EXE jest szacunkiem z widełkami, bo PyInstaller
wyrzuca z paczki to, czego kod nie dotyka: ten sam `pandas` waży inaczej w
skrypcie czytającym jeden CSV, a inaczej w programie używającym połowy API.

Zgłoszenie 7 mówi dokładnie o tym, że liczby wzięte z sufitu wprowadzają w
błąd. Dlatego każdy wpis niesie `measured` — datę pomiaru albo słowo
„tymczasowe". Zadanie 15 zamienia wszystkie „tymczasowe" na daty.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from exelent.constants import TARGET_PYTHON
from exelent.runtime.env import run_uv
from exelent.runtime.uvlog import PACKAGE, WOULD_DOWNLOAD, parse_line

# Znacznik ABI koła, którego naprawdę użyje build: CPython w wersji docelowej,
# 64-bitowy Windows. Koło dla innej wersji albo innego systemu opisuje plik,
# którego nigdy nie pobierzemy.
_TAG = f"cp{TARGET_PYTHON.replace('.', '')}"
_PLATFORM = "win_amd64"
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


def is_heavy(package: str) -> bool:
    entry = EXE_CONTRIBUTION.get(package)
    return entry is not None and entry.high_mb >= HEAVY_THRESHOLD_MB


def estimate_exe_size(packages: Iterable[str]) -> tuple[int, int, tuple[str, ...]]:
    """Widełki rozmiaru CAŁEGO EXE i najcięższe paczki, od największej.

    Paczka spoza tabeli nie dokłada NIC — nie zgadujemy jej wkładu. Zgadywanie
    jest dokładnie tym, co wywołało zgłoszenie 7.

    Do sumy wkładów dochodzi `BASE_EXE_MB`, bo zdanie na ekranie mówi „gotowy
    program zajmie", a gotowy program to także interpreter i biblioteka
    standardowa.
    """
    known = [(name, EXE_CONTRIBUTION[name]) for name in packages if name in EXE_CONTRIBUTION]
    if not known:
        return 0, 0, ()
    low = BASE_EXE_MB + sum(c.low_mb for _name, c in known)
    high = BASE_EXE_MB + sum(c.high_mb for _name, c in known)
    heaviest = tuple(name for name, _c in sorted(known, key=lambda p: -p[1].high_mb))
    return low, high, heaviest


def wheel_size(payload: dict) -> int:
    """Rozmiar pliku, który uv naprawdę pobierze dla tej wersji.

    Kolejność prób: koło dla naszego ABI i systemu → koło uniwersalne
    (`py3-none-any`) → archiwum źródłowe. Nierozpoznany kształt odpowiedzi
    daje zero, a nie wyjątek: brak liczby jest do przeżycia, wyjątek w tle
    ekranu 2 nie.
    """
    urls = payload.get("urls") or []
    wheels = [u for u in urls if u.get("packagetype") == "bdist_wheel"]
    for candidate in wheels:
        name = candidate.get("filename", "")
        if _TAG in name and _PLATFORM in name:
            return int(candidate.get("size") or 0)
    for candidate in wheels:
        if "none-any" in candidate.get("filename", ""):
            return int(candidate.get("size") or 0)
    for candidate in urls:
        if candidate.get("packagetype") == "sdist":
            return int(candidate.get("size") or 0)
    return 0


def _fetch_release(spec: str, timeout: float) -> dict:
    name, _, version = spec.partition("==")
    with urllib.request.urlopen(_PYPI.format(name=name, version=version), timeout=timeout) as r:
        return json.load(r)


def download_size(specs: Sequence[str], timeout: float = 5.0) -> int:
    """Łączny rozmiar pobierania dla przypiętych `nazwa==wersja`.

    Zapytania idą równolegle, bo osiem kolejnych rundtripów do PyPI zajęłoby
    tyle, że ekran 2 zdążyłby się znudzić. KAŻDA porażka jest cicha i daje
    zero — wtedy warstwa wyżej sięga po szacunek z tabeli.
    """

    def one(spec: str) -> int:
        try:
            return wheel_size(_fetch_release(spec, timeout))
        except (OSError, ValueError, KeyError):
            return 0

    if not specs:
        return 0
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(specs))) as pool:
        return sum(pool.map(one, specs))


@dataclass(frozen=True)
class DownloadPlan:
    specs: tuple[str, ...] = ()
    would_download: int = 0
    total_bytes: int = 0


def _default_run_dry(uv: Path, python: Path, packages: Sequence[str]) -> str:
    result = run_uv(
        uv,
        ["pip", "install", "--python", str(python), "--dry-run", "--color", "never", *packages],
    )
    return result.stderr or ""


def resolve_download_plan(
    uv: Path,
    python: Path,
    packages: Sequence[str],
    *,
    run_dry=None,
    measure=None,
) -> DownloadPlan:
    """Co naprawdę zostanie pobrane i ile to waży.

    `--dry-run` daje pełne drzewo z PRZYPIĘTYMI wersjami oraz liczbę paczek,
    których brakuje w cache. Bez tej drugiej liczby okno pytałoby o zgodę na
    pobranie stu megabajtów, które już leżą na dysku.

    Rozmiar liczymy tylko wtedy, gdy jest co pobierać. Każda porażka — brak
    uv, brak sieci, nieznany kształt wyjścia — daje pusty plan, a warstwa
    wyżej sięga po szacunek z tabeli.
    """
    runner = run_dry or _default_run_dry
    measurer = measure or download_size
    try:
        text = runner(uv, python, packages)
    except (OSError, ValueError):
        return DownloadPlan()

    specs: list[str] = []
    would = 0
    for line in text.splitlines():
        event = parse_line(line)
        if event is None:
            continue
        if event.kind == PACKAGE:
            specs.append(event.name)
        elif event.kind == WOULD_DOWNLOAD:
            would = event.count

    total = measurer(specs) if would else 0
    return DownloadPlan(specs=tuple(specs), would_download=would, total_bytes=total)
