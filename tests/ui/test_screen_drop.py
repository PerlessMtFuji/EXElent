"""Ekran 1 — pole na folder z kodem.

Ten ekran jest jedynym wejsciem do programu, wiec pilnujemy tu nie wygladu,
tylko trzech rzeczy: co uznajemy za wskazanie folderu, czego NIE uznajemy, i
czy wskazanie da sie powtorzyc jednym kliknieciem nastepnym razem.
"""

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QPushButton

from exelent.i18n import CATALOGS, current_language
from exelent.ui import recent, theme
from exelent.ui.screen_drop import DropScreen


@pytest.fixture
def screen(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    widget = DropScreen()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def mime():
    """Fabryka `QMimeData`, ktora trzyma referencje do konca testu.

    Bez tego obiekt ginie razem z ramka helpera, a `event.mimeData()` oddaje
    wskaznik po zwolnionej pamieci — PySide wraca wtedy golym `QObject`, a
    pytest wywala sie access violation przy renderowaniu tracebacku. To jest
    zycie obiektu w tescie, nie zachowanie ekranu.
    """
    kept = []

    def make(*paths, urls=None, text=None):
        data = QMimeData()
        if text is not None:
            data.setText(text)
        else:
            data.setUrls(
                list(urls) if urls is not None else [QUrl.fromLocalFile(str(p)) for p in paths]
            )
        kept.append(data)
        return data

    yield make
    kept.clear()


def _drop(data):
    return QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _drag_enter(data):
    return QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _recent_buttons(screen):
    widgets = (screen.recent_row.itemAt(i).widget() for i in range(screen.recent_row.count()))
    return [w for w in widgets if isinstance(w, QPushButton)]


# --- tekst ---


def test_the_screen_shows_sentences_not_key_names(screen):
    """`t()` przy nieznanym kluczu oddaje sam klucz i nie rzuca. Bez tego
    straznika literowka albo zapomniane tlumaczenie konczy sie napisem
    "drop_headline" na jedynym ekranie, ktory laik widzi na starcie."""
    catalog = CATALOGS[current_language()]
    shown = (screen.headline.text(), screen.browse.text(), screen.recent_label.text())
    assert [text for text in shown if text not in catalog.values()] == []


# --- rendering ---


def test_the_drop_zone_is_one_continuous_surface(screen):
    """Etykiety dziedzicza po regule `QWidget` NIEPRZEZROCZYSTE tlo `bg`, wiec
    naglowek i strzalka wycinaja w jasniejszej strefie ciemne prostokaty —
    widac to dopiero w renderingu, bo `styleSheet()` jako napis jest poprawny.
    Mierzone na pikselach: wewnatrz strefy nie moze byc ANI JEDNEGO piksela
    w kolorze tla okna (przed poprawka bylo ich 3624 w co trzecim punkcie).
    """
    screen.setStyleSheet(theme.build_stylesheet(dark=True))
    screen.resize(900, 620)
    screen.layout().activate()
    pixmap = screen.zone.grab()
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    inset = int(12 * ratio)
    bg = QColor(theme.PALETTE_DARK["bg"]).rgb()
    holes = sum(
        image.pixel(x, y) == bg
        for y in range(inset, image.height() - inset, 4)
        for x in range(inset, image.width() - inset, 4)
    )
    assert holes == 0, f"etykiety maluja wlasne tlo: {holes} pikseli koloru okna w strefie"


# --- co uznajemy za wskazanie folderu ---


def test_the_screen_accepts_drops_at_all(screen):
    """Testy wolaja `dropEvent` wprost, wiec omijaja bramke Qt: bez
    `setAcceptDrops(True)` Qt nie dostarczy ekranowi ZADNEGO zdarzenia
    przeciagania, a caly ekran przestaje dzialac przy zielonych testach."""
    assert screen.acceptDrops() is True


def test_dropping_folder_emits_signal(screen, qtbot, mime, tmp_path):
    project = tmp_path / "projekt"
    project.mkdir()
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.dropEvent(_drop(mime(project)))
    assert blocker.args == [project]


def test_dropping_a_file_selects_the_file_not_its_folder(screen, qtbot, mime, tmp_path):
    """Upuszczenie pojedynczego pliku wybiera SAM plik, nie jego folder
    nadrzedny — plik `test.txt` z Pobranych nie moze wciagnac calych
    Pobranych do analizy."""
    script = tmp_path / "test.txt"
    script.write_text("print('x')\n", encoding="utf-8")
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.dropEvent(_drop(mime(script)))
    assert blocker.args == [script]


def test_a_handled_drop_is_accepted(screen, mime, tmp_path):
    """Bez `acceptProposedAction` program-zrodlo pokazuje kursor odmowy i
    uzytkownik widzi, ze upuszczenie sie nie udalo — mimo ze sie udalo."""
    event = _drop(mime(tmp_path))
    screen.dropEvent(event)
    assert event.isAccepted()


# --- czego nie uznajemy ---


def test_dropping_a_link_from_a_browser_chooses_nothing(screen, qtbot, mime):
    """`QUrl("https://...").toLocalFile()` to pusty napis, a `Path("").parent`
    to katalog biezacy. Bez straznika przeciagniecie linku uruchamialoby
    analize katalogu, w ktorym akurat stoi program."""
    data = mime(urls=[QUrl("https://example.com/kod.zip")])
    with qtbot.assertNotEmitted(screen.folder_chosen):
        screen.dropEvent(_drop(data))


def test_dropping_nothing_useful_chooses_nothing(screen, qtbot, mime):
    with qtbot.assertNotEmitted(screen.folder_chosen):
        screen.dropEvent(_drop(mime(urls=[])))


def test_dragging_plain_text_is_refused(screen, mime):
    event = _drag_enter(mime(text="to nie jest folder"))
    screen.dragEnterEvent(event)
    assert screen.zone.property("active") is False
    assert not event.isAccepted()


# --- podswietlenie ramki ---


def test_drag_enter_marks_zone_active(screen, mime, tmp_path):
    event = _drag_enter(mime(tmp_path))
    screen.dragEnterEvent(event)
    assert screen.zone.property("active") is True
    assert event.isAccepted()


def test_leaving_the_zone_clears_the_highlight(screen, mime, tmp_path):
    screen.dragEnterEvent(_drag_enter(mime(tmp_path)))
    screen.dragLeaveEvent(QDragLeaveEvent())
    assert screen.zone.property("active") is False


def test_dropping_clears_the_highlight(screen, mime, tmp_path):
    screen.dragEnterEvent(_drag_enter(mime(tmp_path)))
    screen.dropEvent(_drop(mime(tmp_path)))
    assert screen.zone.property("active") is False


# --- lista ostatnich ---


def test_choosing_a_folder_remembers_it(screen, mime, tmp_path):
    project = tmp_path / "projekt"
    project.mkdir()
    screen.dropEvent(_drop(mime(project)))
    assert recent.load_recent() == [project]


def test_recent_list_is_shown(screen, tmp_path):
    project = tmp_path / "wczesniejszy"
    project.mkdir()
    recent.remember(project)
    screen.refresh_recent()
    assert [b.text() for b in _recent_buttons(screen)] == ["wczesniejszy"]


def test_nothing_remembered_means_no_recent_row(screen):
    screen.refresh_recent()
    assert _recent_buttons(screen) == []
    assert not screen.recent_label.isVisibleTo(screen)


def test_clicking_a_recent_entry_chooses_it(screen, qtbot, tmp_path):
    project = tmp_path / "wczesniejszy"
    project.mkdir()
    recent.remember(project)
    screen.refresh_recent()
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        _recent_buttons(screen)[0].click()
    assert blocker.args == [project]


def test_every_recent_entry_points_at_its_own_folder(screen, qtbot, tmp_path):
    """Lambda bez domyslnego argumentu zamyka sie po ZMIENNEJ petli, wiec
    wszystkie przyciski wskazywalyby ten sam, ostatni folder."""
    for name in ("pierwszy", "drugi"):
        (tmp_path / name).mkdir()
        recent.remember(tmp_path / name)
    screen.refresh_recent()
    first = _recent_buttons(screen)[0]
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        first.click()
    assert blocker.args == [tmp_path / first.text()]


def test_refreshing_twice_does_not_double_the_row(screen, tmp_path):
    """`refresh_recent` czysci uklad przed wypelnieniem — inaczej kazdy powrot
    na ekran dokladalby te same przyciski jeszcze raz."""
    project = tmp_path / "wczesniejszy"
    project.mkdir()
    recent.remember(project)
    screen.refresh_recent()
    screen.refresh_recent()
    assert len(_recent_buttons(screen)) == 1


# --- przycisk "wybierz folder" ---


def test_browsing_chooses_the_folder_from_the_dialog(screen, qtbot, monkeypatch, tmp_path):
    project = tmp_path / "z-okienka"
    project.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(project))
    )
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.browse.click()
    assert blocker.args == [project]


def test_a_cancelled_dialog_chooses_nothing(screen, qtbot, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    with qtbot.assertNotEmitted(screen.folder_chosen):
        screen.browse.click()
