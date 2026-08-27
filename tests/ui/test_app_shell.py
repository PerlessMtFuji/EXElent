"""Powloka okna: stos trzech ekranow, tytul, motyw i przelacznik jezyka.

Ekrany 1-2 sa juz wlasciwe (Task 18-19), ekran 3 to nadal pusty `QWidget` —
zadanie 20 podmienia go, nie ruszajac tej klasy.
"""

import pytest

from exelent.i18n import CATALOGS, set_language
from exelent.ui.app import SCREEN_REVIEW, MainWindow
from exelent.ui.screen_drop import DropScreen
from exelent.ui.screen_review import ReviewScreen


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


def test_the_second_screen_is_the_review_screen(window):
    assert isinstance(window.stack.widget(SCREEN_REVIEW), ReviewScreen)


def test_choosing_a_folder_shows_its_analysis(window, tmp_path):
    """Sama zmiana ekranu to za malo: bez wywolania analizy uzytkownik dostaje
    ekran 2 z poprzednim projektem albo z pustka."""
    (tmp_path / "main.py").write_text("print(1)", encoding="utf-8")
    window.screen_drop.folder_chosen.emit(tmp_path)
    assert "main.py" in window.screen_review.row_entry.value_text()


def test_an_unreadable_folder_does_not_crash_the_window(window, tmp_path):
    """Katalog moze zniknac miedzy upuszczeniem a analiza. Rdzen wraca wtedy
    z blokada, wiec okno ma pokazac zdanie, a nie traceback."""
    window.screen_drop.folder_chosen.emit(tmp_path / "nie-ma-takiego")
    assert window.stack.currentIndex() == SCREEN_REVIEW
    assert window.screen_review.build_button.isEnabled() is False
    assert window.screen_review.warnings_label.text() != ""


def test_the_window_speaks_the_system_language_on_every_screen(qtbot, monkeypatch):
    """Ekrany biora napisy z `t()` w konstruktorze, wiec jezyk musi byc
    ustawiony PRZED nimi. Zmierzone: przy `set_language` po konstrukcji
    angielski uzytkownik dostawal polski naglowek ekranu 1."""
    monkeypatch.setattr("exelent.ui.app.system_language", lambda: "en")
    window = MainWindow()
    qtbot.addWidget(window)
    english = set(CATALOGS["en"].values())
    assert window.screen_drop.headline.text() in english
    assert window.screen_review.headline.text() in english
