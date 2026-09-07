from pathlib import Path

from exelent.build.entrymodule import resolve_entry
from exelent.build.pyinstaller import build_arguments, materialize_entry_alias
from exelent.models import AppKind, BuildPlan, OutputMode


def _plan(**kwargs):
    base = {
        "root": Path("C:/src"),
        "entry": Path("C:/src/main.py"),
        "app_kind": AppKind.CONSOLE,
        "output_mode": OutputMode.ONEFILE,
        "exe_name": "Kalkulator",
        "dest_dir": Path("C:/out"),
    }
    base.update(kwargs)
    return BuildPlan(**base)


def test_upx_is_always_disabled():
    args = build_arguments(_plan(), Path("C:/w"), Path("C:/w/_exelent_launcher.py"), None)
    assert "--noupx" in args


def test_onefile_flag():
    args = build_arguments(_plan(), Path("C:/w"), Path("C:/w/l.py"), None)
    assert "--onefile" in args and "--onedir" not in args


def test_onedir_flag():
    plan = _plan(output_mode=OutputMode.ONEDIR)
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    assert "--onedir" in args and "--onefile" not in args


def test_onedir_places_contents_next_to_exe():
    """A04: `--contents-directory .` kladzie zasoby obok EXE, nie w `_internal`,
    zeby open('config.json') je znalazl przy cwd = katalog EXE."""
    plan = _plan(output_mode=OutputMode.ONEDIR)
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    assert args[args.index("--contents-directory") + 1] == "."


def test_onefile_has_no_contents_directory():
    args = build_arguments(_plan(), Path("C:/w"), Path("C:/w/l.py"), None)
    assert "--contents-directory" not in args


def test_windowed_app_hides_console():
    plan = _plan(app_kind=AppKind.WINDOWED)
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    assert "--windowed" in args


def test_console_app_keeps_console():
    args = build_arguments(_plan(), Path("C:/w"), Path("C:/w/l.py"), None)
    assert "--console" in args


def test_exe_name_is_passed():
    args = build_arguments(_plan(), Path("C:/w"), Path("C:/w/l.py"), None)
    assert args[args.index("--name") + 1] == "Kalkulator"


def test_entry_module_is_a_hidden_import():
    args = build_arguments(_plan(), Path("C:/w"), Path("C:/w/l.py"), None)
    assert "--hidden-import" in args
    assert "main" in args


def test_root_dunder_main_collects_a_safe_alias_not_dunder_main():
    """Root `__main__.py`: zbierana i uruchamiana nazwa to bezpieczny alias,
    bo `__main__` zderza sie z launcherem w zamrozonym EXE (B03)."""
    plan = _plan(root=Path("C:/src"), entry=Path("C:/src/__main__.py"))
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    assert "_exelent_main" in args
    assert "__main__" not in args


def test_materialize_entry_alias_copies_dunder_main_to_a_safe_name(tmp_path):
    """Backend kopiuje `__main__.py` pod nazwe aliasu z kontraktu, zachowujac
    bajty (a wiec kodowanie). Zwykly skrypt: brak aliasu = brak kopii (B03)."""
    (tmp_path / "__main__.py").write_bytes(b"print('cze\xc5\x9b\xc4\x87')\n")
    spec = resolve_entry(tmp_path, Path("__main__.py"))
    materialize_entry_alias(spec)
    assert (tmp_path / "_exelent_main.py").read_bytes() == b"print('cze\xc5\x9b\xc4\x87')\n"

    (tmp_path / "main.py").write_text("print(1)", encoding="utf-8")
    materialize_entry_alias(resolve_entry(tmp_path, Path("main.py")))
    assert not (tmp_path / "_main.py").exists()


def test_extra_hidden_imports_are_included():
    plan = _plan(hidden_imports=("requests",))
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    assert "requests" in args


def test_icon_is_passed_when_present():
    args = build_arguments(_plan(), Path("C:/w"), Path("C:/w/l.py"), Path("C:/w/i.ico"))
    assert args[args.index("--icon") + 1] == str(Path("C:/w/i.ico"))


def test_launcher_is_the_last_argument():
    launcher = Path("C:/w/_exelent_launcher.py")
    args = build_arguments(_plan(), Path("C:/w"), launcher, None)
    assert args[-1] == str(launcher)


def test_data_files_point_to_workspace_copy_not_user_folder():
    """R5: --add-data must reference the workspace copy of a data file, not
    the path inside the user's original directory — the build must never
    need to read from the user's folder while running."""
    plan = _plan(data_files=(Path("C:/src/assets/img.png"),))
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    # Cel zachowuje katalog `assets` (A04), nie splaszcza do korzenia.
    expected = f"{Path('C:/w/assets/img.png')};assets"
    assert args[args.index("--add-data") + 1] == expected
    assert "C:\\src" not in args[args.index("--add-data") + 1]


def test_root_level_data_file_maps_to_bundle_root():
    plan = _plan(data_files=(Path("C:/src/config.json"),))
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    expected = f"{Path('C:/w/config.json')};."
    assert args[args.index("--add-data") + 1] == expected


def test_nested_data_file_preserves_relative_layout():
    plan = _plan(data_files=(Path("C:/src/pkg/data/config.json"),))
    args = build_arguments(plan, Path("C:/w"), Path("C:/w/l.py"), None)
    # `assets/nested.json -> assets/nested.json`: cel to katalog `pkg/data`.
    expected = f"{Path('C:/w/pkg/data/config.json')};pkg/data"
    assert args[args.index("--add-data") + 1] == expected
