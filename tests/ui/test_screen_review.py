"""Ekran 2 — co EXElent zrozumial z katalogu.

To jest ekran, na ktorym produkt albo mowi prawde, albo klamie po cichu.
Kazde zgadniecie ma byc WIDOCZNE przed pieciominutowym buildem i poprawialne,
a to, co uzytkownik poprawi, ma naprawde trafic do planu — testy pilnuja
obu polowek tej obietnicy osobno.
"""

from pathlib import Path

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QWidget

from exelent.analysis.project import analyze_project
from exelent.i18n import CATALOGS, current_language, set_language, t
from exelent.models import AppKind, OutputMode
from exelent.ui import theme
from exelent.ui.screen_review import ReviewScreen


@pytest.fixture(autouse=True)
def _restore_language():
    """Jezyk jest stanem globalnym — bez tego kolejnosc testow decydowalaby
    o tym, w jakim jezyku pracuja pozostale."""
    yield
    set_language("pl")


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "projekt"
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def screen(qtbot):
    widget = ReviewScreen()
    qtbot.addWidget(widget)
    return widget


def _load(screen, tmp_path, files):
    root = _project(tmp_path, files)
    screen.load(analyze_project(root))
    return root


def _shown_texts(widget):
    """Kazdy napis, ktory ekran naprawde pokazuje."""
    return [
        w.text()
        for w in widget.findChildren(QWidget)
        if hasattr(w, "text") and isinstance(w.text(), str)
    ]


def _entry_choices(screen):
    return [screen.entry_combo.itemText(i) for i in range(screen.entry_combo.count())]


def _accent_pixels(widget):
    """Ile pikseli widget maluje kolorem akcentu motywu ciemnego."""
    image = widget.grab().toImage()
    accent = QColor(theme.PALETTE_DARK["accent"]).rgb()
    return sum(
        image.pixel(x, y) == accent
        for y in range(0, image.height(), 2)
        for x in range(0, image.width(), 2)
    )


# --- tekst ---


def test_no_widget_shows_a_raw_key(screen, tmp_path):
    """`t()` przy nieznanym kluczu oddaje sam klucz i nie rzuca, wiec literowka
    konczy sie napisem "review_build" na przycisku. Sprawdzamy KAZDY widget,
    zeby straznik obejmowal tez to, co dojdzie pozniej."""
    _load(screen, tmp_path, {"main.py": "print(1)"})
    keys = set(CATALOGS[current_language()])
    leaked = [text for text in _shown_texts(screen) if text in keys]
    assert leaked == [], f"widget pokazuje surowy klucz: {leaked}"


def test_the_icon_dialog_speaks_the_users_language(screen, monkeypatch):
    """Filtr okienka wyboru pliku to tekst dla uzytkownika jak kazdy inny.

    Sprawdzane PO ANGIELSKU, bo to jedyny jezyk, w ktorym widac roznice:
    napis wpisany na sztywno po polsku jest przeciez rowny polskiemu
    tlumaczeniu, wiec asercja po polsku przechodzi takze dla niego (mutant
    M-T19n przezyl dokladnie w ten sposob).
    """
    seen = {}

    def fake(parent, caption, directory, filter_):
        seen["caption"] = caption
        seen["filter"] = filter_
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake))
    set_language("en")
    screen.icon_button.click()
    english = set(CATALOGS["en"].values())
    assert seen["filter"] in english and seen["caption"] in english


# --- fakty: co zrozumielismy ---


