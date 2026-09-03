"""Ekran 3 — postep budowania i wynik.

Ekran ma cztery stany w jednym widgecie: trwa, udalo sie, nie udalo sie,
przerwane. Testy pilnuja glownie tego, czego uzytkownik NIE ma zobaczyc:
poprzedniego builda w trakcie nowego, przycisku "zglos blad" po wlasnorecznym
anulowaniu i pustego zdania zamiast diagnozy.
"""

import pytest
from PySide6.QtWidgets import QFileDialog, QWidget

from exelent.i18n import CATALOGS, current_language, set_language, t
from exelent.models import AppKind, BuildPlan, BuildResult, Issue, OutputMode, Severity
from exelent.runtime import Progress
from exelent.ui import screen_build as screen_build_module
from exelent.ui.screen_build import BuildScreen


@pytest.fixture(autouse=True)
def _restore_language():
    yield
    set_language("pl")


@pytest.fixture
def screen(qtbot):
    widget = BuildScreen()
    qtbot.addWidget(widget)
    return widget


def _plan(tmp_path, name="Kalkulator"):
    return BuildPlan(
        root=tmp_path / "projekt",
        entry=tmp_path / "projekt" / "main.py",
        app_kind=AppKind.WINDOWED,
        output_mode=OutputMode.ONEFILE,
        exe_name=name,
        dest_dir=tmp_path / "out",
    )


def _artifact(tmp_path, size=2048):
    path = tmp_path / "Program.exe"
    path.write_bytes(b"x" * size)
    return path


def _shown_texts(widget):
    return [
        w.text()
        for w in widget.findChildren(QWidget)
        if hasattr(w, "text") and isinstance(w.text(), str)
    ]


def _visible(widget, screen):
    return widget.isVisibleTo(screen)


# --- tekst ---


def test_no_widget_shows_a_raw_key(screen, tmp_path):
    screen.start(_plan(tmp_path))
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path), size_bytes=2048))
    keys = set(CATALOGS[current_language()])
    leaked = [text for text in _shown_texts(screen) if text in keys]
    assert leaked == [], f"widget pokazuje surowy klucz: {leaked}"


def test_the_phase_is_a_sentence_not_a_key(screen):
    screen.on_progress(Progress(phase="analyze", fraction=0.4))
    assert screen.phase_label.text() == t("analyze")


# --- postep ---


def test_progress_updates_bar_and_phase_text(screen):
    screen.on_progress(Progress(phase="analyze", fraction=0.4))
    assert screen.bar.value() == 40
    assert screen.phase_label.text() != ""


def test_a_running_build_shows_only_the_cancel_button(screen, tmp_path):
    screen.start(_plan(tmp_path))
    assert _visible(screen.cancel_button, screen) is True
    for button in (screen.open_folder_button, screen.run_button, screen.again_button):
        assert _visible(button, screen) is False


# --- sukces ---


def test_success_shows_size_and_actions(screen, tmp_path):
    """`isVisible()` na niepokazanym oknie jest ZAWSZE False, wiec asercja
    `isVisible() is True` z planu nie moze przejsc, a `is False` przechodzi
    zawsze. Pytamy `isVisibleTo`, czyli o to, co uzytkownik zobaczy."""
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path), size_bytes=2048))
    assert _visible(screen.open_folder_button, screen) is True
    assert "MB" in screen.summary_label.text() or "KB" in screen.summary_label.text()


def test_success_shows_antivirus_note(screen, tmp_path):
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path, 1), size_bytes=1))
    assert _visible(screen.antivirus_label, screen) is True


def test_success_fills_the_bar(screen, tmp_path):
    screen.on_progress(Progress(phase="analyze", fraction=0.4))
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path), size_bytes=2048))
    assert screen.bar.value() == 100


def test_cancel_button_hidden_after_finish(screen, tmp_path):
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path, 1), size_bytes=1))
    assert _visible(screen.cancel_button, screen) is False


