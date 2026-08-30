"""Wiersz faktu: znacznik pewnosci, rekomendacja, link powrotu.

Rekomendacja odpowiada na pytanie, ktore uzytkownik zadaje sobie pol godziny
pozniej: "co program wybral sam, zanim to zmienilem". Wiersz porownuje NAPISY,
bo to jedyne, co widzi niezaleznie od tego, czy edytorem jest lista, pole
tekstowe czy przycisk.
"""

import pytest
from PySide6.QtWidgets import QComboBox

from exelent.ui.rows import FactRow


@pytest.fixture
def combo_row(qtbot):
    combo = QComboBox()
    combo.addItem("Program w oknie (zalecane)", "windowed")
    combo.addItem("Program konsolowy", "console")
    row = FactRow("Rodzaj programu", combo)
    qtbot.addWidget(row)
    return row, combo


def test_link_is_hidden_when_nothing_is_recommended(combo_row):
    row, _combo = combo_row
    assert row.restore_visible() is False


def test_link_is_hidden_while_the_value_matches_the_recommendation(combo_row):
    row, _combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    assert row.restore_visible() is False


def test_link_appears_when_the_user_picks_something_else(combo_row):
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    assert row.restore_visible() is True


def test_link_disappears_again_when_the_value_comes_back(combo_row):
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    combo.setCurrentIndex(0)
    assert row.restore_visible() is False


def test_clicking_the_link_asks_the_screen_instead_of_setting_the_value(qtbot, combo_row):
    """Wiersz nie umie ustawic wartosci w dowolnym edytorze — ma o to poprosic.

    Gdyby probowal sam, musialby znac QComboBox, QLineEdit i QPushButton, czyli
    dokladnie te wiedze, ktorej `value_text()` celowo unika.
    """
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    with qtbot.waitSignal(row.restore_requested, timeout=1000):
        row.restore_button().click()
    assert combo.currentIndex() == 1  # wiersz NIE ustawil nic sam
