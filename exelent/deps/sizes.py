"""How much space it takes in the EXE and in downloads: two different numbers.

DOWNLOAD size comes from resolved versions, cache misses, and PyPI (tasks
16–17). EXE size is an interval estimate because PyInstaller discards code
that is unused: the same `pandas` weighs differently in a script reading one
CSV and in an application using half its API.

Issue 7 says precisely that invented numbers mislead. Every entry therefore
carries `measured`: a measurement date or the word "temporary". Task 15
replaces every "temporary" marker with a date.
"""

from __future__ import annotations

import functools
import json
import re
import tempfile
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from packaging.tags import Tag, compatible_tags, cpython_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from exelent.constants import TARGET_PYTHON
from exelent.runtime.env import run_uv
from exelent.runtime.uvlog import PACKAGE, UNCACHED_PACKAGE, WOULD_DOWNLOAD, parse_line

# ABI tag of the wheel the build will actually use: target CPython on 64-bit
# Windows. A wheel for another version or system describes a file that will
# never be downloaded.
_PLATFORM = "win_amd64"
_UV_PLATFORM = "x86_64-pc-windows-msvc"
_PYPI = "https://pypi.org/pypi/{name}/{version}/json"
_MAX_PARALLEL = 8

# Above this many megabytes at the upper bound, size stops being information
# and becomes a warning (together with a note about longer build time).
LARGE_WARNING_MB = 300

# Size of an EXE from an empty `print('x')` script: interpreter, standard
# library, and PyInstaller loader. MEASURED 2026-09-04: 10.5 MB. Included in
# the estimate because the message says "the finished program will take", not
# "packages will add"; without it every estimate was 10 MB too low.
BASE_EXE_MB = 11

# A package is "heavy" above this many megabytes of upper-bound contribution;
# this replaces the old flat `HEAVY_PACKAGES` set.
HEAVY_THRESHOLD_MB = 15


@dataclass(frozen=True)
class Contribution:
    """Package contribution to the finished EXE, in megabytes.

    `measured` is a measurement date in `YYYY-MM-DD` format or the word
    "temporary". `test_every_entry_declares_where_its_number_came_from`
    ensures the field is never empty — source-free numbers are exactly what
    this module was created to prevent.
    """

    low_mb: int
    high_mb: int
    measured: str


# Dated entries are MEASURED with two real builds each (see
# `tests/test_exe_contribution_measurement.py`):
#   - lower end: a script that merely imports the package and touches one
#     item — PyInstaller discards most of the tree,
#   - upper end: a script that actually uses the package, plus 25% headroom.
# The headroom is measured: for the only measured COMBINATION of packages
# (matplotlib + pandas + scipy, 172.4 MB), summed individual measurements were
# about 20% below the result because composition pulls in more than each alone.
#
# `temporary` means NOT MEASURED, an approximate number. `torch`, `tensorflow`,
# and `transformers` remain in this state because measuring them requires
# several gigabytes of downloads and was deliberately skipped.
EXE_CONTRIBUTION: dict[str, Contribution] = {
    "torch": Contribution(300, 900, "provisional"),
    "tensorflow": Contribution(250, 700, "provisional"),
    "transformers": Contribution(60, 200, "provisional"),
    "scipy": Contribution(18, 51, "2026-09-04"),
    "opencv-python": Contribution(53, 67, "2026-09-04"),
    "matplotlib": Contribution(27, 93, "2026-09-04"),
    "pandas": Contribution(20, 26, "2026-09-04"),
    "numpy": Contribution(11, 15, "2026-09-04"),
    "PySide6": Contribution(16, 21, "2026-09-04"),
    "PyQt5": Contribution(10, 36, "2026-09-04"),
    "PyQt6": Contribution(7, 18, "2026-09-04"),
    "librosa": Contribution(94, 119, "2026-09-04"),
    "moviepy": Contribution(49, 62, "2026-09-04"),
}