def test_success_does_not_offer_a_bug_report(screen, tmp_path):
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path, 1), size_bytes=1))
    assert _visible(screen.github_button, screen) is False
    assert _visible(screen.report_button, screen) is False


# --- porazka ---


def test_failure_shows_translated_issue(screen):
    screen.on_finished(BuildResult(ok=False, issues=(Issue("no_network", Severity.BLOCKER),)))
    assert screen.summary_label.text() == t("no_network")
    assert _visible(screen.report_button, screen) is True


def test_failure_offers_github_issue(screen, tmp_path):
    log = tmp_path / "build.log"
    log.write_text("nieznany blad", encoding="utf-8")
    screen.on_finished(BuildResult(ok=False, log_path=log))
    assert _visible(screen.github_button, screen) is True


def test_a_failure_without_any_issue_still_says_something(screen):
    """Build, ktorego logu nie rozpoznal zaden wzorzec, wraca z PUSTA lista
    Issue (`pyinstaller.py`, returncode != 0). Pusty ekran w takim momencie
    to koniec drogi dla uzytkownika."""
    screen.on_finished(BuildResult(ok=False))
    assert screen.summary_label.text() == t("build_failed_unknown")


def test_failure_offers_no_way_to_run_a_file_that_does_not_exist(screen):
    screen.on_finished(BuildResult(ok=False))
    assert _visible(screen.run_button, screen) is False
    assert _visible(screen.open_folder_button, screen) is False


def test_failure_shows_no_antivirus_note(screen):
    """Ostrzezenie o falszywych alarmach dotyczy GOTOWEGO pliku. Po porazce
    zadnego pliku nie ma, a rada "dodaj go do wyjatkow" wysyla laika w droge
    donikad."""
    screen.on_finished(BuildResult(ok=False))
    assert _visible(screen.antivirus_label, screen) is False


# --- przerwanie ---


def test_a_cancelled_build_is_not_reported_as_a_failure(screen):
    """`build_cancelled` to INFO, nie awaria: uzytkownik sam przerwal. Ekran
    z naglowkiem "Nie udalo sie" i przyciskiem "Zglos na GitHubie" prosi go o
    zgloszenie wlasnej decyzji jako bledu."""
    screen.on_finished(BuildResult(ok=False, issues=(Issue("build_cancelled", Severity.INFO),)))
    assert screen.phase_label.text() == t("build_cancelled")
    assert screen.phase_label.text() != t("build_failed_title")
    assert _visible(screen.github_button, screen) is False
    assert _visible(screen.report_button, screen) is False
    assert _visible(screen.again_button, screen) is True


def test_a_cancel_that_left_something_behind_still_warns(screen):
    """`cancel_incomplete` znaczy, ze proces PyInstallera moze wciaz zyc i
    trzymac pliki — nastepny build padnie z powodu, ktorego nikt nie polaczy
    z tamtym anulowaniem."""
    screen.on_finished(
        BuildResult(
            ok=False,
            issues=(
                Issue("build_cancelled", Severity.INFO),
                Issue("cancel_incomplete", Severity.WARNING),
            ),
        )
    )
    assert t("cancel_incomplete") in screen.summary_label.text()


# --- nowy build kasuje poprzedni ---


def test_starting_a_new_build_clears_the_previous_result(screen, tmp_path):
    """Bez tego drugi build biegnie z paskiem postepu i JEDNOCZESNIE ze zdaniem
    o awarii poprzedniego, przyciskiem "Zapisz raport" i logiem sprzed chwili."""
    log = tmp_path / "build.log"
    log.write_text("stary log", encoding="utf-8")
    screen.on_finished(
        BuildResult(ok=False, log_path=log, issues=(Issue("no_network", Severity.BLOCKER),))
    )

    screen.start(_plan(tmp_path))

    assert screen.summary_label.text() == ""
    assert screen.log_view.toPlainText() == ""
    assert screen.bar.value() == 0
    assert _visible(screen.log_toggle, screen) is False
    assert _visible(screen.report_button, screen) is False
    assert _visible(screen.github_button, screen) is False
    assert _visible(screen.again_button, screen) is False
    assert _visible(screen.cancel_button, screen) is True


