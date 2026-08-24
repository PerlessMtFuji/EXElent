from collections.abc import Callable

ProgressFn = Callable[[str, float], None]
"""Wywoływane z (kod_fazy, postęp 0.0-1.0). Kod fazy tłumaczy warstwa UI."""


def noop_progress(phase: str, fraction: float) -> None:
    return None


__all__ = ["ProgressFn", "noop_progress"]
