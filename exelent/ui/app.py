"""Okno główne: stos trzech ekranów, motyw i przełącznik języka.

Ekrany są tu pustymi `QWidget`. Zadania 18–20 podmieniają je na właściwe, nie
ruszając tej klasy — stos, tytuł i motyw są jej całą odpowiedzialnością.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget

from exelent.constants import APP_NAME
from exelent.i18n import set_language, system_language
from exelent.ui.theme import build_stylesheet, is_system_dark

SCREEN_DROP = 0
SCREEN_REVIEW = 1
SCREEN_BUILD = 2


class MainWindow(QMainWindow):
    language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(900, 620)
        self.setMinimumSize(760, 540)

        self.stack = QStackedWidget()
        for _ in range(3):
            self.stack.addWidget(QWidget())
        self.setCentralWidget(self.stack)

        set_language(system_language())
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