def test_shows_detected_entry_point(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    assert "main.py" in screen.row_entry.value_text()


def test_certain_detection_shows_check_mark(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    assert screen.row_entry.marker() == "✓"


def test_uncertain_detection_shows_question_mark(screen, tmp_path):
    _load(
        screen,
        tmp_path,
        {
            "a.py": "if __name__ == '__main__':\n    pass",
            "b.py": "if __name__ == '__main__':\n    pass",
        },
    )
    assert screen.row_entry.marker() == "?"


def test_entry_choices_distinguish_files_with_the_same_name(screen, tmp_path):
    """Sama nazwa pliku nie wystarcza: projekt z `main.py` w korzeniu i w
    podkatalogu dawalby dwie identyczne pozycje, a uzytkownik nie mialby jak
    wybrac wlasciwej — ani powiedziec, ktora jest zaznaczona."""
    _load(screen, tmp_path, {"main.py": "import pkg.main", "pkg/main.py": "print(2)"})
    suffix = f" {t('review_recommended_suffix')}"
    stripped = sorted(choice.removesuffix(suffix) for choice in _entry_choices(screen))
    assert stripped == ["main.py", "pkg/main.py"]


def test_kind_follows_the_analysis(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "import tkinter\ntkinter.Tk()"})
    assert (
        screen.kind_combo.currentText() == f"{t('kind_windowed')} {t('review_recommended_suffix')}"
    )


def test_uncertain_kind_shows_question_mark(screen, tmp_path):
    """Okno i `input()` naraz — rdzen nie wie, czy konsola ma zostac."""
    _load(screen, tmp_path, {"main.py": "import tkinter\ninput()"})
    assert screen.row_kind.marker() == "?"


def test_name_starts_as_the_folder_name(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    assert screen.name_edit.text() == "projekt"


def test_found_icon_is_shown_on_the_button(screen, tmp_path):
    root = _project(tmp_path, {"main.py": "print(1)"})
    (root / "icon.ico").write_bytes(b"\x00")
    screen.load(analyze_project(root))
    assert screen.icon_button.text() == "icon.ico"


# --- dodatki ---


def test_dependencies_are_listed(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "import requests\nimport rich"})
    text = screen.deps_label.text()
    assert "requests" in text and "rich" in text


def test_dependency_section_hidden_when_none(screen, tmp_path):
    """`isVisible()` na niepokazanym oknie jest ZAWSZE False, wiec asercja na
    nim przechodzi takze dla sekcji, ktora nigdy sie nie chowa. `isVisibleTo`
    pyta o to, co uzytkownik zobaczy po pokazaniu okna."""
    _load(screen, tmp_path, {"main.py": "import os"})
    assert screen.deps_box.isVisibleTo(screen) is False


def test_dependency_section_comes_back_for_the_next_project(screen, tmp_path):
    """Schowanie bez odslaniania to blad jednokierunkowy: drugi projekt w tej
    samej sesji nie pokazalby ani jednej paczki."""
    _load(screen, tmp_path, {"main.py": "import os"})
    _load(screen, tmp_path / "drugi", {"main.py": "import requests"})
    assert screen.deps_box.isVisibleTo(screen) is True


# --- ostrzezenia ---


def test_warnings_are_shown_as_sentences_not_codes(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "from flask import Flask"})
    text = screen.warnings_label.text()
    assert "server_app" not in text
    assert "flask" in text.lower()


def test_a_clean_project_shows_no_warning_line(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    assert screen.warnings_label.text() == ""
    assert screen.warnings_label.isVisibleTo(screen) is False


def test_warnings_do_not_survive_the_next_project(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "from flask import Flask"})
    _load(screen, tmp_path / "drugi", {"main.py": "print(1)"})
    assert screen.warnings_label.text() == ""


# --- blokada ---


def test_blocker_disables_build_button(screen, tmp_path):
    _load(screen, tmp_path, {"kod.txt": "def f(:\n    pass"})
    assert screen.build_button.isEnabled() is False


def test_the_button_comes_back_when_the_next_project_is_fine(screen, tmp_path):
    _load(screen, tmp_path, {"kod.txt": "def f(:\n    pass"})
    _load(screen, tmp_path / "drugi", {"main.py": "print(1)"})
    assert screen.build_button.isEnabled() is True


