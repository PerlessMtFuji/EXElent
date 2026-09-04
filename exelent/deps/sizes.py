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

from collections.abc import Iterable
from dataclasses import dataclass

# Powyżej tylu megabajtów górnych widełek rozmiar przestaje być informacją,
# a staje się ostrzeżeniem (razem z uwagą o dłuższym budowaniu).
LARGE_WARNING_MB = 300

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


# WSZYSTKIE wpisy sa TYMCZASOWE do czasu wykonania zadania 15.
EXE_CONTRIBUTION: dict[str, Contribution] = {
    "torch": Contribution(300, 900, "tymczasowe"),
    "tensorflow": Contribution(250, 700, "tymczasowe"),
    "transformers": Contribution(60, 200, "tymczasowe"),
    "scipy": Contribution(30, 70, "tymczasowe"),
    "opencv-python": Contribution(35, 70, "tymczasowe"),
    "matplotlib": Contribution(15, 40, "tymczasowe"),
    "pandas": Contribution(20, 45, "tymczasowe"),
    "numpy": Contribution(15, 30, "tymczasowe"),
    "PySide6": Contribution(40, 120, "tymczasowe"),
    "PyQt5": Contribution(40, 110, "tymczasowe"),
    "PyQt6": Contribution(40, 110, "tymczasowe"),
    "librosa": Contribution(20, 50, "tymczasowe"),
    "moviepy": Contribution(15, 40, "tymczasowe"),
}


def is_heavy(package: str) -> bool:
    entry = EXE_CONTRIBUTION.get(package)
    return entry is not None and entry.high_mb >= HEAVY_THRESHOLD_MB


def estimate_exe_size(packages: Iterable[str]) -> tuple[int, int, tuple[str, ...]]:
    """Widełki rozmiaru EXE i najcięższe paczki, od największej.

    Paczka spoza tabeli nie dokłada NIC — nie zgadujemy jej wkładu. Zgadywanie
    jest dokładnie tym, co wywołało zgłoszenie 7.
    """
    known = [(name, EXE_CONTRIBUTION[name]) for name in packages if name in EXE_CONTRIBUTION]
    if not known:
        return 0, 0, ()
    low = sum(c.low_mb for _name, c in known)
    high = sum(c.high_mb for _name, c in known)
    heaviest = tuple(name for name, _c in sorted(known, key=lambda p: -p[1].high_mb))
    return low, high, heaviest
