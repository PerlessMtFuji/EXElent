"""Rozmiar EXE to nie rozmiar pobierania.

PyInstaller wyrzuca z paczki to, czego kod nie dotyka — i wlasnie dlatego
skrypt z matplotlib, pandas i scipy dal 26 MB przy ostrzezeniu o "kilkuset
megabajtach". Widelki mowia prawde, ktorej jedna liczba nie umie powiedziec.
"""

import re

from exelent.deps.sizes import EXE_CONTRIBUTION, LARGE_WARNING_MB, estimate_exe_size


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
