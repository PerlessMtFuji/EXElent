import os
from pathlib import Path

import pytest

from exelent import planning
from exelent.analysis.project import analyze_project
from exelent.models import AppKind, OutputMode
from exelent.planning import default_dest_dir, make_plan


def _make(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_plan_uses_analysis_defaults(tmp_path):
    root = _make(tmp_path / "kalkulator", {"main.py": "print(1)"})
    plan = make_plan(analyze_project(root))
    assert plan.entry.name == "main.py"
    assert plan.exe_name == "kalkulator"
    assert plan.app_kind is AppKind.CONSOLE


def test_overrides_win_over_analysis(tmp_path):
    root = _make(tmp_path / "p", {"main.py": "print(1)", "inny.py": "print(2)"})
    plan = make_plan(
        analyze_project(root),
        entry=root / "inny.py",
        exe_name="Moj Program",
        app_kind=AppKind.WINDOWED,
        output_mode=OutputMode.ONEDIR,
    )
    assert plan.entry.name == "inny.py"
    assert plan.exe_name == "Moj Program"
    assert plan.app_kind is AppKind.WINDOWED
    assert plan.output_mode is OutputMode.ONEDIR


def test_optional_dependencies_are_excluded_from_packages(tmp_path):
    code = "try:\n    import numpy\nexcept ImportError:\n    numpy = None\nimport requests"
    root = _make(tmp_path / "p", {"main.py": code})
    plan = make_plan(analyze_project(root))
    assert "requests" in plan.packages
    assert "numpy" not in plan.packages


def test_default_dest_dir_sits_next_to_source(tmp_path):
    root = _make(tmp_path / "kalkulator", {"main.py": ""})
    dest = default_dest_dir(root, "Kalkulator")
    assert dest.parent == root.parent
    assert dest.name == "Kalkulator-EXE"


def test_dest_falls_back_to_desktop_when_source_readonly(tmp_path, monkeypatch):
    root = _make(tmp_path / "p", {"main.py": ""})
    monkeypatch.setattr("exelent.planning._is_writable", lambda _p: False)
    dest = default_dest_dir(root, "Program")
    assert "Desktop" in str(dest) or "Pulpit" in str(dest)


def test_invalid_exe_name_characters_are_replaced(tmp_path):
    root = _make(tmp_path / "p", {"main.py": ""})
    plan = make_plan(analyze_project(root), exe_name="a/b:c*d?")
    assert not set(plan.exe_name) & set('/\\:*?"<>|')


def test_data_files_are_carried_into_plan(tmp_path):
    root = _make(tmp_path / "p", {"main.py": "", "dane.json": "{}"})
    plan = make_plan(analyze_project(root))
    assert any(p.name == "dane.json" for p in plan.data_files)


# --- hidden_imports come from the analysis, not from a second computation ---


def test_hidden_imports_are_taken_from_the_analysis(tmp_path):
    """Task 8 already computes hidden imports; planning must reuse them.

    The plan's sketch recomputed them from `{p: "" for p in scan.py_files}`,
    i.e. from empty file bodies, which can only ever yield an empty tuple.
    """
    code = "import importlib\nimportlib.import_module('ukryty_modul')\n"
    root = _make(tmp_path / "p", {"main.py": code})
    analysis = analyze_project(root)
    assert analysis.hidden_imports == ("ukryty_modul",)
    assert make_plan(analysis).hidden_imports == ("ukryty_modul",)


def test_make_plan_without_entry_raises_value_error(tmp_path):
    root = _make(tmp_path / "pusty", {})
    root.mkdir(parents=True, exist_ok=True)
    analysis = analyze_project(root)
    assert analysis.entry is None
    with pytest.raises(ValueError):
        make_plan(analysis)


# --- the writability probe must not litter the user's folder (spec section 7) ---


def test_writability_probe_leaves_nothing_behind(tmp_path):
    assert planning._is_writable(tmp_path) is True
    assert list(tmp_path.iterdir()) == []


def test_writability_probe_never_touches_an_existing_file(tmp_path):
    """A fixed probe name silently overwrites and then DELETES a user file
    that happens to carry that name. The probe must never collide."""
    victim = tmp_path / ".exelent-write-test"
    victim.write_text("dane uzytkownika", encoding="utf-8")

    assert planning._is_writable(tmp_path) is True

    assert victim.exists(), "sonda skasowala istniejacy plik uzytkownika"
    assert victim.read_text(encoding="utf-8") == "dane uzytkownika"


@pytest.mark.skipif(not hasattr(os, "O_TEMPORARY"), reason="delete-on-close is a Windows facility")
def test_writability_probe_is_removed_even_if_our_cleanup_never_runs(tmp_path, monkeypatch):
    """Stands in for "the process died between creating and removing the probe".

    With `os.unlink` disabled, only a kernel-level delete-on-close can keep
    the folder clean.
    """

    def _never(*_args, **_kwargs):
        raise OSError("celowo zablokowany unlink")

    monkeypatch.setattr(planning.os, "unlink", _never)

    assert planning._is_writable(tmp_path) is True
    assert list(tmp_path.iterdir()) == []


def test_writability_probe_reports_false_for_a_missing_directory(tmp_path):
    assert planning._is_writable(tmp_path / "nie-ma-takiego") is False
