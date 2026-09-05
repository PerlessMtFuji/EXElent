import ast
import os
import sys
from pathlib import Path

import pytest

from exelent.build.launcher import LAUNCHER_FILENAME, render_launcher
from exelent.models import AppKind, OutputMode


def _render_and_exec(entry_module: str) -> dict:
    """Render the launcher for `entry_module` and execute it in an isolated namespace.

    A plain `exec(code, ns)` never triggers `main()`: with no "__name__" key
    supplied, name resolution for the bare `__name__` in the template's
    `if __name__ == "__main__":` guard falls through to the auto-installed
    `__builtins__` module object and resolves to the string "builtins", not
    "__main__" -- so this only exercises the module's top-level assignments
    and definitions (in particular ENTRY_MODULE), never chdir()s the test
    process or attempts to actually run a module.
    """
    code = render_launcher(entry_module, AppKind.CONSOLE, OutputMode.ONEFILE)
    ast.parse(code)
    ns: dict = {}
    # Executing our own generated code to verify it round-trips correctly.
    exec(compile(code, "<generated launcher>", "exec"), ns)  # noqa: S102
    return ns


def test_generated_launcher_is_valid_python():
    code = render_launcher("main", AppKind.WINDOWED, OutputMode.ONEFILE)
    ast.parse(code)


def test_launcher_runs_entry_module_as_main():
    code = render_launcher("kalkulator", AppKind.CONSOLE, OutputMode.ONEDIR)
    assert '"kalkulator"' in code
    assert 'run_name="__main__"' in code


def test_onefile_readonly_chdir_to_bundle():
    code = render_launcher("main", AppKind.CONSOLE, OutputMode.ONEFILE)
    assert "_MEIPASS" in code


def test_onedir_chdir_to_executable_folder():
    code = render_launcher("main", AppKind.CONSOLE, OutputMode.ONEDIR)
    assert "sys.executable" in code


def test_windowed_launcher_shows_dialog():
    code = render_launcher("main", AppKind.WINDOWED, OutputMode.ONEFILE)
    assert "_show_error_dialog" in code


def test_console_launcher_waits_for_keypress():
    code = render_launcher("main", AppKind.CONSOLE, OutputMode.ONEFILE)
    assert "input(" in code


def test_launcher_filename_is_ascii_and_unlikely_to_collide():
    assert LAUNCHER_FILENAME == "_exelent_launcher.py"
    assert LAUNCHER_FILENAME.isascii()


def test_entry_module_name_is_escaped():
    entry = 'zly"; import os'
    code = render_launcher(entry, AppKind.CONSOLE, OutputMode.ONEFILE)
    ast.parse(code)
    # Parsing alone only checks the symptom (no SyntaxError). The binding
    # property is round-trip identity: after executing the generated source,
    # ENTRY_MODULE must equal the original input exactly -- otherwise the
    # built EXE fails later, further from the cause, with a confusing
    # ModuleNotFoundError.
    ns = _render_and_exec(entry)
    assert ns["ENTRY_MODULE"] == entry


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("plain_module", id="plain"),
        pytest.param("has'single'quotes", id="single-quotes"),
        pytest.param('has"double"quotes', id="double-quotes"),
        pytest.param("has\\backslash", id="backslash"),
        pytest.param("has\nnewline", id="newline"),
        pytest.param("has{braces}here", id="single-braces"),
        pytest.param("has{{double}}braces", id="double-braces"),
        pytest.param('triple"""quote', id="triple-double-quote"),
        pytest.param("Zażółć", id="bmp-polish-diacritics"),
        pytest.param("astral_\U0001f600_emoji", id="astral-character"),
        pytest.param("", id="empty-string"),
    ],
)
def test_entry_module_round_trips_exactly(entry):
    ns = _render_and_exec(entry)
    assert ns["ENTRY_MODULE"] == entry


def _exec_launcher(output_mode: OutputMode = OutputMode.ONEFILE) -> dict:
    code = render_launcher("program", AppKind.CONSOLE, output_mode)
    ns: dict = {}
    exec(compile(code, "<generated launcher>", "exec"), ns)  # noqa: S102
    return ns


def test_launcher_registers_every_vendored_dll_dir(tmp_path, monkeypatch):
    """Regresja: numpy + pandas w jednym programie dawaly EXE, ktore umieralo na
    `DLL load failed while importing _multiarray_umath`.

    delvewheel wektoruje `msvcp140-<hash>.dll` i do `numpy.libs`, i do
    `pandas.libs` — pod ta sama nazwa pliku. PyInstaller rozwiazuje zaleznosci
    binarne po samej nazwie i bierze PIERWSZE trafienie, wiec do paczki trafia
    wylacznie kopia z `pandas.libs`; kopii numpy nie ma tam w ogole.

    W czasie dzialania lata delvewheel w `numpy/__init__.py` dokłada do
    wyszukiwania DLL tylko `numpy.libs`. `pandas.libs` nie dokłada nikt, bo
    pandas jest importowany dopiero PO numpy — i biblioteka lezaca o jeden
    katalog obok jest nieosiagalna.
    """
    base = tmp_path / "bundle"
    (base / "numpy.libs").mkdir(parents=True)
    (base / "pandas.libs").mkdir()
    (base / "numpy").mkdir()  # zwykly pakiet — nie jest katalogiem DLL
    (base / "cos.libs").write_text("nie katalog")

    registered: list[str] = []
    monkeypatch.setattr(os, "add_dll_directory", registered.append, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(base), raising=False)

    _exec_launcher()["_register_vendored_dll_dirs"]()

    assert sorted(Path(p).name for p in registered) == ["numpy.libs", "pandas.libs"]


def test_dll_dirs_are_registered_before_the_program_runs():
    """Kolejnosc jest cala rzecza: rejestracja po pierwszym `import numpy`
    juz niczego nie ratuje."""
    code = render_launcher("program", AppKind.CONSOLE, OutputMode.ONEFILE)
    body = code[code.index("def main()") :]
    assert body.index("_register_vendored_dll_dirs()") < body.index("run_module")


def test_registering_dll_dirs_survives_a_bundle_without_them(monkeypatch):
    """Brak `_MEIPASS` (uruchomienie ze zrodel) i katalog nie do przyjecia nie
    moga wywrocic programu, ktory poza tym dziala."""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    _exec_launcher()["_register_vendored_dll_dirs"]()


def test_a_rejected_dll_dir_does_not_stop_the_program(tmp_path, monkeypatch):
    base = tmp_path / "bundle"
    (base / "numpy.libs").mkdir(parents=True)

    def refuse(path):
        raise OSError("odmowa")

    monkeypatch.setattr(os, "add_dll_directory", refuse, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(base), raising=False)

    _exec_launcher()["_register_vendored_dll_dirs"]()
