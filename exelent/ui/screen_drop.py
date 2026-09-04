"""Ekran 1 — pole na folder albo pojedynczy plik z kodem."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from exelent.i18n import t
from exelent.ui import recent


def _source_from(mime) -> Path | None:
    """Ścieżka wskazana przez upuszczone dane albo None, gdy to nie ścieżka.

    Plik NIE jest zamieniany na katalog nadrzędny. Poprzednia wersja robiła
    `path.parent` i przez to `test.txt` upuszczony z Pobranych wybierał całe
    Pobrane — łącznie z kopiowaniem ich do katalogu roboczego.

    Wszystko, co nie jest ścieżką lokalną (link przeciągnięty z przeglądarki,
    zaznaczony tekst), nadal odrzucamy jawnie: pusty `toLocalFile()` po
    `Path(...)` daje katalog bieżący, więc cicha tolerancja kończyłaby się
    analizą przypadkowego miejsca.
    """
    for url in mime.urls():
        local = url.toLocalFile()
        if not local:
            continue
        return Path(local)
    return None


class SourceDialog(QFileDialog):
    """Okno wyboru, ktore przyjmuje ZAROWNO plik, jak i katalog.

    Qt nie ma takiego trybu. `getExistingDirectory` pozwala kliknac wylacznie
    katalog, wiec uzytkownik proszony o wskazanie swojego `program.txt`
    zaznaczal folder, w ktorym ten plik lezy — i EXElent bral caly folder,
    z Pobranymi wlacznie. `getOpenFileName` ma odwrotna wade: nie da sie nim
    wskazac projektu zlozonego z wielu plikow.

    Dlatego tryb katalogu (zeby katalog dalo sie zatwierdzic) z widocznymi
    plikami, plus `accept()` ponizej, ktore przepuszcza plik. Okno musi byc
    nienatywne: natywne okno Windows realizuje tryb katalogu po swojemu i w
    ogole nie pokazuje plikow, wiec nie byloby czego klikac.
    """

    def __init__(self, parent: QWidget | None, caption: str) -> None:
        super().__init__(parent, caption)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setFileMode(QFileDialog.FileMode.Directory)
        self.setOption(QFileDialog.Option.ShowDirsOnly, False)

    def accept(self) -> None:
        selected = self.selectedFiles()
        if selected and Path(selected[0]).is_file():
            # QFileDialog.accept() w trybie katalogu odrzuciloby plik (albo
            # potraktowalo go jak katalog do wejscia). QDialog.accept() konczy
            # okno z pominieciem tej walidacji, a wybor zostaje w selectedFiles().
            QDialog.accept(self)
            return
        super().accept()


def choose_source(parent: QWidget | None, caption: str) -> Path | None:
    """Sciezka z okna wyboru albo None, gdy uzytkownik zrezygnowal.

    Osobna funkcja modulu, a nie metoda ekranu: to jedyne miejsce, ktore
    naprawde otwiera okno, wiec testy ekranu podmieniaja wlasnie ja zamiast
    uruchamiac modalny dialog.
    """
    dialog = SourceDialog(parent, caption)
    if not dialog.exec():
        return None
    selected = dialog.selectedFiles()
    return Path(selected[0]) if selected else None


class DropScreen(QWidget):
    folder_chosen = Signal(Path)
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

        self.settings_button = QPushButton("⚙", objectName="Link")
        self.settings_button.setToolTip(t("settings_title"))
        self.settings_button.clicked.connect(self.settings_requested)

        self.zone = QFrame(objectName="DropZone")
        self.zone.setProperty("active", False)
        zone_layout = QVBoxLayout(self.zone)
        zone_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone_layout.setSpacing(14)

        arrow = QLabel("⬇", objectName="Title")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.headline = QLabel(t("drop_headline"), objectName="Title")
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browse = QPushButton(t("drop_browse"))
        self.browse.clicked.connect(self._browse)

        zone_layout.addWidget(arrow)
        zone_layout.addWidget(self.headline)
        zone_layout.addWidget(self.browse, alignment=Qt.AlignmentFlag.AlignCenter)

        self.recent_row = QHBoxLayout()
        self.recent_label = QLabel(t("drop_recent"), objectName="Muted")

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        top_row.addWidget(self.settings_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 32)
        outer.setSpacing(20)
        outer.addLayout(top_row)
        outer.addWidget(self.zone, stretch=1)
        outer.addWidget(self.recent_label)
        outer.addLayout(self.recent_row)

        self.refresh_recent()

    def retranslate(self) -> None:
        """Przepisuje napisy po zmianie języka.

        Ekrany biorą teksty z `t()` w konstruktorze, więc bez tej metody
        przełącznik języka działałby dopiero po restarcie programu.
        """
        self.headline.setText(t("drop_headline"))
        self.browse.setText(t("drop_browse"))
        self.recent_label.setText(t("drop_recent"))
        self.settings_button.setToolTip(t("settings_title"))

    def refresh_recent(self) -> None:
        while self.recent_row.count():
            item = self.recent_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = recent.load_recent()
        self.recent_label.setVisible(bool(entries))
        # Etykiety liczone dla CALEJ listy naraz: skrot jest jednoznaczny
        # tylko w kontekscie pozostalych wpisow (patrz `recent.display_labels`).
        for path, label in zip(entries, recent.display_labels(entries), strict=True):
            button = QPushButton(label, objectName="Link")
            button.setToolTip(str(path))
            button.clicked.connect(lambda _checked=False, p=path: self._choose(p))
            self.recent_row.addWidget(button)
        self.recent_row.addStretch(1)

    def _browse(self) -> None:
        chosen = choose_source(self, t("drop_browse"))
        if chosen is not None:
            self._choose(chosen)

    def _choose(self, path: Path) -> None:
        recent.remember(path)
        self.folder_chosen.emit(path)

    def _set_active(self, active: bool) -> None:
        self.zone.setProperty("active", active)
        self.zone.style().unpolish(self.zone)
        self.zone.style().polish(self.zone)

    # Trzy metody nizej maja nazwy narzucone przez Qt (camelCase) — to
    # nadpisania `QWidget`, nie nasza konwencja.
    def dragEnterEvent(self, event) -> None:
        if _source_from(event.mimeData()) is None:
            event.ignore()
            return
        self._set_active(True)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event) -> None:
        self._set_active(False)
        source = _source_from(event.mimeData())
        if source is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self._choose(source)
