"""Ekran 2 — co EXElent zrozumiał z katalogu.

Tu leży różnica między „działa" a „użytkownik utknął": każde zgadnięcie
jest widoczne przed pięciominutowym buildem i poprawialne jednym kliknięciem.

Ekran nie analizuje i nie buduje — dostaje `ProjectAnalysis`, pokazuje ją,
a to, co użytkownik poprawi, oddaje jako `BuildPlan`. Cała wiedza o tym, co
znaczą te dane, została w rdzeniu; tutaj jest wyłącznie ich prezentacja.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
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


def _mark_recommended(combo: QComboBox, index: int) -> None:
    """Dopisuje „(zalecane)" do etykiety pozycji, NIE ruszając jej danych.

    `setItemText` zmienia wyłącznie napis; `itemData` zostaje tym, czym było.
    To rozróżnienie jest jedyną rzeczą, która dzieli ten ekran od regresji, w
    której `currentData()` oddaje napis i program konsolowy udaje okienkowy.
    """
    if index < 0:
        return
    combo.setItemText(index, f"{combo.itemText(index)} {t('review_recommended_suffix')}")


class ReviewScreen(QWidget):
    build_requested = Signal(object)
    back_requested = Signal()

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

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(t("mode_onefile"), OutputMode.ONEFILE)
        self.mode_combo.addItem(t("mode_onedir"), OutputMode.ONEDIR)

        self.row_entry = FactRow(t("review_entry"), self.entry_combo)
        self.row_kind = FactRow(t("review_kind"), self.kind_combo)
        self.row_name = FactRow(t("review_name"), self.name_edit)
        self.row_icon = FactRow(t("review_icon"), self.icon_button)
        self.row_mode = FactRow(t("review_mode"), self.mode_combo)

        card = QFrame(objectName="Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 18, 24, 18)
        for row in (self.row_entry, self.row_kind, self.row_name, self.row_icon, self.row_mode):
            card_layout.addWidget(row)

        for row, combo in (
            (self.row_entry, self.entry_combo),
            (self.row_kind, self.kind_combo),
            (self.row_mode, self.mode_combo),
        ):
            row.restore_requested.connect(
                lambda _checked=False, r=row, c=combo: c.setCurrentIndex(
                    max(c.findText(r.recommended_text() or ""), 0)
                )
            )

        self.extra_label = QLabel("", objectName="Muted")
        self.extra_label.setWordWrap(True)
        self.extra_label.setVisible(False)

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

        self.back_button = QPushButton(t("review_back"), objectName="Link")
        self.back_button.clicked.connect(self.back_requested)

        self.build_button = QPushButton(t("review_build"), objectName="Primary")
        self.build_button.clicked.connect(self._emit_plan)

        actions = QHBoxLayout()
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(self.build_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 28)
        outer.setSpacing(16)
        outer.addWidget(self.headline)
        outer.addWidget(card)
        outer.addWidget(self.extra_label)
        outer.addWidget(self.deps_box)
        outer.addWidget(self.warnings_label)
        outer.addStretch(1)
        outer.addLayout(actions)

    def load(self, analysis: ProjectAnalysis) -> None:
        """Pokazuje wynik analizy. Wołane też przy DRUGIM projekcie w tej samej
        sesji, więc każde pole jest ustawiane bezwarunkowo — pozostałość po
        poprzednim katalogu byłaby zdaniem o pliku, którego już nie ma."""
        self._analysis = analysis
        self._icon = analysis.suggested_icon

        # Etykiety list o stalej zawartosci wracaja do postaci bazowej, bo
        # `_mark_recommended` DOPISUJE sufiks — drugi projekt w tej samej
        # sesji dostawalby "Program w oknie (zalecane) (zalecane)".
        self.kind_combo.setItemText(0, t("kind_windowed"))
        self.kind_combo.setItemText(1, t("kind_console"))
        self.mode_combo.setItemText(0, t("mode_onefile"))
        self.mode_combo.setItemText(1, t("mode_onedir"))

        self.entry_combo.clear()
        for candidate in analysis.entry_candidates:
            self.entry_combo.addItem(_label_for(analysis.root, candidate.path), candidate.path)
        _mark_recommended(self.entry_combo, 0)
        self.entry_combo.setCurrentIndex(0 if analysis.entry_candidates else -1)
        self.row_entry.set_recommended(self.entry_combo.currentText())
        # Pewność wymaga wartości. `entry_is_certain(())` to prawda w sensie
        # rdzenia („nie ma dwóch kandydatów remisujących"), ale wiersz jest
        # wtedy PUSTY, a `✓` przy pustym polu to fałszywa pewność — dokładnie
        # to, przeciwko czemu ten ekran istnieje.
        self.row_entry.set_certain(analysis.entry_certain and bool(analysis.entry_candidates))

        kind_index = max(self.kind_combo.findData(analysis.app_kind), 0)
        _mark_recommended(self.kind_combo, kind_index)
        self.kind_combo.setCurrentIndex(kind_index)
        self.row_kind.set_recommended(self.kind_combo.currentText())
        self.row_kind.set_certain(analysis.app_kind_certain)

        self.name_edit.setText(analysis.suggested_name)
        self.icon_button.setText(
            analysis.suggested_icon.name if analysis.suggested_icon else t("review_pick_icon")
        )

        extra = ", ".join(p.name for p in analysis.extra_sources)
        self.extra_label.setText(t("single_file_extra", files=extra) if extra else "")
        self.extra_label.setVisible(bool(extra))

        packages = [d.package for d in analysis.dependencies if not d.optional]
        self.deps_label.setText(" · ".join(packages))
        self.deps_box.setVisible(bool(packages))

        mode_index = max(self.mode_combo.findData(analysis.output_mode), 0)
        _mark_recommended(self.mode_combo, mode_index)
        self.mode_combo.setCurrentIndex(mode_index)
        self.row_mode.set_recommended(self.mode_combo.currentText())

        warnings = [describe(i) for i in analysis.issues if i.severity is not Severity.INFO]
        self.warnings_label.setText("\n".join(warnings))
        self.warnings_label.setVisible(bool(warnings))

        blocked = any(i.severity is Severity.BLOCKER for i in analysis.issues)
        self.build_button.setEnabled(not blocked)

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
