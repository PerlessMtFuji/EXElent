"""Ekran 3 — postęp budowania i wynik.

Cztery stany w jednym widgecie: trwa, udało się, nie udało się, przerwane.
Rozdzielenie przerwania od awarii nie jest kosmetyką: użytkownik, który sam
nacisnął „Anuluj", nie ma być proszony o zgłoszenie własnej decyzji jako błędu.

Ostrzeżenie o antywirusach pokazujemy zawsze po sukcesie — użytkownik i tak je
spotka, lepiej żeby usłyszał od nas.
"""

from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from exelent.diagnostics.report import github_issue_url, tail, write_report
from exelent.i18n import describe, t
from exelent.models import BuildPlan, BuildResult
from exelent.ui.format import human_duration, human_size, human_speed

# Ile ostatnich linii logu pokazujemy w oknie. Log PyInstallera bywa
# wielomegabajtowy, a interesujący jest zawsze jego koniec.
LOG_TAIL_LINES = 200

# Issue, które nie jest awarią, tylko decyzją użytkownika.
CANCELLED = "build_cancelled"


class BuildScreen(QWidget):
    restart_requested = Signal()
    back_to_review = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._result: BuildResult | None = None
        self._plan: BuildPlan | None = None
        self._log_open = False
        # Klucz zdania, ktore stoi w naglowku. Sam napis nie wystarczy: po
        # zmianie jezyka trzeba go zlozyc od nowa, a `t()` nie umie czytac
        # w druga strone.
        self._phase_key = "build_start"

        self.phase_label = QLabel(t("build_start"), objectName="Title")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bytes_label = QLabel("", objectName="Muted")
        self.bytes_label.setVisible(False)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.antivirus_label = QLabel(t("antivirus_note"), objectName="Muted")
        self.antivirus_label.setWordWrap(True)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_toggle = QPushButton(t("build_show_log"), objectName="Link")
        self.log_toggle.clicked.connect(self._toggle_log)

        self.cancel_button = QPushButton(t("build_cancel"))
        self.open_folder_button = QPushButton(t("build_open_folder"))
        self.run_button = QPushButton(t("build_run"))
        self.report_button = QPushButton(t("build_save_report"))
        self.github_button = QPushButton(t("build_report_github"))
        self.back_button = QPushButton(t("build_back_to_review"))
        self.again_button = QPushButton(t("build_again"), objectName="Primary")

        self.again_button.clicked.connect(self.restart_requested)
        self.back_button.clicked.connect(self.back_to_review)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.run_button.clicked.connect(self._run_artifact)
        self.report_button.clicked.connect(self._save_report)
        self.github_button.clicked.connect(self._open_github)

        actions = QHBoxLayout()
        for button in (
            self.back_button,
            self.cancel_button,
            self.open_folder_button,
            self.run_button,
            self.report_button,
            self.github_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.again_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 28)
        outer.setSpacing(16)
        outer.addWidget(self.phase_label)
        outer.addWidget(self.bar)
        outer.addWidget(self.bytes_label)
        outer.addWidget(self.summary_label)
        outer.addWidget(self.antivirus_label)
        outer.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(self.log_view, stretch=1)
        outer.addStretch(1)
        outer.addLayout(actions)

        self._show_running()

    # --- stany ---

    def _hide_all_actions(self) -> None:
        """Czysty punkt wyjścia dla każdego stanu.

        Stan ma określać CAŁY ekran, a nie dokładać się do poprzedniego:
        bez tego przejście z porażki w przerwanie zostawiało na ekranie
        „Zgłoś na GitHubie" z tamtej porażki — zmierzone na renderze.

        Licznik megabajtów gaśnie tu razem z przyciskami: build przerwany w
        połowie pobierania zostawiłby pod zdaniem o awarii licznik, który
        nadal odlicza.
        """
        self.antivirus_label.setVisible(False)
        self.bytes_label.setVisible(False)
        for button in (
            self.cancel_button,
            self.open_folder_button,
            self.run_button,
            self.report_button,
            self.github_button,
            self.back_button,
            self.again_button,
        ):
            button.setVisible(False)

    def retranslate(self) -> None:
        """Przepisuje napisy po zmianie języka.

        Ekrany biorą teksty z `t()` w konstruktorze, więc bez tej metody
        przełącznik języka działałby dopiero po restarcie programu.

        Gdy build się już skończył, cały ekran składamy od nowa z wyniku:
        zdania w podsumowaniu pochodzą z `describe()` i inaczej zostałyby w
        poprzednim języku.
        """
        self.antivirus_label.setText(t("antivirus_note"))
        self.cancel_button.setText(t("build_cancel"))
        self.open_folder_button.setText(t("build_open_folder"))
        self.run_button.setText(t("build_run"))
        self.report_button.setText(t("build_save_report"))
        self.github_button.setText(t("build_report_github"))
        self.back_button.setText(t("build_back_to_review"))
        self.again_button.setText(t("build_again"))
        self._show_log(self._log_open)
        if self._result is not None:
            self.on_finished(self._result)
            return
        self.phase_label.setText(t(self._phase_key))

    def _set_phase(self, key: str) -> None:
        self._phase_key = key
        self.phase_label.setText(t(key))

    def _show_running(self) -> None:
        self._set_phase("build_start")
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.summary_label.setText("")
        self.log_view.setPlainText("")
        self._show_log(False)
        self.log_toggle.setVisible(False)
        self._hide_all_actions()
        self.cancel_button.setVisible(True)

    def start(self, plan: BuildPlan) -> None:
        """Nowy build zaczyna się od czystego ekranu.

        Bez tego drugi build biegnie z paskiem postępu i JEDNOCZEŚNIE ze
        zdaniem o awarii poprzedniego, przyciskiem „Zapisz raport" i logiem
        sprzed chwili — czyli pokazuje dwa różne budowania naraz.
        """
        self._plan = plan
        self._result = None
        self._show_running()

    def on_progress(self, update) -> None:
        self._set_phase(update.phase)
        self.bar.setValue(int(update.fraction * 100))
        self._show_bytes(update)

    def _show_bytes(self, update) -> None:
        """Druga linijka tylko wtedy, gdy naprawdę coś się pobiera.

        Pusty licznik megabajtów pod paskiem przy pakowaniu byłby gorszy niż
        jego brak, więc ekran poznaje to po `total_bytes == 0`.
        """
        if not update.total_bytes:
            self.bytes_label.setVisible(False)
            return
        parts = [
            t(
                "progress_bytes",
                done=human_size(update.done_bytes),
                total=human_size(update.total_bytes),
            )
        ]
        if update.speed_bps > 0:
            parts.append(human_speed(update.speed_bps))
        if update.eta_s is not None:
            parts.append(t("progress_eta", eta=human_duration(update.eta_s)))
        self.bytes_label.setText(" · ".join(parts))
        self.bytes_label.setVisible(True)

    def on_finished(self, result: BuildResult) -> None:
        self._result = result
        self._hide_all_actions()
        self.again_button.setVisible(True)
        self._load_log(result)

        if result.ok and result.artifact:
            self._show_success(result)
            return
        if any(issue.code == CANCELLED for issue in result.issues):
            self._show_cancelled(result)
            return
        self._show_failure(result)

    def _show_success(self, result: BuildResult) -> None:
        self.bar.setValue(100)
        self._set_phase("done")
        self.summary_label.setText(
            t(
                "build_success",
                name=result.artifact.name,
                size=human_size(result.size_bytes),
            )
        )
        self.antivirus_label.setVisible(True)
        self.open_folder_button.setVisible(True)
        self.run_button.setVisible(True)

    def _show_cancelled(self, result: BuildResult) -> None:
        """Przerwanie to nie awaria — bez raportu i bez zgłoszenia.

        Zdanie o samym przerwaniu jest nagłówkiem, a nie powtórzeniem w
        podsumowaniu; zostaje tam tylko to, czego użytkownik jeszcze nie wie —
        na przykład ostrzeżenie, że po anulowaniu coś mogło zostać uruchomione.
        """
        self.bar.setVisible(False)
        self._set_phase(CANCELLED)
        self.summary_label.setText(
            "\n".join(describe(i) for i in result.issues if i.code != CANCELLED)
        )
        self.back_button.setVisible(True)

    def _show_failure(self, result: BuildResult) -> None:
        """Diagnozy tu NIE robimy.

        `run_build` przepuszcza cały log przez `explain_log` i to, co
        rozpoznał, leży już w `result.issues`. Powtarzanie tego na ogonie logu
        (jak chciał plan) mogło znaleźć wyłącznie podzbiór tego samego, za to
        przenosiło wiedzę diagnostyczną do warstwy prezentacji.
        """
        self.bar.setVisible(False)
        self._set_phase("build_failed_title")
        self.summary_label.setText(
            "\n".join(describe(i) for i in result.issues) or t("build_failed_unknown")
        )
        self.report_button.setVisible(True)
        self.github_button.setVisible(True)
        self.back_button.setVisible(True)

    # --- log ---

    def _load_log(self, result: BuildResult) -> None:
        text = ""
        if result.log_path:
            try:
                text = tail(
                    result.log_path.read_text(encoding="utf-8", errors="replace"),
                    LOG_TAIL_LINES,
                )
            except OSError:
                # Ścieżka logu przychodzi z rdzenia, ale plik może już nie
                # istnieć: build żyje w katalogu tymczasowym, który system
                # sprząta. Brak logu nie jest powodem, żeby stracić wynik.
                text = ""
        self.log_view.setPlainText(text)
        # Kursor na koniec: log czyta się od końca, bo tam jest to, co
        # przerwało build. Otwarty na pierwszej linii kazałby użytkownikowi
        # przewinąć dwieście linii, zanim zobaczy powód.
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_toggle.setVisible(bool(text))

    def _show_log(self, visible: bool) -> None:
        self._log_open = visible
        self.log_view.setVisible(visible)
        self.log_toggle.setText(t("build_hide_log") if visible else t("build_show_log"))

    def _toggle_log(self) -> None:
        # Stan trzymany osobno, a nie czytany z `isVisible()`: to ostatnie mówi
        # o widoczności NA EKRANIE, więc dopóki okno nie jest pokazane, oddaje
        # False także dla widgetu, który właśnie odsłoniliśmy.
        self._show_log(not self._log_open)

    # --- akcje ---

    def _open_folder(self) -> None:
        """„Pokaż w folderze" ma POKAZAĆ plik, nie tylko otworzyć katalog.

        Katalog wynikowy potrafi mieć kilkaset pozycji (ONEDIR), więc samo
        otwarcie okna zostawia użytkownika ze szukaniem. `/select` otwiera
        Eksploratora z zaznaczonym plikiem. Przy ONEDIR artefaktem jest sam
        katalog i wtedy otwieramy go wprost.
        """
        artifact = self._result.artifact if self._result else None
        if artifact is None:
            return
        arguments = (
            ["explorer", f"/select,{artifact}"]
            if artifact.is_file()
            else ["explorer", str(artifact)]
        )
        subprocess.run(arguments, check=False)

    def _run_artifact(self) -> None:
        artifact = self._result.artifact if self._result else None
        if artifact is not None and artifact.is_file():
            subprocess.Popen([str(artifact)], cwd=str(artifact.parent))

    def _plan_summary(self) -> str:
        """Kontekst zgłoszenia. Nazwa PROJEKTU, nie artefaktu.

        Raport powstaje wyłącznie po nieudanym buildzie, a wtedy artefaktu z
        definicji nie ma — wersja z planu opisywała więc każde zgłoszenie
        słowem „build".
        """
        plan = self._plan
        if plan is None:
            return "build"
        return (
            f"{plan.exe_name} ({plan.entry.name}, {plan.app_kind.value}, {plan.output_mode.value})"
        )

    def _log_text(self) -> str:
        if self._result and self._result.log_path:
            try:
                return self._result.log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        return self.summary_label.text()

    def _save_report(self) -> None:
        chosen, _filter = QFileDialog.getSaveFileName(
            self, t("build_save_report"), "EXElent-raport.txt", t("build_report_filter")
        )
        if chosen:
            write_report(self._log_text(), Path(chosen), self._plan_summary())

    def _open_github(self) -> None:
        webbrowser.open(github_issue_url(self._log_text(), self._plan_summary()))
