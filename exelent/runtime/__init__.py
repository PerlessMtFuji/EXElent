from collections.abc import Callable

from exelent.runtime.progress import Progress

ProgressFn = Callable[[Progress], None]
"""Wywoływane z jednym `Progress`. Kod fazy tłumaczy warstwa UI."""


def noop_progress(update: Progress) -> None:
    return None


__all__ = ["Progress", "ProgressFn", "noop_progress"]
