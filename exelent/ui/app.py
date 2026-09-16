"""Main window: three-screen stack, theme, and language switch.

The window is the only place that knows screen order; screens know nothing about
one another and communicate only through signals. The sole build worker also
lives here: screen 3 displays progress but does not own the thread.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QStackedWidget

from exelent.constants import APP_NAME
from exelent.deps.sizes import estimate_exe_size
from exelent.i18n import set_language, system_language
from exelent.models import Issue, Severity
from exelent.runtime.paths import clean_current_session, clean_stale_sessions, register_session
from exelent.runtime.procs import kill_tree
from exelent.settings import load_settings, save_settings
from exelent.ui.analysis_worker import AnalysisWorker
from exelent.ui.dialog_download import DownloadDialog, should_ask, should_ask_offline
from exelent.ui.dialog_settings import SettingsDialog
from exelent.ui.preflight import PreflightWorker
from exelent.ui.screen_build import BuildScreen
from exelent.ui.screen_drop import DropScreen
from exelent.ui.screen_review import ReviewScreen
from exelent.ui.theme import build_stylesheet, is_system_dark
from exelent.ui.worker import BuildWorker

SCREEN_DROP = 0
SCREEN_REVIEW = 1
SCREEN_BUILD = 2

# How long the window waits for preflight after "Create EXE" is clicked.
# Specification §9.2 sets a short deadline followed by a table estimate. A
# click must not freeze the window on a network request; a slow connection is
# exactly the case that prompted issue 4.
PREFLIGHT_WAIT_MS = 1500


def _force_shutdown() -> None:
    """Terminate the application and all descendants without Qt cleanup.

    Last resort for a closing window whose worker thread missed its deadline.
    Terminate the process tree first; otherwise uv or PyInstaller remain as
    orphans holding files. `os._exit` is only a fallback because taskkill with
    `/T` also terminates this process.
    """
    kill_tree(os.getpid())
    os._exit(1)


class MainWindow(QMainWindow):
    language_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        # Store an attribute rather than calling directly so tests can replace
        # it with something that does not terminate pytest itself.
        self.hard_exit = _force_shutdown
        # Set language FIRST, before screens. Screens obtain text from `t()` in
        # their constructors, so setting it later left English users with a
        # Polish window: measured — screen 1 stayed Polish while
        # `current_language() == "en"`.
        #
        # A saved selection outranks system language; `None` means follow it.
        settings = load_settings()
        set_language(settings.language or system_language())
        self.setWindowTitle(APP_NAME)
        self.resize(900, 620)
        self.setMinimumSize(760, 540)

        self.screen_drop = DropScreen()
        self.screen_drop.folder_chosen.connect(self._on_folder_chosen)
        self.screen_drop.settings_requested.connect(self._on_settings)
        self.screen_review = ReviewScreen()
        self.screen_review.build_requested.connect(self._on_build_requested)
        self.screen_review.back_requested.connect(self._on_back_to_drop)
        self.screen_build = BuildScreen()
        self.screen_build.restart_requested.connect(self._on_restart)
        self.screen_build.back_to_review.connect(self._on_back_to_review)

        # One worker for the window lifetime, connected once. Creating one for
        # every build would duplicate signal connections.
        self.worker = BuildWorker()
        self.worker.progress.connect(self.screen_build.on_progress)
        self.worker.finished.connect(self.screen_build.on_finished)
        self.screen_build.cancel_button.clicked.connect(self.worker.cancel)

        # Analysis warnings from screen 2: the build executes a completed plan,
        # so analysis warnings must be passed separately.
        self._carried: tuple[Issue, ...] = ()

        # Background analysis: one worker for the window lifetime, like BuildWorker.
        self._analysis_worker = AnalysisWorker()
        self._analysis_worker.finished.connect(self._on_analysis_done)

        # Download size is calculated behind screen 2. It never blocks a build;
        # an empty result only means the number could not be calculated.
        self.preflight = PreflightWorker()
        self.preflight.finished.connect(self.screen_review.show_download_plan)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.screen_drop)
        self.stack.addWidget(self.screen_review)
        self.stack.addWidget(self.screen_build)
        self.setCentralWidget(self.stack)

        # `language_changed` existed from the start but NOBODY listened to it;
        # changing system language was the only path to English. Screens now
        # receive their updated text.
        self.language_changed.connect(self._retranslate)

        self.setStyleSheet(build_stylesheet(is_system_dark()))

    def _on_settings(self) -> None:
        dialog = SettingsDialog(load_settings(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.chosen()
        save_settings(chosen)
        self.set_language(chosen.language or system_language())

    def _retranslate(self, _lang: str) -> None:
        for screen in (self.screen_drop, self.screen_review, self.screen_build):
            screen.retranslate()

    def go_to(self, index: int) -> None:
        """Change the current screen.

        Do not add custom range checks: `QStackedWidget` ignores out-of-range
        indexes itself. Verified for 99, -1, and -5; the stack never loses its
        screen. A custom `if` would be a branch no test can kill (deleting it
        survived mutation testing), while an observable-behavior test protects
        the invariant.
        """
        self.stack.setCurrentIndex(index)

    def _on_folder_chosen(self, folder: Path) -> None:
        """B11: background analysis keeps Qt responsive on large projects.

        Screen 1 shows loading state and the result arrives through
        `_on_analysis_done`. If the user selects another folder meanwhile, the
        worker automatically discards the stale previous result.
        """
        self.screen_drop.set_analyzing(True)
        self._analysis_worker.start(folder)

    def _on_analysis_done(self, analysis) -> None:
        """Handle the background analysis result and move to screen 2."""
        self.screen_drop.set_analyzing(False)
        self._carried = tuple(i for i in analysis.issues if i.severity is not Severity.BLOCKER)
        self.screen_review.load(analysis)
        self.preflight.start([d.package for d in analysis.dependencies if not d.optional])
        self.go_to(SCREEN_REVIEW)

    def _download_dialog(self, plan, download, settings) -> DownloadDialog | None:
        """Consent dialog for this build, or `None` when there is nothing to ask.

        Two paths cover three preflight outcomes: calculated with missing items
        (ask using the exact number), calculated with nothing missing (do not
        ask), or timed out/failed (ask using the §7.2 table estimate).
        """
        if should_ask(download, settings):
            return DownloadDialog(download, self)
        low, high, heaviest = estimate_exe_size(plan.packages)
        if should_ask_offline(download, settings, high):
            return DownloadDialog(download, self, estimate=(low, high), estimate_packages=heaviest)
        return None

    def _on_build_requested(self, plan) -> None:
        """Clear screen 3 BEFORE showing it, then start the build after navigation.

        Ask for download consent first, with a bounded preflight wait so the
        click neither hangs on the network nor silently skips the question.
        """
        # Changes on screen 2, especially a manually added module, create a plan
        # with a different package list. An estimate for the old scope must not
        # reach the new build's dialog or progress bar.
        if not self.preflight.matches(plan.packages, plan.python_version):
            self.preflight.start(plan.packages)
        download = self.preflight.plan(wait_ms=PREFLIGHT_WAIT_MS)
        settings = load_settings()
        dialog = self._download_dialog(plan, download, settings)
        if dialog is not None:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return  # stay on screen 2; nothing started
            if dialog.dont_ask_again():
                save_settings(replace(settings, ask_before_download=False))

        plan = replace(plan, total_download_bytes=download.total_bytes)
        self.screen_build.start(plan)
        self.go_to(SCREEN_BUILD)
        self.worker.start(plan, self._carried)

    def _on_back_to_drop(self) -> None:
        """Return to the start without building.

        Refresh recent items because the project just selected is already there
        (`DropScreen._choose` calls `recent.remember` before emitting), while
        screen 1 last read the list at application startup.
        """
        if self.worker.is_running():
            return
        self._analysis_worker.stop()
        self.preflight.stop()
        self.screen_drop.set_analyzing(False)
        self.screen_drop.refresh_recent()
        self.go_to(SCREEN_DROP)

    def _on_back_to_review(self) -> None:
        """Return to screen 2 with the analysis PRESERVED.

        Screen 2 is long-lived and stores the last `ProjectAnalysis`, so fixing
        a name after a failed build does not require rescanning the directory.

        Blocking navigation during a build is necessary: `BuildWorker.start`
        silently rejects a second build, which would otherwise leave the user
        on a progress screen that never starts.
        """
        if self.worker.is_running():
            return
        self.go_to(SCREEN_REVIEW)

    def _on_restart(self) -> None:
        """Return to the start. Refresh recent projects because the newly built
        project was just added, while screen 1 last read the list at startup."""
        if self.worker.is_running():
            return
        self.screen_drop.refresh_recent()
        self.go_to(SCREEN_DROP)

    def closeEvent(self, event) -> None:
        """Close the window during a build.

        Without this, Qt destroys the running `QThread` on exit (abort), leaving
        PyInstaller orphaned with files open — exactly what `kill_tree` prevents.
        Qt dictates the camelCase method name; this overrides `QWidget`.

        When graceful shutdown fails because work is stuck in a call that never
        checks cancellation, force termination. Returning control to Qt with a
        live thread ends in `abort()`, and a windowed application has nowhere to
        show it: the user closes the window but the process remains in the background.
        """
        stopped_analysis = self._analysis_worker.stop()
        stopped_preflight = self.preflight.stop()
        stopped_build = self.worker.shutdown()
        super().closeEvent(event)
        if not (stopped_analysis and stopped_preflight and stopped_build):
            self.hard_exit()
            return
        # Graceful shutdown: threads exited, so no process holds this session's
        # files. Remove THIS session's working directory (code copy, venv,
        # PyInstaller scratch) while leaving other instances untouched.
        # Best-effort cleanup must not delay window shutdown.
        clean_current_session()

    def set_language(self, lang: str) -> None:
        set_language(lang)
        self.language_changed.emit(lang)


def run_gui(argv: list[str]) -> int:
    register_session()
    clean_stale_sessions()
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui(sys.argv))
