"""Rozmiar EXE to nie rozmiar pobierania.

PyInstaller wyrzuca z paczki to, czego kod nie dotyka — i wlasnie dlatego
skrypt z matplotlib, pandas i scipy dal 26 MB przy ostrzezeniu o "kilkuset
megabajtach". Widelki mowia prawde, ktorej jedna liczba nie umie powiedziec.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

from exelent.deps.sizes import (
    EXE_CONTRIBUTION,
    LARGE_WARNING_MB,
    download_size,
    estimate_exe_size,
    resolve_download_plan,
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
    """Kolejnosc bierze sie z POMIARU, nie z intuicji: matplotlib pociaga za
    soba wlasne backendy i wazy ponad trzy razy tyle co pandas (zmierzone
    2026-09-04: 74,4 MB wobec 20,8 MB)."""
    _low, _high, heaviest = estimate_exe_size(["pandas", "matplotlib"])
    assert heaviest == ("matplotlib", "pandas")


# Wpisy, ktorych NIE zmierzono. Ich pomiar to kilka gigabajtow pobierania i
# swiadomie go odlozono. Lista jest JAWNA po to, zeby liczba z sufitu nie
# mogla wejsc po cichu: nowy wpis bez daty i bez miejsca tutaj wywala test.
NIEZMIERZONE = frozenset({"torch", "tensorflow", "transformers"})


def test_every_entry_is_either_measured_or_openly_listed_as_not():
    """Wpis bez zrodla to liczba wzieta z sufitu — dokladnie to, na co
    skarzy sie zgloszenie 7."""
    for package, contribution in EXE_CONTRIBUTION.items():
        assert contribution.measured, f"{package} nie mowi, skad ma swoje liczby"
        if package in NIEZMIERZONE:
            assert contribution.measured == "tymczasowe", (
                f"{package} ma juz date pomiaru — zdejmij go z NIEZMIERZONE"
            )
            continue
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", contribution.measured), (
            f"{package}: liczba bez daty pomiaru. Zmierz ja albo dopisz do NIEZMIERZONE."
        )


def test_the_estimate_covers_the_whole_exe_not_just_the_packages():
    """Zdanie na ekranie mowi "gotowy program zajmie", a gotowy program to
    takze interpreter. ZMIERZONE 2026-09-04: pusty skrypt daje 10,5 MB."""
    low, _high, _heaviest = estimate_exe_size(["numpy"])
    assert low > EXE_CONTRIBUTION["numpy"].low_mb


def test_the_script_from_the_report_falls_inside_its_own_estimate():
    """KRYTERIUM SUKCESU specyfikacji: rozmiar gotowego programu ma sie miescic
    w widelkach pokazanych przed buildem.

    ZMIERZONE 2026-09-04 na prawdziwym buildzie skryptu ze zgloszenia 7
    (pandas + scipy.stats + pyplot.savefig): 172,4 MB.
    """
    low, high, _heaviest = estimate_exe_size(["matplotlib", "pandas", "scipy"])
    assert low <= 172.4 <= high, f"widelki {low}-{high} MB nie obejmuja zmierzonych 172,4 MB"


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


# --- plan pobierania: co uv naprawde sciagnie, z uwzglednieniem cache ---


def test_dry_run_yields_pinned_specs_and_the_missing_count():
    transcript = (FIXTURES.parent.parent / "runtime" / "fixtures" / "uv_dry_run.txt").read_text(
        encoding="utf-8"
    )
    plan = resolve_download_plan(
        uv=Path("uv.exe"),
        python=Path("python.exe"),
        packages=["matplotlib", "pandas", "scipy"],
        run_dry=lambda *_a, **_k: transcript,
        measure=lambda specs, **_k: 0,
    )
    assert plan.would_download == 8
    assert "scipy==1.18.1" in plan.specs
    assert len(plan.specs) == 14


def test_nothing_to_download_when_everything_is_cached():
    """Pytanie o zgode na pobranie zera megabajtow uczy klikac OK bez
    czytania — wiec ta liczba musi byc prawdziwa."""
    transcript = "Resolved 3 packages in 12ms\nWould download 0 packages\n + six==1.17.0\n"
    plan = resolve_download_plan(
        uv=Path("uv.exe"),
        python=Path("python.exe"),
        packages=["six"],
        run_dry=lambda *_a, **_k: transcript,
        measure=lambda specs, **_k: 999,
    )
    assert plan.would_download == 0
    assert plan.total_bytes == 0


def test_resolution_failure_degrades_to_an_empty_plan():
    def boom(*_args, **_kwargs):
        raise OSError("uv nie wystartowal")

    plan = resolve_download_plan(
        uv=Path("uv.exe"), python=Path("python.exe"), packages=["scipy"], run_dry=boom
    )
    assert plan.specs == ()
    assert plan.total_bytes == 0


def test_dry_run_receives_the_cancel_token(monkeypatch):
    """Token musi dojsc az do `uv` — inaczej anulowanie preflightu konczy sie
    na granicy warstwy, a proces uv miele dalej."""
    from exelent.build.backend import CancelToken
    from exelent.deps import sizes as sizes_module

    seen = {}

    def fake_run_uv(uv, args, *, cwd=None, cancel=None):
        seen["cancel"] = cancel
        return SimpleNamespace(stderr="")

    monkeypatch.setattr(sizes_module, "run_uv", fake_run_uv)
    token = CancelToken()

    resolve_download_plan(Path("uv.exe"), Path("python.exe"), ["six"], cancel=token)

    assert seen["cancel"] is token