def test_a_blocked_build_button_looks_blocked(screen, tmp_path):
    """Zmierzone na PIKSELACH, bo `isEnabled()` nie mowi nic o wygladzie:
    arkusz ustawia tlo przycisku wprost, wiec bez reguly `:disabled` Qt nie
    ma czego wygasic i martwy przycisk wyglada dokladnie jak dzialajacy."""
    screen.setStyleSheet(theme.build_stylesheet(dark=True))
    screen.resize(900, 620)

    _load(screen, tmp_path, {"main.py": "print(1)"})
    screen.layout().activate()
    zywy = _accent_pixels(screen.build_button)

    _load(screen, tmp_path / "zepsuty", {"kod.txt": "def f(:\n    pass"})
    screen.layout().activate()
    martwy = _accent_pixels(screen.build_button)

    assert zywy > 0, "aktywny przycisk nie jest w kolorze akcentu"
    assert martwy == 0, f"zablokowany przycisk nadal maluje akcent: {martwy} pikseli"


def test_an_empty_entry_row_is_not_certain(screen, tmp_path):
    """Pusty wiersz ze znacznikiem `✓` to fałszywa pewność o niczym."""
    _load(screen, tmp_path, {"kod.txt": "def f(:\n    pass"})
    assert screen.row_entry.marker() == "?"


def test_a_blocked_project_still_says_why(screen, tmp_path):
    """Wygaszony przycisk bez zdania to slepy zaulek — uzytkownik widzi, ze
    nie moze isc dalej, i nie wie dlaczego."""
    _load(screen, tmp_path, {"kod.txt": "def f(:\n    pass"})
    assert "kod.txt" in screen.warnings_label.text()


# --- co trafia do planu ---


def test_build_button_emits_plan(screen, qtbot, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].entry.name == "main.py"


def test_the_plan_points_at_the_analysed_folder(screen, qtbot, tmp_path):
    root = _load(screen, tmp_path, {"main.py": "import requests"})
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    plan = blocker.args[0]
    assert plan.root == root
    assert plan.packages == ("requests",)


def test_edited_name_reaches_the_plan(screen, qtbot, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    screen.name_edit.setText("Kalkulator Pro")
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].exe_name == "Kalkulator Pro"


def test_changing_entry_updates_plan(screen, qtbot, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)", "inny.py": "print(2)"})
    screen.entry_combo.setCurrentText("inny.py")
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].entry.name == "inny.py"


def test_kind_override_reaches_the_plan(screen, qtbot, tmp_path):
    """`is`, nie `==`, i to jest sedno tego testu: Qt oddaje dane pozycji jako
    GOŁY napis, a rdzeń porownuje te pola tozsamoscia (`plan.app_kind is
    AppKind.WINDOWED` w `pyinstaller.py`). Napis rowna sie enumowi, wiec `==`
    przepuscilby blad, po ktorym za kazdym oknem stoi czarna konsola."""
    _load(screen, tmp_path, {"main.py": "print(1)"})
    screen.kind_combo.setCurrentIndex(screen.kind_combo.findData(AppKind.WINDOWED))
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].app_kind is AppKind.WINDOWED


def test_output_mode_override_reaches_plan(screen, qtbot, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    screen.mode_combo.setCurrentIndex(screen.mode_combo.findData(OutputMode.ONEDIR))
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].output_mode is OutputMode.ONEDIR


def test_chosen_icon_reaches_the_plan(screen, qtbot, monkeypatch, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    wybrana = tmp_path / "moja.png"
    wybrana.write_bytes(b"\x00")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(wybrana), ""))
    )
    screen.icon_button.click()
    assert screen.icon_button.text() == "moja.png"
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].icon == wybrana


def test_a_cancelled_icon_dialog_keeps_the_found_one(screen, qtbot, monkeypatch, tmp_path):
    root = _project(tmp_path, {"main.py": "print(1)"})
    (root / "icon.ico").write_bytes(b"\x00")
    screen.load(analyze_project(root))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    screen.icon_button.click()
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].icon == root / "icon.ico"


def test_an_icon_does_not_leak_into_the_next_project(screen, qtbot, monkeypatch, tmp_path):
    """Ikona WSKAZANA RECZNIE, bo tylko ona zyje poza `load` — ta znaleziona
    w katalogu znika razem z analiza, wiec na niej mutant kasujacy zerowanie
    przechodzil (M-T19p). Bez zerowania drugi projekt dostaje ikone pierwszego,
    a przycisk pokazuje przy tym "wybierz" — czyli nawet ekran o tym nie wie.
    """
    _load(screen, tmp_path, {"main.py": "print(1)"})
    wybrana = tmp_path / "moja.png"
    wybrana.write_bytes(b"\x00")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(wybrana), ""))
    )
    screen.icon_button.click()
    _load(screen, tmp_path / "drugi", {"main.py": "print(1)"})
    with qtbot.waitSignal(screen.build_requested, timeout=1000) as blocker:
        screen.build_button.click()
    assert blocker.args[0].icon is None