def test_starting_a_new_build_hides_the_previous_success(screen, tmp_path):
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path), size_bytes=2048))
    screen.start(_plan(tmp_path))
    assert _visible(screen.open_folder_button, screen) is False
    assert _visible(screen.antivirus_label, screen) is False


# --- log ---


def test_the_log_is_shown_when_the_build_leaves_one(screen, tmp_path):
    log = tmp_path / "build.log"
    log.write_text("linia jeden\nlinia dwa", encoding="utf-8")
    screen.on_finished(BuildResult(ok=False, log_path=log))
    assert "linia dwa" in screen.log_view.toPlainText()


def test_a_missing_log_file_is_not_a_crash(screen, tmp_path):
    """Sciezka logu przychodzi z rdzenia, ale plik moze zniknac — build w
    katalogu tymczasowym sprzatanym przez system to normalna sytuacja."""
    screen.on_finished(BuildResult(ok=False, log_path=tmp_path / "nie-ma.log"))
    assert screen.log_view.toPlainText() == ""


def test_the_log_toggle_opens_and_closes(screen, tmp_path):
    log = tmp_path / "build.log"
    log.write_text("cos", encoding="utf-8")
    screen.on_finished(BuildResult(ok=False, log_path=log))
    screen.log_toggle.click()
    assert _visible(screen.log_view, screen) is True
    screen.log_toggle.click()
    assert _visible(screen.log_view, screen) is False


# --- raport ---


def test_the_report_names_the_project_not_the_missing_artifact(screen, monkeypatch, tmp_path):
    """Raport powstaje WYLACZNIE po porazce, a wtedy artefaktu nie ma — wersja
    z planu opisywala wiec kazde zgloszenie slowem "build". Ekran zna plan,
    wiec zna nazwe projektu."""
    log = tmp_path / "build.log"
    log.write_text("tresc logu", encoding="utf-8")
    cel = tmp_path / "raport.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(cel), ""))
    )

    screen.start(_plan(tmp_path, name="Kalkulator"))
    screen.on_finished(BuildResult(ok=False, log_path=log))
    screen.report_button.click()

    zapisane = cel.read_text(encoding="utf-8")
    assert "Kalkulator" in zapisane
    assert "tresc logu" in zapisane


def test_a_cancelled_save_dialog_writes_nothing(screen, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    screen.on_finished(BuildResult(ok=False))
    screen.report_button.click()
    assert list(tmp_path.glob("*.txt")) == []


def test_the_save_dialog_speaks_the_users_language(screen, monkeypatch):
    """Sprawdzane po angielsku — polski napis wpisany na sztywno jest rowny
    polskiemu tlumaczeniu, wiec asercja po polsku niczego nie mierzy."""
    seen = {}

    def fake(parent, caption, name, filter_):
        seen.update(caption=caption, filter=filter_)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake))
    set_language("en")
    screen.on_finished(BuildResult(ok=False))
    screen.report_button.click()
    english = set(CATALOGS["en"].values())
    assert seen["caption"] in english and seen["filter"] in english


def test_github_button_opens_a_prefilled_issue(screen, monkeypatch, tmp_path):
    log = tmp_path / "build.log"
    log.write_text("PyInstaller: cos peklo", encoding="utf-8")
    otwarte = []
    monkeypatch.setattr(screen_build_module.webbrowser, "open", otwarte.append)

    screen.start(_plan(tmp_path, name="Kalkulator"))
    screen.on_finished(BuildResult(ok=False, log_path=log))
    screen.github_button.click()

    assert len(otwarte) == 1
    assert "github.com" in otwarte[0]
    assert "Kalkulator" in otwarte[0]


# --- gotowy plik ---


