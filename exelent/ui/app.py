"""Okno główne: stos trzech ekranów, motyw i przełącznik języka.

Okno jest jedynym miejscem, które zna kolejność ekranów — same ekrany nie wiedzą
o sobie nawzajem i rozmawiają wyłącznie sygnałami. Tu też leży jedyny worker
budujący: ekran 3 pokazuje postęp, ale nie jest właścicielem wątku.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from exelent.analysis.project import analyze_project
from exelent.constants import APP_NAME
from exelent.i18n import set_language, system_language
from exelent.ui.preflight import PreflightWorker
from exelent.ui.screen_build import BuildScreen
from exelent.ui.screen_drop import DropScreen
from exelent.ui.screen_review import ReviewScreen
from exelent.ui.theme import build_stylesheet, is_system_dark
from exelent.ui.worker import BuildWorker

SCREEN_DROP = 0
SCREEN_REVIEW = 1
SCREEN_BUILD = 2


class MainWindow(QMainWindow):
    language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        # Język PIERWSZY, przed ekranami. Ekrany biorą swoje napisy z `t()` w
        # konstruktorze, więc ustawiony po nich zostawiał angielskiemu
        # użytkownikowi polskie okno: sprawdzone — nagłówek ekranu 1 zostawał
        # polski przy `current_language() == "en"`.
        set_language(system_language())
        self.setWindowTitle(APP_NAME)
        self.resize(900, 620)
        self.setMinimumSize(760, 540)

        self.screen_drop = DropScreen()
        self.screen_drop.folder_chosen.connect(self._on_folder_chosen)
        self.screen_review = ReviewScreen()
        self.screen_review.build_requested.connect(self._on_build_requested)
        self.screen_review.back_requested.connect(self._on_back_to_drop)
        self.screen_build = BuildScreen()
        self.screen_build.restart_requested.connect(self._on_restart)
        self.screen_build.back_to_review.connect(self._on_back_to_review)

        # JEDEN worker na całe życie okna, podpięty RAZ. Worker tworzony przy
        # każdym buildzie dokładałby kolejne połączenie do „Przerwij" (po trzech
        # buildach przycisk anulowałby trzy workery naraz) i zostawiał po sobie
        # obiekty wątków. Worker umie zacząć od nowa, bo token anulowania
        # powstaje w `start`, a nie w konstruktorze.
        self.worker = BuildWorker()
        self.worker.progress.connect(self.screen_build.on_progress)
        self.worker.finished.connect(self.screen_build.on_finished)
        self.screen_build.cancel_button.clicked.connect(self.worker.cancel)

        # Rozmiar pobierania liczy sie w tle ekranu 2. Nigdy nie blokuje
        # budowania: pusty wynik znaczy tylko tyle, ze liczba sie nie policzyla.
        self.preflight = PreflightWorker()
        self.preflight.finished.connect(self.screen_review.show_download_plan)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.screen_drop)
        self.stack.addWidget(self.screen_review)
        self.stack.addWidget(self.screen_build)
        self.setCentralWidget(self.stack)

        self.setStyleSheet(build_stylesheet(is_system_dark()))

    def go_to(self, index: int) -> None:
        """Zmienia ekran.

        Bez własnego sprawdzania zakresu: `QStackedWidget` sam ignoruje indeks
        spoza zakresu — sprawdzone dla 99, -1 i -5, stos nigdy nie zostaje bez
        ekranu. Własny `if` byłby gałęzią, której żaden test nie umie zgasić
        (mutant kasujący go przechodził), a właściwości pilnuje test na
        obserwowalnym zachowaniu.
        """
        self.stack.setCurrentIndex(index)

    def _on_folder_chosen(self, folder: Path) -> None:
        """Analiza i przejście na ekran 2.

        Analiza czyta AST plików z dysku, nie sieć, a skan ma twarde limity
        (`MAX_SCAN_FILES`/`MAX_SCAN_BYTES`), więc mieści się w wątku głównym.
        Katalog, którego nie da się przeczytać, nie jest awarią: analiza wraca
        wtedy z blokadą, którą ekran 2 pokazuje zdaniem.
        """
        analysis = analyze_project(folder)
        self.screen_review.load(analysis)
        self.preflight.start([d.package for d in analysis.dependencies if not d.optional])
        self.go_to(SCREEN_REVIEW)

    def _on_build_requested(self, plan) -> None:
        """Ekran 3 czyszczony PRZED pokazaniem, build startuje po przejściu."""
        self.screen_build.start(plan)
        self.go_to(SCREEN_BUILD)
        self.worker.start(plan)

    def _on_back_to_drop(self) -> None:
        """Powrót na start bez budowania.

        Lista ostatnich jest odświeżana, bo projekt wybrany przed chwilą już do
        niej trafił (`DropScreen._choose` woła `recent.remember` przed emisją),
        a ekran 1 czytał ją ostatnio przy uruchamianiu programu.
        """
        if self.worker.is_running():
            return
        self.preflight.stop()
        self.screen_drop.refresh_recent()
        self.go_to(SCREEN_DROP)

    def _on_back_to_review(self) -> None:
        """Powrót na ekran 2 z ZACHOWANĄ analizą.

        Ekran 2 jest widgetem długożyjącym i trzyma ostatnią `ProjectAnalysis`
        w swoim polu, więc poprawienie nazwy po nieudanym buildzie nie kosztuje
        ponownego skanu katalogu.

        Blokada przy trwającym buildzie nie jest ostrożnością na wyrost:
        `BuildWorker.start` odrzuca drugi build po cichu, więc użytkownik
        dostałby ekran postępu, który nigdy nie ruszy.
        """
        if self.worker.is_running():
            return
        self.go_to(SCREEN_REVIEW)

    def _on_restart(self) -> None:
        """Powrót na start. Lista ostatnich projektów jest odświeżana, bo
        właśnie doszedł do niej projekt zbudowany przed chwilą — ekran 1 czytał
        ją ostatnio przy uruchamianiu programu."""
        if self.worker.is_running():
            return
        self.screen_drop.refresh_recent()
        self.go_to(SCREEN_DROP)

    def closeEvent(self, event) -> None:
        """Zamknięcie okna w trakcie budowania.

        Bez tego Qt niszczy działający `QThread` przy wychodzeniu (abort), a
        proces PyInstallera zostaje w systemie jako sierota trzymająca pliki
        otwarte — dokładnie to, przed czym broni się `_kill_tree`. Nazwa metody
        jest narzucona przez Qt (camelCase), to nadpisanie `QWidget`.
        """
        self.preflight.stop()
        self.worker.shutdown()
        super().closeEvent(event)

    def set_language(self, lang: str) -> None:
        set_language(lang)
        self.language_changed.emit(lang)


def run_gui(argv: list[str]) -> int:
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui(sys.argv))
