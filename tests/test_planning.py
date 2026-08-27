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


# --- Important I2: katalog w korzeniu dysku nie ma "obok" ---


def test_source_at_a_drive_root_is_never_probed_nor_written_into(tmp_path, monkeypatch):
    """`Path('F:/').parent` to znowu `Path('F:/')`. Uzasadnienie z docstringa
    ('sondowany jest rodzic') jest wtedy wprost falszywe: sonda pisze DO
    katalogu zrodlowego, a wynik builda ladowalby w srodku niego — przy
    kolejnej przebudowie kopiowany razem z projektem, wiec EXE puchnie."""
    root = Path(tmp_path.anchor)
    assert root.parent == root, "przeslanka testu: korzen dysku jest wlasnym rodzicem"

    probed: list[Path] = []

    def _spy(path: Path) -> bool:
        probed.append(Path(path))
        return False

    monkeypatch.setattr(planning, "_is_writable", _spy)
    dest = default_dest_dir(root, "Program")

    assert root not in probed, "sonda zapisala plik w katalogu zrodlowym uzytkownika"
    assert dest.parent != root, "wynik builda wladowal sie do katalogu zrodlowego"


# --- Important I3: 40 MB EXE nie ma sie zaczac wysylac do chmury ---


def test_cloud_synced_parent_loses_to_a_local_folder(tmp_path, monkeypatch):
    onedrive = tmp_path / "OneDrive"
    root = onedrive / "Dokumenty" / "projekt"
    root.mkdir(parents=True)
    local_desktop = tmp_path / "Pulpit"
    local_desktop.mkdir()

    monkeypatch.setenv("OneDrive", str(onedrive))
    monkeypatch.setattr(planning, "_desktop_dir", lambda: local_desktop)

    dest = default_dest_dir(root, "Program")
    assert dest.parent == local_desktop


def test_cloud_folder_is_still_used_when_there_is_no_local_alternative(tmp_path, monkeypatch):
    """Chmura jest gorsza niz dysk lokalny, ale nieskonczenie lepsza niz brak
    miejsca docelowego. Odrzucenie wszystkich kandydatow to regres."""
    onedrive = tmp_path / "OneDrive"
    root = onedrive / "Dokumenty" / "projekt"
    root.mkdir(parents=True)

    monkeypatch.setenv("OneDrive", str(onedrive))
    monkeypatch.setattr(planning, "_desktop_dir", lambda: None)
    monkeypatch.setattr(planning, "_home_dir", lambda: onedrive / "Dokumenty")

    dest = default_dest_dir(root, "Program")
    assert dest.parent == root.parent


def test_a_folder_merely_named_like_a_project_is_not_treated_as_cloud(tmp_path, monkeypatch):
    root = tmp_path / "dropbox-klon" / "projekt"
    root.mkdir(parents=True)
    monkeypatch.delenv("OneDrive", raising=False)
    dest = default_dest_dir(root, "Program")
    assert dest.parent == root.parent


# --- Important I4: Pulpit bierze sie z Windows, nie ze zgadywania nazwy ---


def test_desktop_comes_from_the_known_folder_not_from_a_guessed_name(tmp_path, monkeypatch):
    r"""Przy OneDrive Known Folder Move (domyslny polski OOBE) pulpit lezy w
    `%USERPROFILE%\OneDrive\Pulpit`, a `~/Desktop` moze nie istniec. Stara
    wersja robila wtedy `mkdir` niewidocznego katalogu i raportowala SUKCES."""
    moved = tmp_path / "OneDrive" / "Pulpit"
    moved.mkdir(parents=True)
    root = _make(tmp_path / "p", {"main.py": ""})

    monkeypatch.setattr(planning, "_known_folder_desktop", lambda: moved)
    monkeypatch.setattr(planning, "_is_writable", lambda p: Path(p) != root.parent)

    dest = default_dest_dir(root, "Program")
    assert dest.parent == moved


