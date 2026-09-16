"""Parser for uv output. Every format was measured on uv 0.8.17, not assumed.

This file is the only place that knows how uv speaks. Every format comes from
a real run saved in `fixtures/`, because a parser based on imagined tool output
fails silently on the first version change and leaves a frozen progress bar.
"""

from pathlib import Path

import pytest

from exelent.runtime.uvlog import (
    DOWNLOAD_DONE,
    DOWNLOAD_START,
    INSTALLED,
    PACKAGE,
    PREPARED,
    RESOLVED,
    UNCACHED_PACKAGE,
    WOULD_DOWNLOAD,
    parse_line,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _events(name: str):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [e for e in (parse_line(line) for line in text.splitlines()) if e is not None]


def test_download_start_carries_name_and_size():
    event = parse_line("Downloading pillow (6.9MiB)")
    assert event.kind == DOWNLOAD_START
    assert event.name == "pillow"
    assert event.size_bytes == int(6.9 * 1024**2)


def test_download_completion_has_a_leading_space_and_no_size():
    event = parse_line(" Downloading pillow")
    assert event.kind == DOWNLOAD_DONE
    assert event.name == "pillow"


def test_python_download_name_contains_parentheses():
    """A naive regex treats `(download)` as the size and fails.

    The pattern must anchor on the final parentheses and require a unit there.
    """
    event = parse_line("Downloading cpython-3.11.13-windows-x86_64-none (download) (24.3MiB)")
    assert event.kind == DOWNLOAD_START
    assert event.name == "cpython-3.11.13-windows-x86_64-none (download)"
    assert event.size_bytes == int(24.3 * 1024**2)


def test_python_download_completion_keeps_the_parenthesised_name():
    event = parse_line(" Downloading cpython-3.11.13-windows-x86_64-none (download)")
    assert event.kind == DOWNLOAD_DONE
    assert event.name == "cpython-3.11.13-windows-x86_64-none (download)"


@pytest.mark.parametrize(
    ("line", "kind", "count"),
    [
        ("Resolved 14 packages in 18ms", RESOLVED, 14),
        ("Resolved 1 package in 477ms", RESOLVED, 1),
        ("Would download 8 packages", WOULD_DOWNLOAD, 8),
        ("Prepared 1 package in 1.25s", PREPARED, 1),
        ("Prepared 12 packages in 3.4s", PREPARED, 12),
    ],
)
def test_counting_lines_accept_singular_and_plural(line, kind, count):
    """uv writes both "1 package" and "12 packages"; accept both forms."""
    event = parse_line(line)
    assert event.kind == kind
    assert event.count == count


def test_package_line_carries_name_and_version():
    event = parse_line(" + python-dateutil==2.9.0.post0")
    assert event.kind == PACKAGE
    assert event.name == "python-dateutil==2.9.0.post0"


def test_verbose_dry_run_identifies_the_uncached_distribution():
    event = parse_line("DEBUG Identified uncached distribution: scipy==1.18.1")
    assert event.kind == UNCACHED_PACKAGE
    assert event.name == "scipy==1.18.1"


@pytest.mark.parametrize(
    "line",
    [
        "",
        "Using Python 3.12.11 environment at: probe-venv",
        "Would install 14 packages",
        " + cpython-3.11.13-windows-x86_64-none (python3.11.exe)",
        "something completely unknown",
    ],
)
def test_unknown_lines_return_none_and_never_raise(line):
    """Progress is optional presentation; a parser exception must not kill a build."""
    assert parse_line(line) is None


def test_all_units_are_powers_of_1024():
    assert parse_line("Downloading a (1KiB)").size_bytes == 1024
    assert parse_line("Downloading a (1MiB)").size_bytes == 1024**2
    assert parse_line("Downloading a (1GiB)").size_bytes == 1024**3


def test_real_install_transcript():
    """`Installed` is a separate event rather than silence before the package list."""
    kinds = [e.kind for e in _events("uv_install.txt")]
    assert kinds == [RESOLVED, DOWNLOAD_START, DOWNLOAD_DONE, PREPARED, INSTALLED, PACKAGE]


def test_real_dry_run_transcript_yields_every_pinned_package():
    events = _events("uv_dry_run.txt")
    would = [e for e in events if e.kind == WOULD_DOWNLOAD]
    packages = [e.name for e in events if e.kind == PACKAGE]
    assert would[0].count == 8
    assert len(packages) == 14
    assert "scipy==1.18.1" in packages


def test_small_packages_produce_no_download_lines():
    """Measured: `six` and `packaging` emitted no `Downloading` line with --no-cache.

    Summing those lines would systematically undercount, so the total comes
    from PyPI and `Prepared` signals 100% completion.
    """
    text = "Resolved 2 packages in 372ms\nPrepared 2 packages in 239ms\n"
    events = [e for e in (parse_line(line) for line in text.splitlines()) if e]
    assert not any(e.kind == DOWNLOAD_START for e in events)
