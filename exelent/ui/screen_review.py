"""Screen 2: what EXElent understood from the directory.

This is the difference between "works" and "the user is stuck": every guess is
visible before a five-minute build and correctable with one click.

The screen neither analyzes nor builds. It receives and displays
`ProjectAnalysis`, then returns user corrections as `BuildPlan`. All knowledge
of what the data means stays in the core; this layer only presents it.
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
    """Append "(recommended)" to an item label WITHOUT changing its data.

    `setItemText` changes only the label; `itemData` remains unchanged. This
    distinction prevents a regression where `currentData()` returns text and a
    console program masquerades as a windowed one.
    """
    if index < 0:
        return
    combo.setItemText(index, f"{combo.itemText(index)} {t('review_recommended_suffix')}")


class TextPreviewDialog(QDialog):
    """Original, result, and actual diff for one TXT conversion."""

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
        # Last preflight result. Preserve it because `retranslate` passes through
        # `load`, which starts with "checking size...". Otherwise a language
        # change would erase a calculated number that nobody recalculates.
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
        # A manual ONEFILE choice carries a visible limitation (B01), so warnings
        # are recalculated on EVERY mode change, not only during `load`.
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

        # Manually add modules invisible to static scanning (dynamic import,
        # plugin). Always visible regardless of `deps_box`: a project with no
        # detected dependencies may still need this field.
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

        # Information has its OWN label rather than a place among warnings: the
        # sentence "the program will take 26–45 MB" is not a warning and should
        # not look like one.
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
        """Display analysis results. Also called for a SECOND project in the same
        session, so set every field unconditionally; leftovers from the previous
        directory would describe a file that no longer exists."""
        self._analysis = analysis
        self._icon = analysis.suggested_icon
        self._custom_dest = False
        self._dest_dir = None

        # Reset labels of fixed-content lists because `_mark_recommended`
        # APPENDS a suffix; otherwise the second project in a session would get
        # "Windowed program (recommended) (recommended)".
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
        # Confidence requires a value. `entry_is_certain(())` is true to the core
        # ("there are not two tied candidates"), but the row is EMPTY and a `✓`
        # beside an empty field is false confidence — exactly what this screen
        # exists to prevent.
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

        # Unconditional like every field: a module added for the previous project
        # must not leak into the next build.
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
        """Warnings produced by the CURRENTLY selected output mode (B01).

        Qt returns item data as a plain string, so reconstruct the mode through
        `OutputMode(...)`, just like `_emit_plan`, allowing core `is`
        comparisons to see an enum rather than a string.
        """
        data = self.mode_combo.currentData()
        if data is None:
            return ()
        return onefile_limitation_issues(OutputMode(data))

    def _update_issue_labels(self) -> None:
        """Assemble warnings and notes from analysis AND the selected mode.

        Called from `load` and on every mode change, so selecting "One EXE file"
        immediately shows its limitation and returning to "Application folder"
        hides it."""
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
        """Rewrite text after a language change.

        Screens obtain text from `t()` in their constructors, so without this
        method the language switch would take effect only after a restart.

        Run `load` again after captions: list items, "(recommended)" suffixes,
        and `describe()` sentences are text too, and `load` is the only place
        that can assemble them.
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
        """B12: three separate sizes and explicit preparation components."""
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
        """Assign translated accessible names to controls for screen readers."""
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
        """There is nothing to build without loaded analysis.

        The screen is created with the window long before a folder is selected,
        so this state is real rather than theoretical.
        """
        if self._analysis is None:
            return
        plan = make_plan(
            self._analysis,
            entry=self.entry_combo.currentData(),
            exe_name=self.name_edit.text(),
            icon=self._icon,
            dest_dir=self._dest_dir,
            # Qt stores item data as QVariant and returns `AppKind` as a BARE
            # string. The core compares these fields with `is`
            # (`plan.app_kind is AppKind.WINDOWED` in `pyinstaller.py`), so the
            # string passes silently and produces a console app where the user
            # selected a window, adding a black console to every GUI. Restore
            # the type here at the Qt boundary.
            app_kind=AppKind(self.kind_combo.currentData()),
            output_mode=OutputMode(self.mode_combo.currentData()),
            extra_modules=_parse_modules(self.extra_edit.text()),
        )
        self.build_requested.emit(plan)


def _parse_modules(text: str) -> list[str]:
    """Entered modules -> list of names. Commas and spaces separate entries;
    empty fragments are removed, as `resolve_extra_modules` filters whitespace."""
    return [token for token in re.split(r"[,\s]+", text.strip()) if token]


def _label_for(root: Path, path: Path) -> str:
    """How to label a candidate in the list.

    A filename alone is insufficient: root `main.py` and `pkg/main.py` produce
    identical entries, so the user cannot choose or identify the right one. A
    path relative to the project directory is the same short name for root files
    and tells the truth for deeper ones.
    """
    return path.relative_to(root).as_posix()
