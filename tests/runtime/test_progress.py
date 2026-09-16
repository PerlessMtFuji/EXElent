"""Represent progress as one object.

A (phase, fraction) pair had nowhere to carry byte counts or speed. Five
optional arguments would create a signature that callers could only partially
populate, so a single object expresses the data more honestly.
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
    """PyInstaller packaging downloads nothing.

    An empty byte counter below the progress bar is worse than no counter, so
    the screen recognizes this state by its zero values.
    """
    update = Progress(phase="package", fraction=0.5)
    assert update.total_bytes == 0
    assert update.done_bytes == 0
    assert update.eta_s is None


def test_noop_progress_accepts_the_object():
    assert noop_progress(Progress(phase="analyze", fraction=0.0)) is None
