"""Ekran 2 — co EXElent zrozumiał z katalogu.

Tu leży różnica między „działa" a „użytkownik utknął": każde zgadnięcie
jest widoczne przed pięciominutowym buildem i poprawialne jednym kliknięciem.

Ekran nie analizuje i nie buduje — dostaje `ProjectAnalysis`, pokazuje ją,
a to, co użytkownik poprawi, oddaje jako `BuildPlan`. Cała wiedza o tym, co
znaczą te dane, została w rdzeniu; tutaj jest wyłącznie ich prezentacja.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from exelent.i18n import describe, t
from exelent.models import AppKind, OutputMode, ProjectAnalysis, Severity
from exelent.planning import make_plan
from exelent.ui.rows import FactRow

COLLAPSED = "▸"
EXPANDED = "▾"


class ReviewScreen(QWidget):
    build_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._analysis: ProjectAnalysis | None = None
        self._icon: Path | None = None

        self.headline = QLabel(t("review_headline"), objectName="Title")

        self.entry_combo = QComboBox()
        self.kind_combo = QComboBox()
        self.kind_combo.addItem(t("kind_windowed"), AppKind.WINDOWED)
        self.kind_combo.addItem(t("kind_console"), AppKind.CONSOLE)
        self.name_edit = QLineEdit()
        self.icon_button = QPushButton(t("review_pick_icon"))
        self.icon_button.clicked.connect(self._pick_icon)

        self.row_entry = FactRow(t("review_entry"), self.entry_combo)
        self.row_kind = FactRow(t("review_kind"), self.kind_combo)
        self.row_name = FactRow(t("review_name"), self.name_edit)
        self.row_icon = FactRow(t("review_icon"), self.icon_button)

        card = QFrame(objectName="Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 18, 24, 18)
        for row in (self.row_entry, self.row_kind, self.row_name, self.row_icon):
            card_layout.addWidget(row)

        self.deps_box = QFrame(objectName="Card")
        deps_layout = QVBoxLayout(self.deps_box)
        deps_layout.setContentsMargins(24, 18, 24, 18)
        deps_layout.addWidget(QLabel(t("review_deps_title")))
        self.deps_label = QLabel("", objectName="Muted")
        self.deps_label.setWordWrap(True)
        deps_layout.addWidget(self.deps_label)
        self.deps_box.setVisible(False)

        self.warnings_label = QLabel("", objectName="Muted")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setVisible(False)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(t("mode_onefile"), OutputMode.ONEFILE)
        self.mode_combo.addItem(t("mode_onedir"), OutputMode.ONEDIR)
        self.advanced = QFrame(objectName="Card")
        advanced_layout = QHBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(24, 14, 24, 14)
        advanced_layout.addWidget(QLabel(t("review_mode")))
        advanced_layout.addWidget(self.mode_combo, stretch=1)
        self.advanced.setVisible(False)

        self.advanced_toggle = QPushButton(objectName="Link")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        self._advanced_open = False
        self._show_advanced(False)

        self.build_button = QPushButton(t("review_build"), objectName="Primary")
        self.build_button.clicked.connect(self._emit_plan)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 28)
        outer.setSpacing(16)
        outer.addWidget(self.headline)
        outer.addWidget(card)
        outer.addWidget(self.deps_box)
        outer.addWidget(self.warnings_label)
        outer.addWidget(self.advanced_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(self.advanced)
        outer.addStretch(1)
        outer.addWidget(self.build_button, alignment=Qt.AlignmentFlag.AlignRight)

    def load(self, analysis: ProjectAnalysis) -> None:
        """Pokazuje wynik analizy. Wołane też przy DRUGIM projekcie w tej samej
        sesji, więc każde pole jest ustawiane bezwarunkowo — pozostałość po
        poprzednim katalogu byłaby zdaniem o pliku, którego już nie ma."""
        self._analysis = analysis
        self._icon = analysis.suggested_icon

        self.entry_combo.clear()
        for candidate in analysis.entry_candidates:
            self.entry_combo.addItem(_label_for(analysis.root, candidate.path), candidate.path)
        # Pewność wymaga wartości. `entry_is_certain(())` to prawda w sensie
        # rdzenia („nie ma dwóch kandydatów remisujących"), ale wiersz jest
        # wtedy PUSTY, a `✓` przy pustym polu to fałszywa pewność — dokładnie
        # to, przeciwko czemu ten ekran istnieje.
        self.row_entry.set_certain(analysis.entry_certain and bool(analysis.entry_candidates))

        self.kind_combo.setCurrentIndex(max(self.kind_combo.findData(analysis.app_kind), 0))
        self.row_kind.set_certain(analysis.app_kind_certain)

        self.name_edit.setText(analysis.suggested_name)
        self.icon_button.setText(
            analysis.suggested_icon.name if analysis.suggested_icon else t("review_pick_icon")
        )

        packages = [d.package for d in analysis.dependencies if not d.optional]
        self.deps_label.setText(" · ".join(packages))
        self.deps_box.setVisible(bool(packages))

        self.mode_combo.setCurrentIndex(max(self.mode_combo.findData(analysis.output_mode), 0))

        warnings = [describe(i) for i in analysis.issues if i.severity is not Severity.INFO]
        self.warnings_label.setText("\n".join(warnings))
        self.warnings_label.setVisible(bool(warnings))

        blocked = any(i.severity is Severity.BLOCKER for i in analysis.issues)
        self.build_button.setEnabled(not blocked)

    def _show_advanced(self, visible: bool) -> None:
        self._advanced_open = visible
        self.advanced.setVisible(visible)
        arrow = EXPANDED if visible else COLLAPSED
        self.advanced_toggle.setText(f"{arrow} {t('review_advanced')}")

    def _toggle_advanced(self) -> None:
        """Stan panelu trzymany osobno, a nie odczytywany z `isVisible()`.

        `isVisible()` mówi o widoczności NA EKRANIE, więc dopóki okno nie jest
        pokazane, oddaje False także dla panelu, który właśnie odsłoniliśmy —
        przełącznik potrafiłby wtedy tylko otwierać.
        """
        self._show_advanced(not self._advanced_open)

    def _pick_icon(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, t("review_pick_icon"), "", t("review_icon_filter")
        )
        if chosen:
            self._icon = Path(chosen)
            self.icon_button.setText(self._icon.name)

    def _emit_plan(self) -> None:
        """Bez wczytanej analizy nie ma czego budować.

        Ekran powstaje razem z oknem, na długo przed wskazaniem folderu, więc
        ten stan jest prawdziwy — a nie teoretyczny.
        """
        if self._analysis is None:
            return
        plan = make_plan(
            self._analysis,
            entry=self.entry_combo.currentData(),
            exe_name=self.name_edit.text(),
            icon=self._icon,
            # Qt przechowuje dane pozycji jako QVariant i oddaje `AppKind`
            # z powrotem jako GOŁY napis. Rdzeń porównuje te pola przez `is`
            # (`plan.app_kind is AppKind.WINDOWED` w `pyinstaller.py`), więc
            # napis przechodzi cicho i daje program konsolowy tam, gdzie
            # użytkownik wybrał okno — czyli czarną konsolę za każdym GUI.
            # Typ odtwarzamy tu, na granicy z Qt.
            app_kind=AppKind(self.kind_combo.currentData()),
            output_mode=OutputMode(self.mode_combo.currentData()),
        )
        self.build_requested.emit(plan)


def _label_for(root: Path, path: Path) -> str:
    """Jak nazwać kandydata na liście.

    Sama nazwa pliku nie wystarcza: `main.py` w korzeniu i `pkg/main.py` dają
    dwie identyczne pozycje, więc użytkownik nie ma jak wybrać właściwej ani
    odczytać, która jest zaznaczona. Ścieżka względem katalogu projektu jest
    dla plików w korzeniu dokładnie tą samą nazwą, a głębiej mówi prawdę.
    """
    return path.relative_to(root).as_posix()
