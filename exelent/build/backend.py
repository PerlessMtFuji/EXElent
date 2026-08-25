"""Kontrakt backendu budującego. PyInstaller jest pierwszą implementacją;
interfejs istnieje po to, żeby dołożyć Nuitkę bez ruszania reszty aplikacji."""

from __future__ import annotations

import threading
from typing import Protocol

from exelent.models import BuildPlan, BuildResult
from exelent.runtime import ProgressFn
from exelent.runtime.env import BuildEnv


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class BuildBackend(Protocol):
    def build(
        self,
        plan: BuildPlan,
        env: BuildEnv,
        progress: ProgressFn,
        cancel: CancelToken,
    ) -> BuildResult: ...
