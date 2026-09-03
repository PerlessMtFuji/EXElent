"""Powloka okna: stos trzech ekranow, tytul, motyw, jezyk i droga przez program.

Tu testujemy to, czego nie widac z zadnego pojedynczego ekranu: ze folder
wskazany na ekranie 1 dociera jako analiza na ekran 2, ze plan z ekranu 2
naprawde rusza build, i ze zamkniecie okna w trakcie budowania nie zostawia
w systemie osieroconego procesu.
"""

import threading

import pytest

from exelent.i18n import CATALOGS, set_language
from exelent.models import AppKind, BuildPlan, BuildResult, OutputMode
from exelent.runtime import Progress
from exelent.ui import worker as worker_module
from exelent.ui.app import SCREEN_BUILD, SCREEN_DROP, SCREEN_REVIEW, MainWindow
from exelent.ui.screen_build import BuildScreen
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


# --- droga przez program: folder -> przeglad -> build ---


def _plan(tmp_path):
    return BuildPlan(
        root=tmp_path,
        entry=tmp_path / "main.py",
        app_kind=AppKind.CONSOLE,
        output_mode=OutputMode.ONEFILE,
        exe_name="Program",
        dest_dir=tmp_path / "out",
    )


@pytest.fixture
def fake_build(monkeypatch):
    """Udawany `run_build`, ktory stoi az do zwolnienia."""
    zwolnij = threading.Event()
    wystartowal = threading.Event()
    stan = {"anulowany": False}

    def fake(root, progress, cancel, **kwargs):
        wystartowal.set()
        progress(Progress(phase="analyze", fraction=0.35))
        for _ in range(1000):
            if zwolnij.is_set() or cancel.cancelled:
                break
            threading.Event().wait(0.005)
        stan["anulowany"] = cancel.cancelled
        return BuildResult(ok=False)

    monkeypatch.setattr(worker_module, "run_build", fake)
    stan["zwolnij"] = zwolnij
    stan["wystartowal"] = wystartowal
    return stan


def test_the_third_screen_is_the_build_screen(window):
    assert isinstance(window.stack.widget(SCREEN_BUILD), BuildScreen)


def test_the_build_screen_is_not_the_owner_of_the_thread(window):
    """Ekran pokazuje postep, watkiem zarzadza okno — inaczej kazdy powrot na
    ekran 1 musialby wiedziec, jak zatrzymac budowanie."""
    assert window.worker is not None
    assert window.worker.is_running() is False


def test_requesting_a_build_moves_to_the_third_screen_and_starts_it(
    window, qtbot, fake_build, tmp_path
):
    window.screen_review.build_requested.emit(_plan(tmp_path))
    assert window.stack.currentIndex() == SCREEN_BUILD
    assert fake_build["wystartowal"].wait(timeout=5)
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        fake_build["zwolnij"].set()


def test_progress_from_the_worker_reaches_the_screen(window, qtbot, fake_build, tmp_path):
    """Sygnaly workera musza byc PODPIETE do ekranu: bez tego pasek stoi na
    zerze przez cale budowanie i program wyglada na zawieszony."""
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        window.screen_review.build_requested.emit(_plan(tmp_path))
        assert fake_build["wystartowal"].wait(timeout=5)
        fake_build["zwolnij"].set()
    assert window.screen_build.bar.value() > 0
    assert window.screen_build.summary_label.text() != ""


def test_the_stop_button_stops_the_running_build(window, qtbot, fake_build, tmp_path):
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        window.screen_review.build_requested.emit(_plan(tmp_path))
        assert fake_build["wystartowal"].wait(timeout=5)
        window.screen_build.cancel_button.click()
    assert fake_build["anulowany"] is True


def test_the_new_build_screen_does_not_show_the_previous_one(window, qtbot, fake_build, tmp_path):
    """Okno wola `start` PRZED pokazaniem ekranu — inaczej uzytkownik widzi
    przez chwile wynik poprzedniego budowania."""
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        window.screen_review.build_requested.emit(_plan(tmp_path))
        fake_build["zwolnij"].set()
    poprzednie = window.screen_build.summary_label.text()
    assert poprzednie != ""

    fake_build["zwolnij"].clear()
    window.screen_review.build_requested.emit(_plan(tmp_path))
    assert window.screen_build.summary_label.text() == ""
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        fake_build["zwolnij"].set()


def test_restart_returns_to_the_first_screen(window, qtbot, tmp_path):
    window.go_to(SCREEN_BUILD)
    window.screen_build.restart_requested.emit()
    assert window.stack.currentIndex() == SCREEN_DROP


def test_restart_refreshes_the_recent_list(window, monkeypatch, tmp_path):
    """Projekt zbudowany przed chwila zostal zapamietany na ekranie 1, ale ten
    ekran czytal liste ostatni raz przy starcie programu — bez odswiezenia
    powrot pokazuje liste bez wlasnie uzytego projektu."""
    odswiezenia = []
    monkeypatch.setattr(window.screen_drop, "refresh_recent", lambda: odswiezenia.append(1))
    window.screen_build.restart_requested.emit()
    assert odswiezenia == [1]


def test_closing_the_window_stops_a_running_build(window, fake_build, tmp_path):
    """Zamkniecie okna w trakcie budowania: Qt niszczy dzialajacy QThread
    (abort), a proces PyInstallera zostaje sierota trzymajaca pliki."""
    window.screen_review.build_requested.emit(_plan(tmp_path))
    assert fake_build["wystartowal"].wait(timeout=5)
    assert window.worker.is_running() is True

    window.close()

    assert window.worker.is_running() is False
    assert fake_build["anulowany"] is True


def test_back_from_review_returns_to_the_drop_screen(qtbot, tmp_path):
    project = tmp_path / "projekt"
    project.mkdir()
    (project / "main.py").write_text("print('x')\n", encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.screen_drop.folder_chosen.emit(project)
    assert window.stack.currentIndex() == SCREEN_REVIEW

    window.screen_review.back_button.click()
    assert window.stack.currentIndex() == SCREEN_DROP


def test_going_back_is_blocked_while_a_build_runs(qtbot, tmp_path, monkeypatch):
    """Drugi build w trakcie pierwszego jest odrzucany przez `BuildWorker`
    po cichu — uzytkownik zobaczylby ekran postepu, ktory nigdy nie ruszy."""
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window.worker, "is_running", lambda: True)
    window.go_to(SCREEN_BUILD)

    window.screen_build.back_to_review.emit()
    assert window.stack.currentIndex() == SCREEN_BUILD
