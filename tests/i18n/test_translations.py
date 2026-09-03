"""Kody Issue i fazy postepu -> zdania po polsku i angielsku.

Straznik kompletnosci LICZY, czego wymaga rdzen (`inventory`), zamiast trzymac
liste przepisana do testu. Powod jest z recenzji rundy 4 (I12): oba straznik i
przewidziane w planie byly slepe na 7 realnie produkowanych kodow, w tym na
`cloud_file_unavailable`, ktory powstal runde wczesniej. Lista przepisana
recznie starzeje sie po cichu — uzytkownik dostaje wtedy goly kod zamiast
zdania, a testy swieca sie na zielono.
"""

from string import Formatter

import pytest
from inventory import (
    DECLARED_DATA,
    DECLARED_DYNAMIC_ISSUES,
    DECLARED_DYNAMIC_PHASES,
    codes_with_non_literal_data,
    dynamic_issue_sites,
    dynamic_phase_sites,
    issue_data_keys,
    phase_keys,
)

from exelent.diagnostics.patterns import PATTERNS
from exelent.i18n import CATALOGS, current_language, describe, set_language, system_language, t
from exelent.models import Issue, Severity


@pytest.fixture(autouse=True)
def _reset_language():
    set_language("pl")
    yield
    set_language("pl")


def _placeholders(template: str) -> set[str]:
    return {name for _text, name, _spec, _conv in Formatter().parse(template) if name}


# --- kompletnosc liczona z kodu ---


def test_both_catalogs_have_identical_keys():
    assert set(CATALOGS["pl"]) == set(CATALOGS["en"])


def test_every_issue_code_the_core_can_produce_is_translated():
    missing = sorted(set(issue_data_keys()) - set(CATALOGS["pl"]))
    assert missing == [], f"kod bez tlumaczenia: {missing}"


def test_every_diagnostic_pattern_is_translated():
    codes = {code for _pattern, code, _severity in PATTERNS}
    assert codes <= set(CATALOGS["pl"])


def test_every_progress_phase_is_translated():
    missing = sorted(phase_keys() - set(CATALOGS["pl"]))
    assert missing == [], f"faza bez tlumaczenia: {missing}"


def test_the_inventory_still_sees_progress_phases():
    """Sonda nad skanem faz: pusty zbior przechodzilby kazdy test
    kompletnosci, wiec brak fazy przestalby cokolwiek znaczyc."""
    phases = phase_keys()
    assert "install_packages" in phases, "faza z env.py wypadla z inwentarza"
    assert len(phases) > 8, f"inwentarz faz nagle schudl do {len(phases)}"


def test_templates_only_ask_for_data_the_core_supplies():
    """Szablon z `{dir}`, gdy rdzen nie podaje `dir`, nie wywala sie — pokazuje
    uzytkownikowi nawias klamrowy w zdaniu. Cichy blad, wiec pilnowany."""
    known = issue_data_keys()
    wrong = {}
    for lang, catalog in CATALOGS.items():
        for key, template in catalog.items():
            if key in known and (extra := _placeholders(template) - known[key]):
                wrong[f"{lang}:{key}"] = sorted(extra)
    assert wrong == {}, f"szablon prosi o dane, ktorych rdzen nie podaje: {wrong}"


# --- straznik nad samym straznikiem ---


def test_the_inventory_sees_the_codes_that_recent_rounds_added():
    """Sonda na wypadek, gdyby skan przestal cokolwiek znajdowac: pusty
    inwentarz przechodzilby kazdy test kompletnosci."""
    codes = set(issue_data_keys())
    assert "cloud_file_unavailable" in codes, "kod z rundy 3 wypadl z inwentarza"
    assert len(codes) > 25, f"inwentarz nagle schudl do {len(codes)} kodow"


def test_dynamic_issue_sites_are_declared():
    """Kod skladany w locie jest dla skanu niewidzialny. Kazde takie miejsce ma
    byc zadeklarowane, zeby nowe nie wypadlo z inwentarza po cichu."""
    assert dynamic_issue_sites() == set(DECLARED_DYNAMIC_ISSUES)


def test_dynamic_progress_sites_are_declared():
    assert dynamic_phase_sites() == set(DECLARED_DYNAMIC_PHASES)


def test_codes_with_non_literal_data_are_declared():
    assert codes_with_non_literal_data() == set(DECLARED_DATA)


# --- zachowanie warstwy ---


def test_translation_switches_with_language():
    polish = t("no_network")
    set_language("en")
    assert t("no_network") != polish


def test_an_unknown_language_falls_back_to_english():
    set_language("de")
    assert current_language() == "en"


def test_parameters_are_interpolated():
    assert "ffmpeg" in t("external_tool", tool="ffmpeg")


def test_missing_key_returns_key_not_crash():
    assert t("klucz-ktorego-nie-ma") == "klucz-ktorego-nie-ma"


def test_describe_renders_issue_with_its_data():
    issue = Issue("external_tool", Severity.WARNING, {"tool": "tesseract"})
    assert "tesseract" in describe(issue)


def test_describe_tolerates_missing_parameters():
    assert describe(Issue("external_tool", Severity.WARNING)) != ""


def test_system_language_falls_back_to_english(monkeypatch):
    monkeypatch.setattr("locale.getlocale", lambda: (None, None))
    assert system_language() == "en"


def test_system_language_detects_polish(monkeypatch):
    monkeypatch.setattr("locale.getlocale", lambda: ("pl_PL", "cp1250"))
    assert system_language() == "pl"


def test_system_language_detects_the_form_windows_actually_returns(monkeypatch):
    """Zmierzone na polskim Windows: `locale.getlocale()` oddaje ANGIELSKĄ NAZWĘ
    języka, `('Polish_Poland', '1250')`, a nie kod `pl_PL`. Test wyżej podaje
    formę POSIX-ową, której ten system nigdy nie produkuje — więc przechodził
    dla kodu, który polskiemu użytkownikowi pokazywał angielskie okno."""
    monkeypatch.setattr("locale.getlocale", lambda: ("Polish_Poland", "1250"))
    assert system_language() == "pl"


def test_cloud_advice_never_mentions_the_antivirus():
    """Ruling rundy 3: `cloud_file_unavailable` powstal wlasnie po to, zeby nie
    wyslac laika na godzine wylaczania antywirusa. Zdanie musi mowic o chmurze."""
    for lang in CATALOGS:
        set_language(lang)
        text = t("cloud_file_unavailable", file="dane.py").lower()
        assert "antywirus" not in text and "antivirus" not in text
        assert "chmur" in text or "cloud" in text