def test_open_folder_points_at_the_artifact(screen, monkeypatch, tmp_path):
    wywolania = []
    monkeypatch.setattr(screen_build_module.subprocess, "run", lambda *a, **k: wywolania.append(a))
    artefakt = _artifact(tmp_path)
    screen.on_finished(BuildResult(ok=True, artifact=artefakt, size_bytes=2048))
    screen.open_folder_button.click()
    assert wywolania, "przycisk nic nie uruchomil"
    assert str(artefakt) in " ".join(wywolania[0][0])


def test_run_button_launches_the_built_program(screen, monkeypatch, tmp_path):
    uruchomione = []
    monkeypatch.setattr(
        screen_build_module.subprocess, "Popen", lambda *a, **k: uruchomione.append(a)
    )
    artefakt = _artifact(tmp_path)
    screen.on_finished(BuildResult(ok=True, artifact=artefakt, size_bytes=2048))
    screen.run_button.click()
    assert uruchomione == [([str(artefakt)],)]


def test_a_onedir_result_opens_the_folder_itself(screen, monkeypatch, tmp_path):
    """Przy `OutputMode.ONEDIR` artefaktem jest KATALOG, nie plik."""
    wywolania = []
    monkeypatch.setattr(screen_build_module.subprocess, "run", lambda *a, **k: wywolania.append(a))
    folder = tmp_path / "Program"
    folder.mkdir()
    screen.on_finished(BuildResult(ok=True, artifact=folder, size_bytes=2048))
    screen.open_folder_button.click()
    assert str(folder) in " ".join(wywolania[0][0])


# --- powrot na start ---


def test_restart_signal_returns_to_start(screen, qtbot, tmp_path):
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path, 1), size_bytes=1))
    with qtbot.waitSignal(screen.restart_requested, timeout=1000):
        screen.again_button.click()


def test_human_size_reads_like_a_size(screen, tmp_path):
    screen.on_finished(
        BuildResult(ok=True, artifact=_artifact(tmp_path, 1), size_bytes=12 * 1024**2)
    )
    assert "12.0 MB" in screen.summary_label.text()


def test_the_summary_names_the_file(screen, tmp_path):
    artefakt = _artifact(tmp_path)
    screen.on_finished(BuildResult(ok=True, artifact=artefakt, size_bytes=2048))
    assert artefakt.name in screen.summary_label.text()


def test_a_report_path_without_a_log_still_works(screen, monkeypatch, tmp_path):
    """Porazka przed uruchomieniem PyInstallera (brak internetu, brak miejsca)
    nie ma logu. Raport ma wtedy nieść to, co ekran wie: rozpoznane zdanie."""
    cel = tmp_path / "raport.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(cel), ""))
    )
    screen.on_finished(BuildResult(ok=False, issues=(Issue("no_network", Severity.BLOCKER),)))
    screen.report_button.click()
    assert t("no_network") in cel.read_text(encoding="utf-8")


def test_the_screen_survives_a_result_it_did_not_start(screen, tmp_path):
    """`on_finished` bez wczesniejszego `start` — stan prawdziwy przy pierwszym
    uruchomieniu okna, gdyby ktos podal wynik z zewnatrz."""
    screen.on_finished(BuildResult(ok=False))
    assert screen.summary_label.text() != ""
    assert isinstance(screen._plan_summary(), str)


def test_the_log_view_keeps_the_whole_tail_it_promises(screen, tmp_path):
    """Log PyInstallera ma tysiace linii, a domyslny `tail()` obcina do 40 —
    czyli do miejsca, w ktorym typowy traceback dopiero sie zaczyna."""
    log = tmp_path / "build.log"
    log.write_text("\n".join(f"linia {i}" for i in range(300)), encoding="utf-8")
    screen.on_finished(BuildResult(ok=False, log_path=log))
    pokazane = screen.log_view.toPlainText()
    assert "linia 299" in pokazane
    assert "linia 150" in pokazane


# --- kazdy stan okresla CALY ekran ---


