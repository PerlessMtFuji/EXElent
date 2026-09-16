"""Human-readable sizes and times. The single place that formats them.

Four independent implementations of "how many megabytes" disagree on rounding,
so the user sees 26.0 MB in one window and 26 MB on the adjacent screen.
"""

from __future__ import annotations

import math


def human_size(size_bytes: int) -> str:
    megabytes = size_bytes / 1024**2
    if megabytes >= 1:
        return f"{megabytes:.1f} MB"
    # Round halves UP rather than using banker's rounding: `f"{0.5:.0f}"`
    # produces "0" in Python, so a 512-byte download was reported as "0 KB".
    return f"{math.floor(size_bytes / 1024 + 0.5):.0f} KB"


def human_speed(bytes_per_second: float) -> str:
    return f"{human_size(int(bytes_per_second))}/s"


def human_duration(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total} s"
    return f"{total // 60} min {total % 60} s"
