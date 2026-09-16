"""EXE size and download size are different quantities.

PyInstaller excludes code that the program never touches. That is why a script
using matplotlib, pandas, and scipy produced 26 MB despite a warning about
hundreds of megabytes. A range conveys uncertainty that one number cannot.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

from exelent.deps.sizes import (
    EXE_CONTRIBUTION,
    LARGE_WARNING_MB,
    download_size,
    estimate_exe_size,
    is_heavy,
    resolve_download_plan,
    wheel_size,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_estimate_returns_a_range_not_a_single_number():
    low, high, heaviest = estimate_exe_size(["matplotlib", "pandas", "scipy"])
    assert low < high
    assert heaviest[0] in {"scipy", "pandas", "matplotlib"}


def test_estimate_ignores_packages_we_have_not_measured():
    """A package outside the table gets no guessed contribution.

    Guessing was the cause of issue 7.
    """
    low_alone, high_alone, _ = estimate_exe_size(["pandas"])
    low_with, high_with, _ = estimate_exe_size(["pandas", "some-small-package"])
    assert (low_alone, high_alone) == (low_with, high_with)


def test_estimate_recognises_a_pinned_version():
    """A11: `pandas==2.2.3` must match the same entry as bare `pandas`.

    A versioned key previously produced a zero estimate.
    """
    bare = estimate_exe_size(["pandas"])
    pinned = estimate_exe_size(["pandas==2.2.3"])
    assert pinned == bare
    assert pinned[0] > 0


def test_estimate_recognises_extras_and_case_and_separators():
    assert estimate_exe_size(["PySide6>=6.7"])[0] > 0
    assert estimate_exe_size(["opencv_python==4.9"])[0] > 0
    assert is_heavy("pandas==2.2.3") is True


def test_no_packages_means_no_estimate():
    assert estimate_exe_size([]) == (0, 0, ())


def test_heaviest_packages_come_first():
    """Order packages by measurement rather than intuition.

    Matplotlib includes its backends and weighs over three times as much as
    pandas (measured 2026-09-04: 74.4 MB versus 20.8 MB).
    """
    _low, _high, heaviest = estimate_exe_size(["pandas", "matplotlib"])
    assert heaviest == ("matplotlib", "pandas")


# Entries not yet measured. Measuring them downloads several gigabytes and was
# deliberately deferred. The explicit list prevents unsupported numbers from
# entering silently: an undated entry absent from this list fails the test.
UNMEASURED = frozenset({"torch", "tensorflow", "transformers"})


def test_every_entry_is_either_measured_or_openly_listed_as_not():
    """An entry without provenance is an unsupported guess, as in issue 7."""
    for package, contribution in EXE_CONTRIBUTION.items():
        assert contribution.measured, f"{package} does not identify the source of its numbers"
        if package in UNMEASURED:
            assert contribution.measured == "provisional", (
                f"{package} now has a measurement date; remove it from UNMEASURED"
            )
            continue
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", contribution.measured), (
            f"{package}: value lacks a measurement date; measure it or add it to UNMEASURED."
        )


def test_the_estimate_covers_the_whole_exe_not_just_the_packages():
    """The finished program includes the interpreter.

    Measured 2026-09-04: an empty script produces 10.5 MB.
    """
    low, _high, _heaviest = estimate_exe_size(["numpy"])
    assert low > EXE_CONTRIBUTION["numpy"].low_mb


def test_the_script_from_the_report_falls_inside_its_own_estimate():
    """Success criterion: the finished program fits the pre-build estimate.

    Measured 2026-09-04 on a real build of the issue-7 script
    (pandas + scipy.stats + pyplot.savefig): 172.4 MB.
    """
    low, high, _heaviest = estimate_exe_size(["matplotlib", "pandas", "scipy"])
    assert low <= 172.4 <= high, f"range {low}-{high} MB excludes measured 172.4 MB"


def test_large_threshold_matches_the_spec():
    assert LARGE_WARNING_MB == 300


# --- exact download size from PyPI ---


def test_wheel_size_prefers_the_matching_windows_wheel():
    """A wheel for another Python version or OS is not our wheel."""
    payload = json.loads((FIXTURES / "pypi_scipy.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 36700160


def test_wheel_size_falls_back_to_a_pure_python_wheel():
    payload = json.loads((FIXTURES / "pypi_pure.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 11053


def test_wheel_size_accepts_abi3_but_rejects_a_newer_cpython_wheel():
    payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "filename": "demo-1.0-cp313-cp313-win_amd64.whl",
                "size": 99,
            },
            {
                "packagetype": "bdist_wheel",
                "filename": "demo-1.0-cp39-abi3-win_amd64.whl",
                "size": 42,
            },
            {
                "packagetype": "bdist_wheel",
                "filename": "demo-1.0-py3-none-any.whl",
                "size": 10,
            },
        ]
    }
    assert wheel_size(payload, python_version="3.12") == 42


def test_wheel_size_falls_back_to_sdist_as_a_last_resort():
    payload = json.loads((FIXTURES / "pypi_sdist_only.json").read_text(encoding="utf-8"))
    assert wheel_size(payload) == 90000


def test_wheel_size_of_empty_payload_is_zero():
    assert wheel_size({"urls": []}) == 0


def test_download_size_degrades_quietly_when_pypi_is_unreachable(monkeypatch):
    """Download size is optional information and must not block a build.

    This is the same rule that governs `recent.py`.
    """
    import exelent.deps.sizes as sizes_module

    def boom(spec, timeout):
        raise OSError("no network")

    monkeypatch.setattr(sizes_module, "_fetch_release", boom)
    assert download_size(["scipy==1.18.1", "numpy==2.5.2"]) == 0


# --- download plan: what uv will actually fetch after accounting for cache ---


def test_dry_run_yields_pinned_specs_and_the_missing_count():
    transcript = (FIXTURES.parent.parent / "runtime" / "fixtures" / "uv_dry_run.txt").read_text(
        encoding="utf-8"
    )
    plan = resolve_download_plan(
        uv=Path("uv.exe"),
        python=Path("python.exe"),
        packages=["matplotlib", "pandas", "scipy"],
        run_dry=lambda *_a, **_k: transcript,
        measure=lambda specs, **_k: 0,
    )
    assert plan.would_download == 8
    assert "scipy==1.18.1" in plan.specs
    assert len(plan.specs) == 14
    assert plan.status == "partial", "an old transcript without cache names cannot claim completeness"


def test_transfer_measures_only_uncached_specs_but_environment_covers_the_tree():
    transcript = (
        "DEBUG Identified uncached distribution: scipy==1.18.1\n"
        "Resolved 2 packages in 12ms\n"
        "Would download 1 package\n"
        " + numpy==2.5.2\n"
        " + scipy==1.18.1"
    )
    measured = {"numpy==2.5.2": 12, "scipy==1.18.1": 36}
    plan = resolve_download_plan(
        uv=Path("uv.exe"),
        python="3.12",
        packages=["scipy"],
        run_dry=lambda *_a, **_k: transcript,
        measure=lambda specs: {spec: measured[spec] for spec in specs},
    )
    assert plan.status == "complete"
    assert plan.missing_specs == ("scipy==1.18.1",)
    assert plan.total_bytes == 36
    assert plan.environment_min_bytes == 48


def test_nothing_to_download_when_everything_is_cached():
    """A zero-megabyte consent prompt teaches users to click without reading.

    The zero must therefore be accurate.
    """
    transcript = "Resolved 3 packages in 12ms\nWould download 0 packages\n + six==1.17.0\n"
    plan = resolve_download_plan(
        uv=Path("uv.exe"),
        python=Path("python.exe"),
        packages=["six"],
        run_dry=lambda *_a, **_k: transcript,
        measure=lambda specs, **_k: 999,
    )
    assert plan.would_download == 0
    assert plan.total_bytes == 0


def test_resolution_failure_degrades_to_an_empty_plan():
    def boom(*_args, **_kwargs):
        raise OSError("uv did not start")

    plan = resolve_download_plan(
        uv=Path("uv.exe"), python=Path("python.exe"), packages=["scipy"], run_dry=boom
    )
    assert plan.specs == ()
    assert plan.total_bytes == 0
    assert plan.status == "offline"


def test_resolver_rejection_is_not_mislabeled_as_offline():
    def rejected(*_args, **_kwargs):
        raise ValueError("requirements are unsatisfiable")

    plan = resolve_download_plan(
        uv=Path("uv.exe"), python="3.12", packages=["demo"], run_dry=rejected
    )
    assert plan.status == "error"


def test_dry_run_receives_the_cancel_token(monkeypatch):
    """The token must reach `uv` or preflight cancellation stops at the layer boundary."""
    from exelent.build.backend import CancelToken
    from exelent.deps import sizes as sizes_module

    seen = {}

    def fake_run_uv(uv, args, *, cwd=None, cancel=None):
        seen["cancel"] = cancel
        seen["args"] = args
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(sizes_module, "run_uv", fake_run_uv)
    token = CancelToken()

    resolve_download_plan(Path("uv.exe"), "3.12", ["six"], cancel=token)

    assert seen["cancel"] is token
    assert "--python-version" in seen["args"]
    assert seen["args"][seen["args"].index("--python-version") + 1] == "3.12"
    assert "--python-platform" in seen["args"]
    assert "--target" in seen["args"]
