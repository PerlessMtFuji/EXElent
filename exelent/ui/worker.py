"""Bridge between the build thread and GUI. The only thread boundary.

A build takes one to several minutes and must not freeze the window. All
communication uses signals: `_Job` lives in `QThread`, `BuildWorker` in the
window thread, so connections are queued and no structure is touched from both
sides at once. The only shared object is `CancelToken`, designed for this with
an internal `threading.Event`.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QObject, QThread, Signal

from exelent.build.backend import CancelToken
from exelent.build.service import execute_build
from exelent.models import BuildPlan, BuildResult, Issue, Severity

# How long to wait for the thread to close after a build. At that point it only
# needs to leave the event loop, so the wait is brief; the limit prevents the
# window from hanging forever if it does not exit.
_THREAD_QUIT_TIMEOUT_MS = 5000


class _Job(QObject):
    """The actual work, executed on the worker thread."""

    progress = Signal(object)
    finished = Signal(object)

    def __init__(self, plan: BuildPlan, cancel: CancelToken, carried: Sequence[Issue] = ()) -> None:
        super().__init__()
        self._plan = plan
        self._cancel = cancel
        self._carried = tuple(carried)

    def run(self) -> None:
        try:
            # Build EXACTLY the plan accepted on screen 2 without reanalyzing
            # the folder. Previously the worker called `run_build(plan.root,
            # ...)`, which rescanned the directory and lost single-file mode:
            # building `Downloads/x.py` packaged all of Downloads. `carried`
            # brings analysis warnings from screen 2 to the result screen.
            result = execute_build(
                self._plan, self.progress.emit, self._cancel, carried=self._carried
            )
        except Exception as exc:  # noqa: BLE001 - a build must not kill the GUI
            # `run_build` has its own exception boundary, so only escapes reach
            # this point. The code and data key match the core exactly
            # (`cli._unexpected_issues`): the catalog describes
            # `unexpected_error` with `{error}`; another key would make `t()`
            # show a non-technical user a brace inside the sentence.
            result = BuildResult(
                ok=False,
                issues=(
                    Issue("unexpected_error", Severity.BLOCKER, {"error": type(exc).__name__}),
                ),
            )
        self.finished.emit(result)


class BuildWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._token: CancelToken | None = None
        self._thread: QThread | None = None
        self._job: _Job | None = None

    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, plan: BuildPlan, carried: Sequence[Issue] = ()) -> None:
        """Start a build on a separate thread.

        Create the token HERE rather than once for the worker lifetime. A single
        permanent token would make every build after the first cancellation
        start already cancelled and finish immediately without explanation.

        Reject a second build while one is running. Specification §3 permits
        one at a time because both use the same environment cache.

        `carried` contains analysis warnings from screen 2 (for example a secret
        in code or a heavy package) that must reach the result screen.
        """
        if self.is_running():
            return
        self._token = CancelToken()
        self._thread = QThread()
        self._job = _Job(plan, self._token, carried)
        self._job.moveToThread(self._thread)
        self._job.progress.connect(self.progress)
        self._job.finished.connect(self._on_done)
        self._thread.started.connect(self._job.run)
        self._thread.start()

    def cancel(self) -> None:
        if self._token is not None:
            self._token.cancel()

    def shutdown(self, timeout_ms: int = _THREAD_QUIT_TIMEOUT_MS) -> bool:
        """Stop a running build and WAIT for its thread when closing the window.

        Plain `cancel()` is insufficient: it returns immediately, after which
        Qt destroys the running `QThread` (abort) and leaves PyInstaller
        orphaned. Clear references only after the thread REALLY exits; dropping
        a running thread would recreate the failure this method prevents.
        """
        thread = self._thread
        if thread is None:
            return True
        self.cancel()
        thread.quit()
        if not thread.wait(timeout_ms):
            return False
        self._thread = None
        self._job = None
        return True

    def _on_done(self, result: BuildResult) -> None:
        """Clean up the thread, then emit the result upward.

        Order matters both ways: `_thread` disappears BEFORE waiting so
        `is_running()` is already accurate in the `finished` slot (the window
        returns to screen 1 and may start another build), while the `_Job`
        reference disappears only AFTER `wait()`. Until the thread leaves its
        loop, emitting `finished` remains on its stack, and deleting the object
        mid-emission accesses freed memory.
        """
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.quit()
            thread.wait(_THREAD_QUIT_TIMEOUT_MS)
        self._job = None
        self.finished.emit(result)