def test_a_cancel_after_a_failure_drops_the_bug_report(screen):
    """Stan, ktory tylko DOKLADA sie do poprzedniego, zostawia na ekranie
    przycisk "Zglos na GitHubie" z poprzedniej porazki — a uzytkownik wlasnie
    sam przerwal budowanie. Zmierzone na renderze."""
    screen.on_finished(BuildResult(ok=False, issues=(Issue("no_network", Severity.BLOCKER),)))
    screen.on_finished(BuildResult(ok=False, issues=(Issue("build_cancelled", Severity.INFO),)))
    assert _visible(screen.github_button, screen) is False
    assert _visible(screen.report_button, screen) is False


def test_a_failure_after_a_success_drops_the_run_button(screen, tmp_path):
    """Odwrotnie: po porazce nie moze zostac przycisk "Uruchom" ani zdanie o
    antywirusie — obie rzeczy dotycza pliku, ktorego nie ma."""
    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path), size_bytes=2048))
    screen.on_finished(BuildResult(ok=False, issues=(Issue("no_network", Severity.BLOCKER),)))
    assert _visible(screen.run_button, screen) is False
    assert _visible(screen.open_folder_button, screen) is False
    assert _visible(screen.antivirus_label, screen) is False


def test_the_bar_disappears_when_it_has_nothing_left_to_measure(screen, tmp_path):
    """Pasek zatrzymany na 92% pod naglowkiem "Nie udalo sie" mowi dwie
    sprzeczne rzeczy naraz. Po sukcesie zostaje — pelny pasek to potwierdzenie."""
    screen.on_progress(Progress(phase="package", fraction=0.92))
    screen.on_finished(BuildResult(ok=False))
    assert _visible(screen.bar, screen) is False

    screen.start(_plan(tmp_path))
    assert _visible(screen.bar, screen) is True

    screen.on_finished(BuildResult(ok=True, artifact=_artifact(tmp_path), size_bytes=2048))
    assert _visible(screen.bar, screen) is True


def test_the_log_opens_at_its_end(screen, tmp_path):
    """Powod awarii jest na koncu logu. Otwarty na pierwszej linii kaze
    uzytkownikowi przewinac dwiescie linii, zanim cokolwiek zobaczy."""
    log = tmp_path / "build.log"
    log.write_text("\n".join(f"linia {i}" for i in range(150)), encoding="utf-8")
    screen.on_finished(BuildResult(ok=False, log_path=log))
    tekst = screen.log_view.toPlainText()
    assert screen.log_view.textCursor().position() == len(tekst)


# --- powrot do przegladu ---


def test_back_to_review_offered_after_failure(qtbot, screen):
    screen.on_finished(BuildResult(ok=False, issues=(Issue("disk_full", Severity.BLOCKER),)))
    assert screen.back_button.isHidden() is False


def test_back_to_review_offered_after_cancel(qtbot, screen):
    screen.on_finished(BuildResult(ok=False, issues=(Issue("build_cancelled", Severity.INFO),)))
    assert screen.back_button.isHidden() is False


def test_back_to_review_not_offered_after_success(qtbot, screen, tmp_path):
    artifact = tmp_path / "Program.exe"
    artifact.write_bytes(b"x" * 2048)
    screen.on_finished(BuildResult(ok=True, artifact=artifact, size_bytes=2048))
    assert screen.back_button.isHidden() is True


def test_back_button_is_hidden_while_running(qtbot, screen, tmp_path):
    """Kazdy stan ma OKRESLAC caly ekran, a nie dokladac sie do poprzedniego.

    Ten sam blad zjadl juz "Zglos na GitHubie", ktorym zostawal po porazce na
    ekranie przerwania — patrz `_hide_all_actions`.
    """
    screen.on_finished(BuildResult(ok=False, issues=(Issue("disk_full", Severity.BLOCKER),)))
    screen.start(_plan(tmp_path))
    assert screen.back_button.isHidden() is True
