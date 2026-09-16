"""One source for formatting sizes and durations.

Four independent implementations of byte formatting will eventually disagree
on rounding, showing 26.0 MB in one window and 26 MB on the next screen.
"""

import pytest

from exelent.ui.format import human_duration, human_size, human_speed


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 KB"), (512, "1 KB"), (1024, "1 KB"), (1024**2, "1.0 MB"), (26 * 1024**2, "26.0 MB")],
)
def test_human_size(value, expected):
    assert human_size(value) == expected


def test_human_speed_reads_per_second():
    assert human_speed(4.2 * 1024**2) == "4.2 MB/s"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(9, "9 s"), (75, "1 min 15 s"), (3600, "60 min 0 s")],
)
def test_human_duration(seconds, expected):
    assert human_duration(seconds) == expected
