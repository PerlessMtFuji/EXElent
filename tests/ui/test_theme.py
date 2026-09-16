"""Theme: one token palette used to generate the QSS stylesheet.

The planned version had a `test_stylesheet_contains_no_unresolved_tokens` test
ending in `or True`, so it always passed—the same class of issue found as
M9/M16 in review rounds 2 and 3. Two tests that can actually fail replace it.
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
    """A doubled brace (`{{bg}}`) leaves a raw `{bg}` in the stylesheet.

    Qt does not understand it and silently ignores the entire rule.
    """
    for dark in (True, False):
        leftovers = re.findall(r"\{[a-z_]+\}", build_stylesheet(dark))
        assert leftovers == [], f"unexpanded tokens: {leftovers}"


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
