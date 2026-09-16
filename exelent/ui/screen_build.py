"""Screen 3: build progress and result.

Four states in one widget: running, succeeded, failed, cancelled. Separating
cancellation from failure is not cosmetic: a user who clicked "Cancel" should
not be asked to report their own decision as a bug.

Always show the antivirus warning after success; the user will encounter the
issue eventually and should hear about it from us first.
"""

from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from exelent.diagnostics.report import github_issue_url, tail, write_report
from exelent.i18n import describe, t
from exelent.models import BuildPlan, BuildResult, Severity, VerificationStatus
from exelent.ui.format import human_duration, human_size, human_speed

# Number of trailing log lines shown in the window. PyInstaller logs may be
# several megabytes, while the interesting part is always at the end.
LOG_TAIL_LINES = 200

# Issue representing a user decision rather than a failure.
CANCELLED = "build_cancelled"


class BuildScreen(QWidget):
    restart_requested = Signal()
    back_to_review = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._result: BuildResult | None = None
        self._plan: BuildPlan | None = None
        self._log_open = False
        # Translation key for the heading sentence. Text alone is insufficient:
        # it must be rebuilt after a language change, and `t()` is not reversible.
        self._phase_key = "build_start"

        self.phase_label = QLabel(t("build_start"), objectName="Title")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bytes_label = QLabel("", objectName="Muted")
        self.bytes_label.setVisible(False)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        # B13: analysis and backend warnings remain visible after success too.
        self.issues_label = QLabel("")
        self.issues_label.setWordWrap(True)
        self.issues_label.setObjectName("Muted")
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

        # Respond to "Cancel" immediately. Cancellation travels through another
        # connection (in app.py), but before the thread reacts the button should
        # show "Cancelling..." and stop accepting clicks.
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.again_button.clicked.connect(self.restart_requested)
        self.back_button.clicked.connect(self.back_to_review)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.run_button.clicked.connect(self._run_artifact)
        self.report_button.clicked.connect(self._save_report)
        self.github_button.clicked.connect(self._open_github)

        # Two short rows fit with large text scaling; one horizontal row of seven
        # actions overflowed a small window.
        actions = QGridLayout()
        actions.addWidget(self.back_button, 0, 0)
        actions.addWidget(self.cancel_button, 0, 1)
        actions.addWidget(self.open_folder_button, 0, 2)
        actions.addWidget(self.run_button, 0, 3)
        actions.addWidget(self.report_button, 1, 0)
        actions.addWidget(self.github_button, 1, 1)
        actions.setColumnStretch(2, 1)
        actions.addWidget(self.again_button, 1, 3)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 28)
        outer.setSpacing(16)
        outer.addWidget(self.phase_label)
        outer.addWidget(self.bar)
        outer.addWidget(self.bytes_label)
        outer.addWidget(self.summary_label)
        outer.addWidget(self.issues_label)
        outer.addWidget(self.antivirus_label)
        outer.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(self.log_view, stretch=1)
        outer.addStretch(1)
        outer.addLayout(actions)

        self.setTabOrder(self.cancel_button, self.open_folder_button)
        self.setTabOrder(self.open_folder_button, self.run_button)
        self.setTabOrder(self.run_button, self.report_button)
        self.setTabOrder(self.report_button, self.github_button)
        self.setTabOrder(self.github_button, self.again_button)

        self._show_running()

    # --- stany ---

    def _hide_all_actions(self) -> None:
        """Clean starting point for every state.

        A state should define the WHOLE screen rather than add to the previous
        one. Without this, moving from failure to cancellation left "Report on
        GitHub" from the failure visible, as observed in rendering.

        The megabyte counter disappears here with the buttons; otherwise a
        build cancelled mid-download would leave a still-counting number below
        the failure message.
        """
        self.antivirus_label.setVisible(False)
        self.issues_label.setVisible(False)
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
        """Rewrite text after a language change.

        Screens obtain text from `t()` in their constructors, so without this
        method the language switch would take effect only after a restart.

        Once a build has finished, rebuild the full screen from its result:
        summary sentences come from `describe()` and would otherwise remain in
        the previous language.
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

    def _on_cancel_clicked(self) -> None:
        """Acknowledge cancellation immediately without waiting for the thread.

        Process cancellation can take a moment while the uv/PyInstaller tree is
        terminated. Meanwhile the button must say 'Cancelling...' and reject a
        second click so the first one does not appear ineffective."""
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText(t("build_cancelling"))

    def _show_running(self) -> None:
        self._set_phase("build_start")
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.summary_label.setText("")
        self.log_view.setPlainText("")
        self._show_log(False)
        self.log_toggle.setVisible(False)
        self._hide_all_actions()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText(t("build_cancel"))
        self.cancel_button.setVisible(True)

    def start(self, plan: BuildPlan) -> None:
        """Start every new build from a clean screen.

        Otherwise the second build runs with its progress bar AND the previous
        build's failure sentence, "Save report" button, and log, displaying two
        different builds at once.
        """
        self._plan = plan
        self._result = None
        self._show_running()

    def on_progress(self, update) -> None:
        self._set_phase(update.phase)
        self.bar.setValue(int(update.fraction * 100))
        self._show_bytes(update)

    def _show_bytes(self, update) -> None:
        """Show the second line only while something is actually downloading.

        An empty megabyte counter under the packaging bar would be worse than
        no counter, so the screen detects this through `total_bytes == 0`.
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
        artifact = result.artifact
        if artifact is None:
            return
        self.bar.setValue(100)
        self._set_phase("done")
        has_warnings = any(issue.severity is Severity.WARNING for issue in result.issues)
        if result.verification is VerificationStatus.PASSED and has_warnings:
            summary_key = "build_success_verified_warnings"
        elif result.verification is VerificationStatus.PASSED:
            summary_key = "build_success_verified"
        elif has_warnings:
            summary_key = "build_success_warnings"
        else:
            summary_key = "build_success"
        self.summary_label.setText(
            t(summary_key, name=artifact.name, size=human_size(result.size_bytes))
        )
        # B13: analysis and backend warnings remain visible after success too.
        # A "Run" button alone does not prove the application is correct.
        if result.issues:
            self.issues_label.setText("\n".join(describe(i) for i in result.issues))
            self.issues_label.setVisible(True)
        self.antivirus_label.setVisible(True)
        self.open_folder_button.setVisible(True)
        self.run_button.setVisible(True)

    def _show_cancelled(self, result: BuildResult) -> None:
        """Cancellation is not a failure: no report and no bug submission.

        The cancellation sentence is the heading rather than a repetition in
        the summary. Keep only information the user does not yet know, such as
        a warning that something may have launched after cancellation.
        """
        self.bar.setVisible(False)
        self._set_phase(CANCELLED)
        self.summary_label.setText(
            "\n".join(describe(i) for i in result.issues if i.code != CANCELLED)
        )
        self.back_button.setVisible(True)

    def _show_failure(self, result: BuildResult) -> None:
        """Do NOT diagnose here.

        `run_build` passes the full log through `explain_log`; recognized items
        are already in `result.issues`. Repeating the process on the log tail,
        as originally planned, could only find a subset while moving diagnostic
        knowledge into the presentation layer.
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
                # The log path comes from the core, but the file may already be
                # gone: builds live in a temporary directory the system cleans.
                # A missing log is no reason to lose the result.
                text = ""
        self.log_view.setPlainText(text)
        # Put the cursor at the end because logs are read backward from the
        # failure. Opening at line one would make users scroll two hundred lines
        # before seeing the cause.
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_toggle.setVisible(bool(text))

    def _show_log(self, visible: bool) -> None:
        self._log_open = visible
        self.log_view.setVisible(visible)
        self.log_toggle.setText(t("build_hide_log") if visible else t("build_show_log"))

    def _toggle_log(self) -> None:
        # Store state separately rather than reading `isVisible()`, which reports
        # ON-SCREEN visibility and returns False until the window is shown even
        # for a widget just revealed.
        self._show_log(not self._log_open)

    # --- akcje ---

    def _open_folder(self) -> None:
        """"Show in folder" should SELECT the EXE, not merely open its directory.

        An ONEDIR output can contain hundreds of entries, so merely opening the
        window leaves users searching. `/select` opens Explorer with the EXE
        selected, including in ONEDIR where it sits among libraries.
        """
        result = self._result
        if result is None or result.artifact is None:
            return
        selectable = result.executable_path or result.artifact
        arguments = (
            ["explorer", f"/select,{selectable}"]
            if selectable.is_file()
            else ["explorer", str(result.artifact)]
        )
        try:
            subprocess.run(arguments, check=False)
        except OSError as exc:
            self._show_action_error("build_open_failed", exc)

    def _run_artifact(self) -> None:
        """Launch the finished application in ONEFILE or ONEDIR mode.

        `artifact.is_file()` is false for ONEDIR, whose artifact is a directory,
        so the "Run" button did nothing. Launch `executable_path` instead and
        use the EXE directory as `cwd` so the program can read adjacent assets."""
        exe = self._result.executable_path if self._result else None
        if exe is not None and exe.is_file():
            try:
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
            except OSError as exc:
                self._show_action_error("build_run_failed", exc)
                return
            self._append_status(t("build_launch_started"))

    def _append_status(self, text: str) -> None:
        previous = self.issues_label.text()
        self.issues_label.setText("\n".join(part for part in (previous, text) if part))
        self.issues_label.setVisible(True)

    def _show_action_error(self, key: str, exc: OSError) -> None:
        self._append_status(t(key, error=str(exc)))

    def _plan_summary(self) -> str:
        """Issue context: the PROJECT name, not the artifact name.

        A report exists only after a failed build, when by definition there is
        no artifact. The planned version therefore described every issue with
        the word "build".
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
