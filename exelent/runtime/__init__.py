from collections.abc import Callable

from exelent.runtime.progress import Progress

ProgressFn = Callable[[Progress], None]
"""Called with one `Progress`. The UI layer translates the phase code."""


def noop_progress(update: Progress) -> None:
    return None


__all__ = ["Progress", "ProgressFn", "noop_progress"]