def test_clicking_build_before_loading_emits_nothing(screen, qtbot):
    """Ekran istnieje od startu programu, wiec stan "nic nie wczytano" jest
    prawdziwy. Bez straznika klikniecie konczy sie tracebackiem."""
    with qtbot.assertNotEmitted(screen.build_requested):
        screen.build_button.click()


def test_loading_another_project_replaces_the_choices(screen, tmp_path):
    """Bez czyszczenia listy pliki poprzedniego projektu zostaja do wyboru —
    a wybrany z nich nie istnieje juz w nowym katalogu."""
    _load(screen, tmp_path, {"main.py": "print(1)"})
    _load(screen, tmp_path / "drugi", {"inny.py": "print(2)"})
    assert _entry_choices(screen) == [f"inny.py {t('review_recommended_suffix')}"]


def test_loading_another_project_replaces_the_name(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print(1)"})
    screen.name_edit.setText("Recznie Nazwany")
    _load(screen, tmp_path / "drugi", {"main.py": "print(2)"})
    assert screen.name_edit.text() == "projekt"


# --- postac wyniku, rekomendacje, koniec "zaawansowanych" ---


def test_output_mode_is_visible_without_clicking_anything(screen, tmp_path):
    """Postac wyniku to informacja o tym, co uzytkownik dostanie na koncu.

    Schowana pod przelacznikiem "Zaawansowane" byla widoczna tylko dla tych,
    ktorzy i tak wiedza, czego szukac.
    """
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    assert screen.row_mode.caption_text() == t("review_mode")
    assert screen.row_mode.isHidden() is False


def test_the_advanced_panel_is_gone_entirely(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    assert not hasattr(screen, "advanced_toggle")
    assert "review_advanced" not in CATALOGS[current_language()]


def test_recommended_item_is_labelled_but_data_stays_typed(screen, tmp_path):
    """Dopisek jest ETYKIETA. `currentData()` ma nadal oddawac enum.

    Regresja tego rodzaju nie widac na ekranie: plan po cichu dostaje napis
    zamiast `AppKind` i uzytkownik, ktory wybral okno, dostaje czarna konsole.
    """
    _load(screen, tmp_path, {"main.py": "import tkinter\ntkinter.Tk()\n"})
    assert "(" in screen.kind_combo.currentText()
    assert screen.kind_combo.currentData() in (AppKind.WINDOWED, AppKind.CONSOLE)
    assert screen.mode_combo.currentData() in (OutputMode.ONEFILE, OutputMode.ONEDIR)


def test_restore_link_returns_the_recommended_value(screen, tmp_path):
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    recommended = screen.kind_combo.currentText()
    other = 1 - screen.kind_combo.currentIndex()
    screen.kind_combo.setCurrentIndex(other)
    assert screen.row_kind.restore_visible() is True

    screen.row_kind.restore_button().click()
    assert screen.kind_combo.currentText() == recommended
    assert screen.row_kind.restore_visible() is False


# --- wiersz faktu ---


def test_a_fact_row_starts_certain(screen):
    assert screen.row_name.marker() == "✓"


def test_a_fact_row_shows_its_caption(screen):
    assert screen.row_entry.caption_text() == t("review_entry")


def test_back_button_emits_instead_of_navigating(qtbot, screen, tmp_path):
    """Ekran nie wie o istnieniu innych ekranow — zglasza zamiar sygnalem.

    To ta sama zasada, ktora trzyma `build_requested`: kolejnosc ekranow zna
    wylacznie okno.
    """
    _load(screen, tmp_path, {"main.py": "print('x')\n"})
    with qtbot.waitSignal(screen.back_requested, timeout=1000):
        screen.back_button.click()
