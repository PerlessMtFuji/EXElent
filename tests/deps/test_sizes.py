"""Rozmiar EXE to nie rozmiar pobierania.

PyInstaller wyrzuca z paczki to, czego kod nie dotyka — i wlasnie dlatego
skrypt z matplotlib, pandas i scipy dal 26 MB przy ostrzezeniu o "kilkuset
megabajtach". Widelki mowia prawde, ktorej jedna liczba nie umie powiedziec.
"""

import json
import re
from pathlib import Path

from exelent.deps.sizes import (
    EXE_CONTRIBUTION,
    LARGE_WARNING_MB,
    download_size,
    estimate_exe_size,
    wheel_size,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_estimate_returns_a_range_not_a_single_number():
    low, high, heaviest = estimate_exe_size(["matplotlib", "pandas", "scipy"])
    assert low < high
    assert heaviest[0] in {"scipy", "pandas", "matplotlib"}


def test_estimate_ignores_packages_we_have_not_measured():
    """Paczka spoza tabeli nie ma wkladu ZGADYWANEGO. Zgadywanie jest tym,
    co wywolalo zgloszenie 7."""
    low_alone, high_alone, _ = estimate_exe_size(["pandas"])
    low_with, high_with, _ = estimate_exe_size(["pandas", "jakas-mala-paczka"])
    assert (low_alone, high_alone) == (low_with, high_with)


def test_no_packages_means_no_estimate():
    assert estimate_exe_size([]) == (0, 0, ())


def test_heaviest_packages_come_first():
    _low, _high, heaviest = estimate_exe_size(["matplotlib", "scipy"])
    assert heaviest == ("scipy", "matplotlib")


def test_every_entry_declares_where_its_number_came_from():
    """Wpis bez zrodla to liczba wzieta z sufitu — dokladnie to, na co
    skarzy sie zgloszenie 7."""
    for package, contribution in EXE_CONTRIBUTION.items():
        assert contribution.measured, f"{package} nie mowi, skad ma swoje liczby"
        assert contribution.measured == "tymczasowe" or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", contribution.measured
        ), f"{package}: `measured` ma byc data albo slowem 'tymczasowe'"


def test_large_threshold_matches_the_spec():
    assert LARGE_WARNING_MB == 300


# --- rozmiar POBIERANIA: dokladny, z PyPI ---


def test_wheel_size_prefers_the_matching_windows_wheel():
    """Kolo dla innej wersji Pythona albo innego systemu to nie nasze kolo."""
    payload = json.loads((FIXTURES / "pypi_scipy.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 36700160


def test_wheel_size_falls_back_to_a_pure_python_wheel():
    payload = json.loads((FIXTURES / "pypi_pure.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 11053


def test_wheel_size_falls_back_to_sdist_as_a_last_resort():
    payload = json.loads((FIXTURES / "pypi_sdist_only.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 90000


def test_wheel_size_of_empty_payload_is_zero():
    assert wheel_size({"urls": []}) == 0


def test_download_size_degrades_quietly_when_pypi_is_unreachable(monkeypatch):
    """Rozmiar pobierania jest WYGODA, a nie powodem, dla ktorego build ma
    nie ruszyc — ta sama zasada, ktora rzadzi `recent.py`."""
    import exelent.deps.sizes as sizes_module

    def boom(spec, timeout):
        raise OSError("brak sieci")

    monkeypatch.setattr(sizes_module, "_fetch_release", boom)
    assert download_size(["scipy==1.18.1", "numpy==2.5.2"]) == 0
