"""PyInstaller may finish with exit code 0 and still ship an EXE without the
user's code -- see `dropped_project_modules` for the mechanism."""

from pathlib import Path

from exelent.build.pyinstaller import dropped_project_modules

WORKSPACE = Path(r"C:\Users\x\AppData\Local\EXElent\b\1acec5c3\src")


def test_module_from_the_project_is_reported():
    lines = [
        r"6856 INFO: Building PYZ (ZlibArchive) ...\build\test\PYZ-00.pyz",
        (
            r"6861 WARNING: Sytnax error while compiling "
            r"C:\Users\x\AppData\Local\EXElent\b\1acec5c3\src\test.py"
        ),
        r"7033 INFO: Building PYZ (ZlibArchive) ... completed successfully.",
    ]
    assert dropped_project_modules(lines, WORKSPACE) == ("test.py",)


def test_module_from_site_packages_is_ignored():
    """A third-party module written for another Python is exactly the case
    PyInstaller's own `continue` is there for. Failing the build over it would
    block builds that work, so only the user's own files count."""
    lines = [
        (
            r"6861 WARNING: Sytnax error while compiling C:\Users\x\AppData\Local"
            r"\EXElent\b\1acec5c3\venv\Lib\site-packages\old_pkg\py2only.py"
        ),
    ]
    assert dropped_project_modules(lines, WORKSPACE) == ()


def test_clean_log_reports_nothing():
    lines = ["6856 INFO: Building PYZ (ZlibArchive) completed successfully."]
    assert dropped_project_modules(lines, WORKSPACE) == ()


def test_path_casing_does_not_hide_the_module():
    """Windows paths are case-insensitive; a casing difference between our
    workspace path and PyInstaller's log line must not silently switch this
    guard off and hand the user the broken EXE again."""
    lines = [
        (
            r"6861 WARNING: Sytnax error while compiling "
            r"c:\users\x\appdata\local\exelent\b\1acec5c3\src\test.py"
        ),
    ]
    assert dropped_project_modules(lines, WORKSPACE) == ("test.py",)


def test_survives_pyinstaller_fixing_its_typo():
    """The warning ships with "Sytnax" misspelled (PyInstaller 6.16.0,
    building/utils.py). Matching only the typo would make this guard fall
    silently dead the day upstream corrects it."""
    lines = [
        (
            r"6861 WARNING: Syntax error while compiling "
            r"C:\Users\x\AppData\Local\EXElent\b\1acec5c3\src\test.py"
        ),
    ]
    assert dropped_project_modules(lines, WORKSPACE) == ("test.py",)
