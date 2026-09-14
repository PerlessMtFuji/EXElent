"""Postep jako jeden obiekt.

Para (faza, ulamek) nie miala gdzie zmiescic bajtow ani predkosci, a dolozenie
pieciu argumentow opcjonalnych dalo by sygnature, ktorej nikt nie umie wypelnic
w polowie. Jeden obiekt jest uczciwszy.
"""

from dataclasses import FrozenInstanceError

import pytest

from exelent.runtime import noop_progress
from exelent.runtime.progress import Progress


def test_progress_is_immutable():
    update = Progress(phase="analyze", fraction=0.5)
    with pytest.raises(FrozenInstanceError):
        update.fraction = 0.9


def test_byte_fields_default_to_zero_for_phases_that_download_nothing():
    """Pakowanie PyInstallerem nic nie pobiera. Pusty licznik bajtow pod
    paskiem bylby gorszy niz jego brak, wiec ekran pozna to po zerze."""
    update = Progress(phase="package", fraction=0.5)
    assert update.total_bytes == 0
    assert update.done_bytes == 0
    assert update.eta_s is None


def test_noop_progress_accepts_the_object():
    assert noop_progress(Progress(phase="analyze", fraction=0.0)) is None
