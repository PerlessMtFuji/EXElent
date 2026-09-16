"""One progress shape for the entire application.

Byte fields are zero for phases that download nothing (PyInstaller packaging).
The presentation layer detects this through `total_bytes == 0` and hides the
second line — an empty megabyte counter below the bar is worse than no counter.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    phase: str
    fraction: float
    done_bytes: int = 0
    total_bytes: int = 0
    speed_bps: float = 0.0
    eta_s: float | None = None
