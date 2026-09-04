"""Rozmiary i czasy po ludzku. Jedyne miejsce, które je formatuje.

Cztery niezależne implementacje „ile to megabajtów" rozjeżdżają się co do
zaokrąglenia, a użytkownik widzi 26,0 MB w oknie i 26 MB na ekranie obok.
"""

from __future__ import annotations

import math


def human_size(size_bytes: int) -> str:
    megabytes = size_bytes / 1024**2
    if megabytes >= 1:
        return f"{megabytes:.1f} MB"
    # Zaokrąglenie połówek W GÓRĘ, a nie bankierskie: `f"{0.5:.0f}"` daje
    # w Pythonie "0", więc pobranie 512 bajtów meldowało się jako "0 KB".
    return f"{math.floor(size_bytes / 1024 + 0.5):.0f} KB"


def human_speed(bytes_per_second: float) -> str:
    return f"{human_size(int(bytes_per_second))}/s"


def human_duration(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total} s"
    return f"{total // 60} min {total % 60} s"