def _canonical(name: str) -> str:
    """Canonical distribution name (PEP 503): lowercase with `-_.` collapsed."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _base_name(spec: str) -> str:
    """Extract the package name from a complete specification.

    `pandas==2.2.3` -> `pandas`, `uvicorn[standard]>=0.20` -> `uvicorn`.
    Without this, the name-keyed contribution table did not recognize pinned
    versions and estimated `pandas==2.2.3` as zero."""
    return re.split(r"[<>=!~;\[ @]", spec.strip(), maxsplit=1)[0].strip()


# Contribution table keyed by canonical name, so `PySide6>=6.7`,
# `opencv_python`, and `pandas==2.2.3` match bare `PySide6`/`opencv-python`.
_CONTRIBUTION_BY_CANONICAL: dict[str, Contribution] = {
    _canonical(name): contribution for name, contribution in EXE_CONTRIBUTION.items()
}


def _contribution_for(spec: str) -> Contribution | None:
    return _CONTRIBUTION_BY_CANONICAL.get(_canonical(_base_name(spec)))


def is_heavy(package: str) -> bool:
    entry = _contribution_for(package)
    return entry is not None and entry.high_mb >= HEAVY_THRESHOLD_MB


def estimate_exe_size(packages: Iterable[str]) -> tuple[int, int, tuple[str, ...]]:
    """Size interval for the WHOLE EXE and heaviest packages, largest first.

    A package absent from the table adds NOTHING — do not guess its
    contribution. Guessing is exactly what caused issue 7.

    Add `BASE_EXE_MB` to the contribution total because the screen says "the
    finished program will take", and that includes the interpreter and standard
    library.
    """
    known: list[tuple[str, Contribution]] = []
    for spec in packages:
        contribution = _contribution_for(spec)
        if contribution is not None:
            known.append((_base_name(spec), contribution))
    if not known:
        return 0, 0, ()
    low = BASE_EXE_MB + sum(c.low_mb for _name, c in known)
    high = BASE_EXE_MB + sum(c.high_mb for _name, c in known)
    heaviest = tuple(name for name, _c in sorted(known, key=lambda p: -p[1].high_mb))
    return low, high, heaviest


@functools.lru_cache(maxsize=8)
def _target_tags(python_version: str = TARGET_PYTHON, platform: str = _PLATFORM) -> tuple[Tag, ...]:
    """Wheel tags in the same preference order as the target CPython."""
    major, minor = (int(part) for part in python_version.split(".")[:2])
    version = (major, minor)
    exact = tuple(cpython_tags(python_version=version, platforms=[platform]))
    universal = tuple(
        compatible_tags(
            python_version=version, interpreter=f"cp{major}{minor}", platforms=[platform]
        )
    )
    return tuple(dict.fromkeys((*exact, *universal)))


def wheel_size(
    payload: dict, *, python_version: str = TARGET_PYTHON, platform: str = _PLATFORM
) -> int:
    """Size of the file uv will actually download for this version.

    Attempt order: wheel for our ABI and system -> universal wheel
    (`py3-none-any`) -> source archive. An unrecognized response shape yields
    zero rather than an exception: a missing number is tolerable, a background
    exception on screen 2 is not.
    """
    urls = payload.get("urls") or []
    rank = {tag: index for index, tag in enumerate(_target_tags(python_version, platform))}
    compatible: list[tuple[int, dict]] = []
    for candidate in urls:
        if candidate.get("packagetype") != "bdist_wheel":
            continue
        try:
            _name, _version, _build, tags = parse_wheel_filename(candidate.get("filename", ""))
        except (InvalidWheelFilename, TypeError):
            continue
        matches = [rank[tag] for tag in tags if tag in rank]
        if matches:
            compatible.append((min(matches), candidate))
    if compatible:
        _best_rank, best = min(compatible, key=lambda item: item[0])
        return int(best.get("size") or 0)
    for candidate in urls:
        if candidate.get("packagetype") == "sdist":
            return int(candidate.get("size") or 0)
    return 0


def _fetch_release(spec: str, timeout: float) -> dict:
    name, _, version = spec.partition("==")
    with urllib.request.urlopen(_PYPI.format(name=name, version=version), timeout=timeout) as r:
        return json.load(r)


def download_size(specs: Sequence[str], timeout: float = 5.0) -> int:
    """Total size of compatible archives for pinned `name==version` specs.

    Queries run concurrently because eight sequential PyPI round trips would
    keep screen 2 waiting too long. EVERY failure is quiet and yields zero;
    the layer above then uses the table estimate.
    """

    return sum(distribution_sizes(specs, timeout=timeout).values())


def distribution_sizes(specs: Sequence[str], timeout: float = 5.0) -> dict[str, int]:
    """Sizes of target-compatible archives without losing package identity."""

    def one(spec: str) -> tuple[str, int]:
        try:
            return spec, wheel_size(_fetch_release(spec, timeout))
        except (OSError, ValueError, KeyError):
            return spec, 0

    if not specs:
        return {}
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL, len(specs))) as pool:
        return dict(pool.map(one, specs))


@dataclass(frozen=True)
class DownloadPlan:
    specs: tuple[str, ...] = ()
    # The full `specs` tree describes the environment; this list contains only
    # archives uv did not find in cache and will actually download.
    missing_specs: tuple[str, ...] = ()
    would_download: int = 0
    # Network transfer for missing archives. The name remains for compatibility
    # with existing BuildPlan/progress, but does not describe EXE size.
    total_bytes: int = 0
    # Lower bound for the full transitive environment: the sum of compressed,
    # compatible wheel archives. The unpacked environment may be larger, so the
    # UI does not present this value as exact.
    environment_min_bytes: int = 0
    # Components outside project packages. `None` means preflight could not
    # check; False means an actual transfer during the build phase.
    uv_cached: bool | None = None
    python_cached: bool | None = None
    includes_build_tools: bool = False
    # Fingerprint of packages and target used for the result. The UI rejects it
    # after manual changes to modules or the target version.
    request_key: str = ""
    # B12: result status distinguishes a complete result from offline/error.
    # "complete": calculated, "empty": no packages (still OK), "pending":
    # running, "offline": no uv/network, "error": resolver failure,
    # "cancelled": interrupted.
    status: str = "empty"


def _default_run_dry(uv: Path, python: str | Path, packages: Sequence[str], *, cancel=None) -> str:
    # An empty target prevents accidental packages from EXElent's own
    # environment from being included. Version and platform are explicit, so
    # uv resolves wheels for the final Windows/CPython even when EXElent itself
    # runs on another Python version.
    with tempfile.TemporaryDirectory(prefix="exelent-preflight-") as empty_target:
        result = run_uv(
            uv,
            [
                "pip",
                "install",
                "--target",
                empty_target,
                "--python-version",
                str(python),
                "--python-platform",
                _UV_PLATFORM,
                "--dry-run",
                "--verbose",
                "--color",
                "never",
                *packages,
            ],
            cancel=cancel,
        )
    if result.returncode != 0:
        raise ValueError(result.stderr or result.stdout or "uv dry-run failed")
    return result.stderr or ""


def resolve_download_plan(
    uv: Path,
    python: str | Path,
    packages: Sequence[str],
    *,
    run_dry=None,
    measure=None,
    cancel=None,
) -> DownloadPlan:
    """What will actually be downloaded and how large it is.

    `--dry-run` gives the full tree with PINNED versions and the number of
    packages missing from cache. Without the latter, the window would ask
    permission to download a hundred megabytes already on disk.

    Calculate size only when there is something to download. Every failure —
    missing uv, no network, unknown output shape — yields an empty plan and the
    layer above falls back to the table estimate.
    """
    # Only the default runner receives the token: an injected `run_dry` is a
    # stub or external function with its own shape, and adding an argument from
    # outside would change the injection-point contract.
    runner = run_dry or functools.partial(_default_run_dry, cancel=cancel)
    measurer = measure or distribution_sizes
    try:
        text = runner(uv, python, packages)
    except OSError:
        return DownloadPlan(status="offline")
    except ValueError:
        return DownloadPlan(status="error")

    # After cancellation uv returns nothing or half a response. Nobody will see
    # the user-facing numbers anyway, while every PyPI request extends the
    # lifetime of the thread a closing window is waiting for.
    if cancel is not None and cancel.cancelled:
        return DownloadPlan(status="cancelled")

    specs: list[str] = []
    missing: list[str] = []
    would = 0
    for line in text.splitlines():
        event = parse_line(line)
        if event is None:
            continue
        if event.kind == PACKAGE:
            specs.append(event.name)
        elif event.kind == UNCACHED_PACKAGE:
            missing.append(event.name)
        elif event.kind == WOULD_DOWNLOAD:
            would = event.count

    measured = measurer(specs) if specs else {}
    if isinstance(measured, Mapping):
        environment = sum(measured.values())
        transfer = sum(measured.get(spec, 0) for spec in missing) if would else 0
    else:
        # Preserve the injection point for simple stubs from earlier tests. The
        # production measurer returns a map and does not perform two rounds.
        scalar_measurer = cast(Callable[[Sequence[str]], int], measurer)
        environment = cast(int, measured)
        transfer = scalar_measurer(missing) if would and missing else 0

    # Older uv or a changed log format may provide a count without names. Such
    # a result is partial: do not assign cached package sizes to transfer or
    # present a falsely precise value.
    missing_sizes_known = not isinstance(measured, Mapping) or all(
        measured.get(spec, 0) > 0 for spec in missing
    )
    status = "complete" if would == len(missing) and missing_sizes_known else "partial"
    return DownloadPlan(
        specs=tuple(specs),
        missing_specs=tuple(missing),
        would_download=would,
        total_bytes=transfer,
        environment_min_bytes=environment,
        status=status,
    )
