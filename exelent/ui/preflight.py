"""How much must be downloaded, calculated before the user clicks.

Dependency resolution calls uv and PyPI, so it cannot run on the window thread.
The worker is cancellable and degrades quietly: missing uv, no network, or a
PyPI error leaves an empty plan and the screen falls back to the table estimate.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QThread, Signal

from exelent.build.backend import CancelToken
from exelent.constants import PYINSTALLER_SPEC, TARGET_PYTHON
from exelent.deps.sizes import DownloadPlan, resolve_download_plan
from exelent.runtime.bootstrap import uv_path
from exelent.runtime.env import run_uv

_THREAD_QUIT_TIMEOUT_MS = 5000

# B12: monotonic request-ID generator.
_request_counter = itertools.count(1)


def preflight_key(packages: Sequence[str], python_version: str = TARGET_PYTHON) -> str:
    normalized = sorted({package.strip().lower() for package in packages if package.strip()})
    return "\0".join((python_version, *normalized))


class _Job(QObject):
    finished = Signal(int, object)  # (request_id, DownloadPlan)

    def __init__(
        self,
        packages: Sequence[str],
        resolve,
        cancel: CancelToken,
        request_id: int,
        request_key: str,
    ) -> None:
        super().__init__()
        self._packages = list(packages)
        self._resolve = resolve
        self._cancel = cancel
        self._request_id = request_id
        self._request_key = request_key

    def run(self) -> None:
        try:
            plan = replace(
                self._resolve(self._packages, self._cancel), request_key=self._request_key
            )
        except Exception:  # noqa: BLE001 - a user-facing number must not kill the window
            plan = DownloadPlan(status="error", request_key=self._request_key)
        self.finished.emit(self._request_id, plan)


class PreflightWorker(QObject):
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._job: _Job | None = None
        self._token: CancelToken | None = None
        self._plan = DownloadPlan()
        # B12: request identifier prevents a stale result from replacing a new one.
        self._current_request: int = 0
        self._queued: tuple[tuple[str, ...], str, int] | None = None
        # Use an event rather than `QThread.wait`: the worker thread runs its
        # own event loop and ends it only after `quit()` from the main thread.
        # If the window waited through `QThread.wait`, it would wait for a
        # `quit()` it cannot call in time — always until the deadline.
        self._done = threading.Event()
        self._done.set()

    def plan(self, wait_ms: int = 0) -> DownloadPlan:
        """Last calculated plan. `wait_ms > 0` waits for active calculation.

        Specification §9.2 requires this explicitly: clicking "Create EXE"
        should WAIT briefly for a result rather than freeze the window on a
        network request or silently skip consent. At the deadline return what
        is available; an empty plan means "use the table estimate".
        """
        if wait_ms > 0:
            self._done.wait(wait_ms / 1000)
        return self._plan

    def _resolve(self, packages: Sequence[str], cancel: CancelToken) -> DownloadPlan:
        uv = uv_path()
        if not uv.exists():
            # Preflight does NOT download uv. That belongs to the build phase,
            # which has its own progress bar; downloading 15 MB behind screen 2
            # do uzytkownika, byloby niespodzianka.
            return DownloadPlan(status="missing_uv", uv_cached=False)
        # Use the TARGET Python version, not a path to a nonexistent
        # `preflight-venv`: --dry-run resolves wheels for the correct interpreter
        # (the one used by the build) when it is already in uv's cache. Without
        # that cache, degrade to an empty plan anyway.
        python_probe = run_uv(
            uv,
            ["python", "find", TARGET_PYTHON, "--no-python-downloads"],
            cancel=cancel,
        )
        plan = resolve_download_plan(
            uv=uv,
            python=TARGET_PYTHON,
            packages=[*packages, PYINSTALLER_SPEC],
            cancel=cancel,
        )
        return replace(
            plan,
            uv_cached=True,
            python_cached=python_probe.returncode == 0,
            includes_build_tools=True,
        )

    def is_running(self) -> bool:
        return self._thread is not None

    def matches(self, packages: Sequence[str], python_version: str = TARGET_PYTHON) -> bool:
        return self._plan.request_key == preflight_key(packages, python_version)

    def start(self, packages: Sequence[str]) -> None:
        stopped = self.stop()
        request_id = next(_request_counter)
        self._current_request = request_id
        # B12: clear the previous result rather than show the old project's
        # estimate while waiting.
        request_key = preflight_key(packages)
        self._plan = DownloadPlan(status="pending", request_key=request_key)
        self._done.clear()
        if not stopped:
            # Never abandon a running QThread or overwrite its reference. The
            # latest change wins and starts after the old job truly exits.
            self._queued = (tuple(packages), request_key, request_id)
            return
        self._launch(tuple(packages), request_key, request_id)

    def _launch(self, packages: tuple[str, ...], request_key: str, request_id: int) -> None:
        token = CancelToken()
        thread = QThread()
        job = _Job(packages, self._resolve, token, request_id, request_key)
        self._token = token
        self._thread = thread
        self._job = job
        job.moveToThread(thread)
        # TWO deliberate connections to one signal. The direct connection
        # stores the result on the worker thread so `plan(wait_ms)` has something
        # to await; the queued one cleans up on the main thread, the only place
        # allowed to call `quit()`/`wait()` on the owned thread.
        job.finished.connect(self._store, Qt.ConnectionType.DirectConnection)
        job.finished.connect(self._on_done)
        thread.started.connect(job.run)
        thread.start()

    def _store(self, request_id: int, plan: DownloadPlan) -> None:
        # B12: only the current result enters _plan.
        if request_id == self._current_request:
            self._plan = plan
            self._done.set()

    def _on_done(self, request_id: int, plan: DownloadPlan) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.quit()
            thread.wait(_THREAD_QUIT_TIMEOUT_MS)
        self._job = None
        if self._queued is not None:
            packages, request_key, queued_id = self._queued
            self._queued = None
            self._launch(packages, request_key, queued_id)
            return
        # B12: stale result from an old request — discard rather than emit.
        if request_id != self._current_request:
            return
        self._plan = plan
        self.finished.emit(plan)

    def stop(self, timeout_ms: int = _THREAD_QUIT_TIMEOUT_MS) -> bool:
        """Stop active calculation and WAIT for its thread. Return whether it exited.

        Qt destroys a running `QThread` on exit (abort), so
        `MainWindow.closeEvent` must call this just as it calls
        `BuildWorker.shutdown`.

        Cancellation comes FIRST because `quit()` only ends the thread's event
        loop. Work blocked in `uv pip install --dry-run` has no loop in which to
        notice it, and `wait()` would always consume the full deadline.

        Clear references only after the thread REALLY exits. Forgetting a live
        thread does not make it disappear; it only means nobody remembers to
        wait for it, and Qt destroys it during application shutdown.
        """
        self._queued = None
        thread = self._thread
        if thread is None:
            self._done.set()
            return True
        if self._token is not None:
            self._token.cancel()
        thread.quit()
        stopped = thread.wait(timeout_ms)
        if stopped:
            self._thread = None
            self._job = None
        # Nobody will calculate this plan now; release waiters instead of making
        # them sit through the full deadline.
        self._done.set()
        return stopped
