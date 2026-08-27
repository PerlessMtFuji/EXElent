"""Powloka okna: stos trzech ekranow, tytul, motyw i przelacznik jezyka.

Ekran 1 jest juz wlasciwy (Task 18), ekrany 2-3 to nadal puste `QWidget` —
zadania 19-20 podmieniaja je, nie ruszajac tej klasy.
"""

import pytest

from exelent.i18n import set_language
from exelent.ui.app import SCREEN_REVIEW, MainWindow
from exelent.ui.screen_drop import DropScreen


@pytest.fixture(autouse=True)
def _restore_language():
    """`MainWindow` ustawia jezyk systemu globalnie — bez tego kolejnosc testow
    decydowalaby o tym, w jakim jezyku pracuja pozostale."""
    yield
    set_language("pl")


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_window_has_three_screens(window):
    assert window.stack.count() == 3


def test_starts_on_first_screen(window):
    assert window.stack.currentIndex() == 0


def test_go_to_changes_screen(window):
    window.go_to(1)
    assert window.stack.currentIndex() == 1


def test_out_of_range_never_leaves_the_window_without_a_screen(window):
    """Własność, nie gałąź: stos bez bieżącego widgetu to szare okno bez treści.
    Gwarancję daje dziś `QStackedWidget`, a ten test jest linką ostrzegawczą na
    wypadek, gdyby `go_to` zaczęło kiedyś trasować po swojemu — na przykład
    „pomocniczo” przycinać indeks do zakresu."""
    for index in (99, -1, -5):
        window.go_to(index)
        assert window.stack.currentIndex() == 0
        assert window.stack.currentWidget() is not None


def test_title_is_app_name(window):
    assert "EXElent" in window.windowTitle()


def test_the_window_wears_the_theme(window):
    """Motyw ma byc PODPIETY, nie tylko zdefiniowany — bez tego okno wyglada
    jak domyslne Qt, a paleta jest martwym kodem."""
    from exelent.ui.theme import PALETTE_DARK, PALETTE_LIGHT

    sheet = window.styleSheet()
    assert sheet, "okno bez arkusza stylow"
    assert PALETTE_DARK["bg"] in sheet or PALETTE_LIGHT["bg"] in sheet


def test_language_switch_emits_signal(window, qtbot):
    with qtbot.waitSignal(window.language_changed, timeout=1000) as blocker:
        window.set_language("en")
    assert blocker.args == ["en"]


def test_the_first_screen_is_the_drop_screen(window):
    assert isinstance(window.stack.widget(0), DropScreen)


def test_choosing_a_folder_moves_to_the_second_screen(window, tmp_path):
    """Sygnal ekranu ma byc PODPIETY: bez tego upuszczenie folderu wyglada
    jak brak reakcji programu."""
    window.screen_drop.folder_chosen.emit(tmp_path)
    assert window.stack.currentIndex() == SCREEN_REVIEW
