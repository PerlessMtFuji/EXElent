"""Ekran 2 — co EXElent zrozumiał z katalogu.

Tu leży różnica między „działa" a „użytkownik utknął": każde zgadnięcie
jest widoczne przed pięciominutowym buildem i poprawialne jednym kliknięciem.

Ekran nie analizuje i nie buduje — dostaje `ProjectAnalysis`, pokazuje ją,
a to, co użytkownik poprawi, oddaje jako `BuildPlan`. Cała wiedza o tym, co
znaczą te dane, została w rdzeniu; tutaj jest wyłącznie ich prezentacja.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from exelent.analysis.textconv import decode_bytes
from exelent.constants import TARGET_PYTHON
from exelent.deps.sizes import estimate_exe_size
from exelent.i18n import describe, t
from exelent.models import AppKind, Issue, OutputMode, ProjectAnalysis, Severity
from exelent.planning import default_dest_dir, make_plan, onefile_limitation_issues
from exelent.ui.format import human_size
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


class TextPreviewDialog(QDialog):
    """Oryginał, wynik i rzeczywista różnica jednej konwersji TXT."""

    def __init__(self, name: str, original: str, converted: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("review_preview_title", file=name))
        self.resize(820, 620)

        self.tabs = QTabWidget()
        self.original_view = self._view(original)
        self.result_view = self._view(converted)
        diff = "\n".join(
            difflib.unified_diff(
                original.splitlines(),
                converted.splitlines(),
                fromfile=name,
                tofile=str(Path(name).with_suffix(".py")),
                lineterm="",
            )
        )
        self.diff_view = self._view(diff)
        self.tabs.addTab(self.original_view, t("review_preview_original"))
        self.tabs.addTab(self.result_view, t("review_preview_result"))
        self.tabs.addTab(self.diff_view, t("review_preview_diff"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    @staticmethod
    def _view(text: str) -> QPlainTextEdit:
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        return view


class ReviewScreen(QWidget):
    build_requested = Signal(object)
    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._analysis: ProjectAnalysis | None = None
        self._icon: Path | None = None
        self._dest_dir: Path | None = None
        self._custom_dest = False
        # Ostatni wynik preflightu. Trzymany, bo `retranslate` przechodzi przez
        # `load`, a ono zaczyna od „sprawdzam rozmiar…" — bez tego zmiana
        # języka kasowałaby policzoną liczbę, której nikt już nie policzy.
        self._download_plan = None

        self.headline = QLabel(t("review_headline"), objectName="Title")

        self.entry_combo = QComboBox()
        self.kind_combo = QComboBox()
        self.kind_combo.addItem(t("kind_windowed"), AppKind.WINDOWED)
        self.kind_combo.addItem(t("kind_console"), AppKind.CONSOLE)
        self.name_edit = QLineEdit()
        self.icon_button = QPushButton(t("review_pick_icon"))
        self.icon_button.clicked.connect(self._pick_icon)
        self.target_label = QLabel(TARGET_PYTHON)
        self.destination_label = QLabel("")
        self.destination_label.setWordWrap(True)
        self.destination_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.destination_button = QPushButton(t("review_destination_change"))
        self.destination_button.setObjectName("Link")
        self.destination_button.clicked.connect(self._pick_destination)
        destination_widget = QWidget()
        destination_layout = QVBoxLayout(destination_widget)
        destination_layout.setContentsMargins(0, 0, 0, 0)
        destination_layout.setSpacing(6)
        destination_layout.addWidget(self.destination_label)
        destination_layout.addWidget(self.destination_button)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(t("mode_onefile"), OutputMode.ONEFILE)
        self.mode_combo.addItem(t("mode_onedir"), OutputMode.ONEDIR)
        # Reczny wybor ONEFILE niesie widoczne ograniczenie (B01). Ostrzezenia
        # sa wiec przeliczane przy KAZDEJ zmianie trybu, nie tylko przy `load`.
        self.mode_combo.currentIndexChanged.connect(lambda *_: self._update_issue_labels())

        self.row_entry = FactRow(t("review_entry"), self.entry_combo)
        self.row_kind = FactRow(t("review_kind"), self.kind_combo)
        self.row_name = FactRow(t("review_name"), self.name_edit)
        self.row_icon = FactRow(t("review_icon"), self.icon_button)
        self.row_mode = FactRow(t("review_mode"), self.mode_combo)
        self.row_target = FactRow(t("review_target"), self.target_label)
        self.row_destination = FactRow(t("review_destination"), destination_widget)

        card = QFrame(objectName="Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 18, 24, 18)
        for row in (
            self.row_entry,
            self.row_kind,
            self.row_name,
            self.row_icon,
            self.row_mode,
            self.row_target,
            self.row_destination,
        ):
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
        self.deps_title_label = QLabel(t("review_deps_title"))
        deps_layout.addWidget(self.deps_title_label)
        self.deps_label = QLabel("", objectName="Muted")
        self.deps_label.setWordWrap(True)
        deps_layout.addWidget(self.deps_label)
        self.deps_size_label = QLabel("", objectName="Muted")
        self.deps_size_label.setWordWrap(True)
        deps_layout.addWidget(self.deps_size_label)
        self.deps_box.setVisible(False)

        # Ręczne dopisanie modułów, których statyczny skan nie widzi (import
        # dynamiczny, wtyczka). Zawsze widoczne, niezależnie od `deps_box`:
        # projekt bez wykrytych zależności też może potrzebować tego pola.
        self.extra_box = QFrame(objectName="Card")
        extra_layout = QVBoxLayout(self.extra_box)
        extra_layout.setContentsMargins(24, 18, 24, 18)
        self.extra_title_label = QLabel(t("review_extra_modules"))
        extra_layout.addWidget(self.extra_title_label)
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText(t("review_extra_modules_placeholder"))
        extra_layout.addWidget(self.extra_edit)
        self.extra_help_label = QLabel(t("review_extra_modules_help"), objectName="Muted")
        self.extra_help_label.setWordWrap(True)
        extra_layout.addWidget(self.extra_help_label)

        self.warnings_label = QLabel("", objectName="Muted")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setVisible(False)

        # Informacja ma WŁASNĄ etykietę, a nie miejsce w ostrzeżeniach:
        # zdanie „program zajmie 26–45 MB" nie jest ostrzeżeniem i nie ma
        # wyglądać jak ostrzeżenie.
        self.notes_label = QLabel("", objectName="Muted")
        self.notes_label.setWordWrap(True)
        self.notes_label.setVisible(False)

        self.scope_box = QFrame(objectName="Card")
        scope_layout = QVBoxLayout(self.scope_box)
        scope_layout.setContentsMargins(24, 18, 24, 18)
        self.scope_title_label = QLabel(t("review_scope_title"))
        self.scope_source_label = QLabel("", objectName="Muted")
        self.scope_source_label.setWordWrap(True)
        self.scope_summary_label = QLabel("", objectName="Muted")
        self.scope_summary_label.setWordWrap(True)
        scope_layout.addWidget(self.scope_title_label)
        scope_layout.addWidget(self.scope_source_label)
        scope_layout.addWidget(self.scope_summary_label)

        self.preview_box = QFrame(objectName="Card")
        preview_layout = QHBoxLayout(self.preview_box)
        preview_layout.setContentsMargins(24, 18, 24, 18)
        self.preview_combo = QComboBox()
        self.preview_button = QPushButton(t("review_preview_button"))
        self.preview_button.clicked.connect(self._show_text_preview)
        preview_layout.addWidget(self.preview_combo, 1)
        preview_layout.addWidget(self.preview_button)
        self.preview_box.setVisible(False)

        self.trust_label = QLabel(t("review_trust_warning"), objectName="Muted")
        self.trust_label.setWordWrap(True)

        self.back_button = QPushButton(t("review_back"), objectName="Link")
        self.back_button.clicked.connect(self.back_requested)

        self.build_button = QPushButton(t("review_build"), objectName="Primary")
        self.build_button.clicked.connect(self._emit_plan)

        actions = QHBoxLayout()
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(self.build_button)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(16)
        body_layout.addWidget(card)
        body_layout.addWidget(self.scope_box)
        body_layout.addWidget(self.preview_box)
        body_layout.addWidget(self.extra_label)
        body_layout.addWidget(self.deps_box)
        body_layout.addWidget(self.extra_box)
        body_layout.addWidget(self.warnings_label)
        body_layout.addWidget(self.notes_label)
        body_layout.addWidget(self.trust_label)
        body_layout.addStretch(1)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 28)
        outer.setSpacing(16)
        outer.addWidget(self.headline)
        outer.addWidget(self.scroll_area, 1)
        outer.addLayout(actions)

        self.setTabOrder(self.entry_combo, self.kind_combo)
        self.setTabOrder(self.kind_combo, self.name_edit)
        self.setTabOrder(self.name_edit, self.icon_button)
        self.setTabOrder(self.icon_button, self.mode_combo)
        self.setTabOrder(self.mode_combo, self.destination_button)
        self.setTabOrder(self.destination_button, self.preview_combo)
        self.setTabOrder(self.preview_combo, self.preview_button)
        self.setTabOrder(self.preview_button, self.extra_edit)
        self.setTabOrder(self.extra_edit, self.back_button)
        self.setTabOrder(self.back_button, self.build_button)
        self._update_accessible_names()

    def load(self, analysis: ProjectAnalysis) -> None:
        """Pokazuje wynik analizy. Wołane też przy DRUGIM projekcie w tej samej
        sesji, więc każde pole jest ustawiane bezwarunkowo — pozostałość po
        poprzednim katalogu byłaby zdaniem o pliku, którego już nie ma."""
        self._analysis = analysis
        self._icon = analysis.suggested_icon
        self._custom_dest = False
        self._dest_dir = None

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
        self._refresh_default_destination()
        self.icon_button.setText(
            analysis.suggested_icon.name if analysis.suggested_icon else t("review_pick_icon")
        )

        extra = ", ".join(p.name for p in analysis.extra_sources)
        self.extra_label.setText(t("single_file_extra", files=extra) if extra else "")
        self.extra_label.setVisible(bool(extra))

        packages = [d.package for d in analysis.dependencies if not d.optional]
        self.deps_label.setText(" · ".join(packages))
        self.deps_box.setVisible(bool(packages))
        self.deps_size_label.setText(t("download_checking") if packages else "")

        # Bezwarunkowo, jak każde pole: moduł dopisany dla poprzedniego projektu
        # nie może przeciec do następnego builda.
        self.extra_edit.clear()

        source = analysis.single_file or analysis.root
        self.scope_source_label.setText(t("review_scope_source", path=str(source)))
        source_count = len(analysis.scan.py_files) + len(analysis.converted)
        self.scope_summary_label.setText(
            t(
                "review_scope_summary",
                sources=str(source_count),
                conversions=str(len(analysis.converted)),
                resources=str(len(analysis.scan.data_files)),
                dependencies=str(len(packages)),
            )
        )
        self.preview_combo.clear()
        for rel_path in analysis.converted:
            self.preview_combo.addItem(str(Path(rel_path).with_suffix(".txt")), rel_path)
        self.preview_box.setVisible(bool(analysis.converted))

        mode_index = max(self.mode_combo.findData(analysis.output_mode), 0)
        _mark_recommended(self.mode_combo, mode_index)
        self.mode_combo.setCurrentIndex(mode_index)
        self.row_mode.set_recommended(self.mode_combo.currentText())

        self._update_issue_labels()

    def _mode_issues(self) -> tuple[Issue, ...]:
        """Ostrzezenia wynikajace z AKTUALNIE wybranego trybu wyjscia (B01).

        Qt oddaje dane pozycji jako goly napis, wiec tryb odtwarzamy przez
        `OutputMode(...)` — tak samo jak `_emit_plan`, zeby porownanie `is` w
        rdzeniu widzialo enum, a nie string."""
        data = self.mode_combo.currentData()
        if data is None:
            return ()
        return onefile_limitation_issues(OutputMode(data))

    def _update_issue_labels(self) -> None:
        """Sklada ostrzezenia i notatki z analizy ORAZ z wyboru trybu.

        Wolane z `load` i przy kazdej zmianie trybu, wiec przelaczenie na
        „Jeden plik EXE" natychmiast pokazuje jego ograniczenie, a powrot na
        „Folder z programem" je chowa."""
        if self._analysis is None:
            return
        issues = (*self._analysis.issues, *self._mode_issues())
        warnings = [describe(i) for i in issues if i.severity is not Severity.INFO]
        notes = [describe(i) for i in issues if i.severity is Severity.INFO]
        self.warnings_label.setText("\n".join(warnings))
        self.warnings_label.setVisible(bool(warnings))
        self.notes_label.setText("\n".join(notes))
        self.notes_label.setVisible(bool(notes))

        blocked = any(i.severity is Severity.BLOCKER for i in issues)
        self.build_button.setEnabled(not blocked)

    def retranslate(self) -> None:
        """Przepisuje napisy po zmianie języka.

        Ekrany biorą teksty z `t()` w konstruktorze, więc bez tej metody
        przełącznik języka działałby dopiero po restarcie programu.

        Po podpisach idzie ponowne `load`: pozycje list, dopiski „(zalecane)"
        i zdania z `describe()` też są tekstem, a jedynym miejscem, które umie
        je złożyć, jest `load`.
        """
        self.headline.setText(t("review_headline"))
        self.deps_title_label.setText(t("review_deps_title"))
        self.extra_title_label.setText(t("review_extra_modules"))
        self.extra_edit.setPlaceholderText(t("review_extra_modules_placeholder"))
        self.extra_help_label.setText(t("review_extra_modules_help"))
        self.scope_title_label.setText(t("review_scope_title"))
        self.preview_button.setText(t("review_preview_button"))
        self.destination_button.setText(t("review_destination_change"))
        self.trust_label.setText(t("review_trust_warning"))
        self.back_button.setText(t("review_back"))
        self.build_button.setText(t("review_build"))
        for row, key in (
            (self.row_entry, "review_entry"),
            (self.row_kind, "review_kind"),
            (self.row_name, "review_name"),
            (self.row_icon, "review_icon"),
            (self.row_mode, "review_mode"),
            (self.row_target, "review_target"),
            (self.row_destination, "review_destination"),
        ):
            row.retranslate(t(key))
        self._update_accessible_names()

        if self._analysis is None:
            self.kind_combo.setItemText(0, t("kind_windowed"))
            self.kind_combo.setItemText(1, t("kind_console"))
            self.mode_combo.setItemText(0, t("mode_onefile"))
            self.mode_combo.setItemText(1, t("mode_onedir"))
            self.icon_button.setText(t("review_pick_icon"))
            return

        chosen_entry = self.entry_combo.currentData()
        chosen_kind = self.kind_combo.currentData()
        chosen_mode = self.mode_combo.currentData()
        chosen_name = self.name_edit.text()
        chosen_icon = self._icon
        chosen_extra = self.extra_edit.text()
        chosen_dest = self._dest_dir
        custom_dest = self._custom_dest
        chosen_preview = self.preview_combo.currentData()

        self.load(self._analysis)
        self.entry_combo.setCurrentIndex(max(self.entry_combo.findData(chosen_entry), 0))
        self.kind_combo.setCurrentIndex(max(self.kind_combo.findData(chosen_kind), 0))
        self.mode_combo.setCurrentIndex(max(self.mode_combo.findData(chosen_mode), 0))
        self.name_edit.setText(chosen_name)
        self._icon = chosen_icon
        self.icon_button.setText(chosen_icon.name if chosen_icon else t("review_pick_icon"))
        self.extra_edit.setText(chosen_extra)
        self._dest_dir = chosen_dest
        self._custom_dest = custom_dest
        if chosen_dest is not None:
            self.destination_label.setText(str(chosen_dest))
        self.preview_combo.setCurrentIndex(max(self.preview_combo.findData(chosen_preview), 0))
        self._update_issue_labels()
        if self._download_plan is not None:
            self.show_download_plan(self._download_plan)

    def show_download_plan(self, plan) -> None:
        """B12: trzy osobne wielkości i jawne składniki przygotowania."""
        self._download_plan = plan
        if plan.status == "pending":
            self.deps_size_label.setText(t("download_checking"))
            return

        packages = (
            [d.package for d in self._analysis.dependencies if not d.optional]
            if self._analysis is not None
            else []
        )
        low, high, _heaviest = estimate_exe_size(packages)
        lines: list[str] = []

        if plan.status == "complete":
            if plan.would_download:
                lines.append(
                    t(
                        "download_transfer",
                        count=str(plan.would_download),
                        size=human_size(plan.total_bytes),
                    )
                )
            else:
                lines.append(t("download_transfer_cached"))
        else:
            lines.append(t("download_transfer_unknown"))

        if plan.environment_min_bytes:
            lines.append(t("download_environment_min", size=human_size(plan.environment_min_bytes)))
        else:
            lines.append(t("download_environment_unknown"))

        if high:
            lines.append(t("download_artifact_estimate", low=str(low), high=str(high)))
        else:
            lines.append(t("download_artifact_unknown"))

        components: list[str] = []
        if plan.uv_cached is True:
            components.append(t("download_component_uv_cached"))
        elif plan.uv_cached is False:
            components.append(t("download_component_uv_missing"))
        if plan.python_cached is True:
            components.append(t("download_component_python_cached"))
        elif plan.python_cached is False:
            components.append(t("download_component_python_missing"))
        if plan.includes_build_tools:
            components.append(t("download_component_tools"))
        if components:
            lines.append(t("download_components", components=", ".join(components)))

        self.deps_size_label.setText("\n".join(lines))
        self.deps_box.setVisible(bool(lines))

    def _pick_icon(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, t("review_pick_icon"), "", t("review_icon_filter")
        )
        if chosen:
            icon = Path(chosen)
            self._icon = icon
            self.icon_button.setText(icon.name)

    def _refresh_default_destination(self) -> None:
        if self._analysis is None or self._custom_dest:
            return
        destination = default_dest_dir(self._analysis.root, self.name_edit.text())
        self._dest_dir = destination
        self.destination_label.setText(str(destination))

    def _pick_destination(self) -> None:
        start = str(self._dest_dir or (self._analysis.root if self._analysis else Path.cwd()))
        chosen = QFileDialog.getExistingDirectory(self, t("review_destination_pick"), start)
        if chosen:
            self._dest_dir = Path(chosen)
            self._custom_dest = True
            self.destination_label.setText(chosen)

    def _update_accessible_names(self) -> None:
        """Nadaje kontrolkom przetłumaczone nazwy dla czytników ekranu."""
        for control, key in (
            (self.entry_combo, "review_entry"),
            (self.kind_combo, "review_kind"),
            (self.name_edit, "review_name"),
            (self.icon_button, "review_icon"),
            (self.mode_combo, "review_mode"),
            (self.destination_button, "review_destination"),
            (self.preview_combo, "review_preview_button"),
            (self.extra_edit, "review_extra_modules"),
            (self.back_button, "review_back"),
            (self.build_button, "review_build"),
        ):
            control.setAccessibleName(t(key))

    def _show_text_preview(self) -> None:
        if self._analysis is None:
            return
        rel_py = self.preview_combo.currentData()
        if not rel_py or rel_py not in self._analysis.converted:
            return
        rel_txt = Path(rel_py).with_suffix(".txt")
        source = self._analysis.root / rel_txt
        try:
            original, _encoding = decode_bytes(source.read_bytes())
        except (OSError, UnicodeError):
            original = t("review_preview_unavailable")
        dialog = TextPreviewDialog(
            rel_txt.as_posix(), original, self._analysis.converted[rel_py], self
        )
        dialog.exec()

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
            dest_dir=self._dest_dir,
            # Qt przechowuje dane pozycji jako QVariant i oddaje `AppKind`
            # z powrotem jako GOŁY napis. Rdzeń porównuje te pola przez `is`
            # (`plan.app_kind is AppKind.WINDOWED` w `pyinstaller.py`), więc
            # napis przechodzi cicho i daje program konsolowy tam, gdzie
            # użytkownik wybrał okno — czyli czarną konsolę za każdym GUI.
            # Typ odtwarzamy tu, na granicy z Qt.
            app_kind=AppKind(self.kind_combo.currentData()),
            output_mode=OutputMode(self.mode_combo.currentData()),
            extra_modules=_parse_modules(self.extra_edit.text()),
        )
        self.build_requested.emit(plan)


def _parse_modules(text: str) -> list[str]:
    """Wpisane moduły -> lista nazw. Przecinki i spacje rozdzielają, puste
    fragmenty odpadają — `resolve_extra_modules` i tak filtruje białe znaki."""
    return [token for token in re.split(r"[,\s]+", text.strip()) if token]


def _label_for(root: Path, path: Path) -> str:
    """Jak nazwać kandydata na liście.

    Sama nazwa pliku nie wystarcza: `main.py` w korzeniu i `pkg/main.py` dają
    dwie identyczne pozycje, więc użytkownik nie ma jak wybrać właściwej ani
    odczytać, która jest zaznaczona. Ścieżka względem katalogu projektu jest
    dla plików w korzeniu dokładnie tą samą nazwą, a głębiej mówi prawdę.
    """
    return path.relative_to(root).as_posix()
