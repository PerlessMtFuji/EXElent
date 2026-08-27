"""Motyw: jedna paleta tokenow, z niej arkusz QSS.

Wersja z planu miala tu test `test_stylesheet_contains_no_unresolved_tokens`
konczacy sie `or True`, czyli przechodzacy zawsze — ta sama klasa, ktora
recenzje rundy 2 i 3 wylapaly jako M9/M16. Zamiast niego sa dwa testy, ktore
naprawde moga zgasnac.
"""

import re

from exelent.ui.theme import PALETTE_DARK, PALETTE_LIGHT, build_stylesheet


def test_palettes_define_the_same_tokens():
    assert set(PALETTE_DARK) == set(PALETTE_LIGHT)


def test_required_tokens_exist():
    required = {
        "bg",
        "surface",
        "text",
        "text_muted",
        "accent",
        "accent_hover",
        "border",
        "danger",
        "success",
    }
    assert required <= set(PALETTE_DARK)


def test_no_token_placeholder_survives_formatting():
    """Podwojony nawias (`{{bg}}`) zostawia w arkuszu goly `{bg}`, ktorego Qt
    nie rozumie i po cichu ignoruje cala regule."""
    for dark in (True, False):
        leftovers = re.findall(r"\{[a-z_]+\}", build_stylesheet(dark))
        assert leftovers == [], f"nierozwiniete tokeny: {leftovers}"


def test_the_sheet_uses_the_palette_it_was_asked_for():
    dark = build_stylesheet(True)
    assert PALETTE_DARK["accent"] in dark
    assert PALETTE_LIGHT["accent"] not in dark


def test_dark_and_light_differ():
    assert build_stylesheet(True) != build_stylesheet(False)


def test_every_palette_value_is_a_colour():
    for palette in (PALETTE_DARK, PALETTE_LIGHT):
        for token, value in palette.items():
            assert value.startswith("#") and len(value) in (7, 9), f"{token} = {value}"