def test_fallback_never_points_at_a_directory_that_does_not_exist(tmp_path, monkeypatch):
    """`_collect_artifact` robi `mkdir(parents=True)`. Katalog wskazany na
    slepo powstanie i EXE zniknie z pola widzenia uzytkownika przy buildzie
    zameldowanym jako udany."""
    root = _make(tmp_path / "p", {"main.py": ""})
    home = tmp_path / "dom"
    home.mkdir()

    monkeypatch.setattr(planning, "_known_folder_desktop", lambda: tmp_path / "nie-ma-takiego")
    monkeypatch.setattr(planning, "_home_dir", lambda: home)
    monkeypatch.setattr(planning, "_is_writable", lambda p: Path(p) != root.parent)

    dest = default_dest_dir(root, "Program")
    assert dest.parent.exists()
    assert dest.parent == home


def test_the_dead_pulpit_arm_is_gone(tmp_path, monkeypatch):
    """Na dysku pulpit nazywa sie zawsze `Desktop` — `Pulpit` to nazwa
    wyswietlana z `desktop.ini`. Zgadywanie `~/Pulpit` nie trafialo nigdy."""
    root = _make(tmp_path / "p", {"main.py": ""})
    home = tmp_path / "dom"
    (home / "Desktop").mkdir(parents=True)

    monkeypatch.setattr(planning, "_known_folder_desktop", lambda: None)
    monkeypatch.setattr(planning, "_home_dir", lambda: home)
    monkeypatch.setattr(planning, "_is_writable", lambda p: Path(p) != root.parent)

    dest = default_dest_dir(root, "Program")
    assert dest.parent == home / "Desktop"


# --- Minor M14: Pulpit jest odpytywany raz, nie dwa razy ---


def test_the_desktop_is_located_only_once(tmp_path, monkeypatch):
    """Kazde pytanie o Pulpit to wywolanie Win32 `SHGetKnownFolderPath`, a
    kazdy kandydat to jeszcze sonda zapisywalnosci — czyli, gdy Pulpit lezy w
    OneDrive, zdarzenie synchronizacji. `default_dest_dir` woli policzyc to
    raz: sciezka fallbacku pytala o Pulpit po raz drugi."""
    root = _make(tmp_path / "p", {"main.py": ""})
    calls: list[int] = []

    def _counted() -> Path:
        calls.append(1)
        return tmp_path / "pulpit"

    monkeypatch.setattr(planning, "_desktop_dir", _counted)
    monkeypatch.setattr(planning, "_is_writable", lambda _p: False)

    default_dest_dir(root, "Program")

    assert len(calls) == 1, f"Pulpit odpytany {len(calls)} razy"


# --- odrocze minor M8 (Task 15): podglad planu nie ma ruszac chmury ---


def test_cloud_candidate_is_rejected_without_writing_a_probe_file(tmp_path, monkeypatch):
    """Sonda zapisywalnosci pisala do OneDrive'a katalog, ktory i tak odpadal.

    Kolejnosc byla taka: najpierw zapis probny, potem pytanie „czy to chmura".
    Dla projektu trzymanego w OneDrive kazdy podglad planu w GUI tworzyl i
    kasowal plik w katalogu synchronizowanym — czyli zdarzenie wysylki za
    kazdym razem, gdy uzytkownik tylko patrzy na ekran 2. Pytanie o chmure
    jest darmowe i idzie teraz pierwsze.
    """
    onedrive = tmp_path / "OneDrive"
    root = onedrive / "Dokumenty" / "projekt"
    root.mkdir(parents=True)
    desktop = tmp_path / "Pulpit"
    desktop.mkdir()
    monkeypatch.setattr(planning, "_desktop_dir", lambda: desktop)

    probed: list[Path] = []

    def _spy(path: Path) -> bool:
        probed.append(Path(path))
        return True

    monkeypatch.setattr(planning, "_is_writable", _spy)
    dest = default_dest_dir(root, "Program")

    assert onedrive / "Dokumenty" not in probed, "sonda zapisala plik w katalogu w chmurze"
    assert dest.parent == desktop
