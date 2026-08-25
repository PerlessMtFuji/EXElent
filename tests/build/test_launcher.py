import ast

from exelent.build.launcher import LAUNCHER_FILENAME, render_launcher
from exelent.models import AppKind, OutputMode


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
    code = render_launcher('zly"; import os', AppKind.CONSOLE, OutputMode.ONEFILE)
    ast.parse(code)
