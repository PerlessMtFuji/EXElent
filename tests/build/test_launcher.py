import ast

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
