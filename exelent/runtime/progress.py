"""Jeden kształt postępu dla całego programu.

Pola bajtowe są zerowe dla faz, które nic nie pobierają (pakowanie
PyInstallerem). Warstwa prezentacji poznaje to po `total_bytes == 0` i wtedy
nie pokazuje drugiej linijki — pusty licznik megabajtów pod paskiem jest
gorszy niż jego brak.
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
