import ast
import ctypes
import os
import sys
import types
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


def _exec_launcher_kind(app_kind: AppKind) -> dict:
    code = render_launcher("program", app_kind, OutputMode.ONEDIR)
    ns: dict = {}
    exec(compile(code, "<generated launcher>", "exec"), ns)  # noqa: S102
    return ns


class _FakeRunpy:
    """Podmiana za `runpy` w przestrzeni nazw launchera.

    Program uzytkownika nie moze naprawde wystartowac w tescie, a to wlasnie
    sposob jego zakonczenia — normalny, `sys.exit` albo wyjatek — decyduje o
    tym, czy launcher zdazy jeszcze zatrzymac okno.
    """

    def __init__(self, raises: BaseException | None = None) -> None:
        self.raises = raises
        self.modules: list[str] = []

    def run_module(self, name, run_name=None, alter_sys=False):
        self.modules.append(name)
        if self.raises is not None:
            raise self.raises


def _arm_launcher(ns, monkeypatch, tmp_path, *, owns_console=True, raises=None) -> list[str]:
    """Uzbraja `main()` do uruchomienia w tescie i oddaje liste zadanych pytan.

    Kazde wywolanie `input()` dopisuje tu swoja zachete, wiec dlugosc listy
    jest wprost liczba pauz, ktore zobaczy uzytkownik.
    """
    prompts: list[str] = []
    ns["_register_vendored_dll_dirs"] = lambda: None
    ns["_set_working_directory"] = lambda: None
    ns["_owns_console"] = lambda: owns_console
    ns["runpy"] = _FakeRunpy(raises)
    ns["_error_path"] = lambda: str(tmp_path / "EXElent-blad.txt")
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt))
    return prompts


def test_console_launcher_waits_after_a_successful_run(monkeypatch, tmp_path):
    """Dwuklik z Eksploratora daje programowi wlasne okno konsoli, ktore Windows
    zamyka razem z procesem. Bez pauzy uzytkownik widzi tylko mrugniecie."""
    ns = _exec_launcher_kind(AppKind.CONSOLE)
    prompts = _arm_launcher(ns, monkeypatch, tmp_path, owns_console=True)

    ns["main"]()

    assert len(prompts) == 1


def test_console_launcher_does_not_wait_when_it_shares_the_console(monkeypatch, tmp_path):
    """Uruchomienie z CMD, z potoku albo ze skryptu: okno nie znika po wyjsciu,
    wiec pauza tylko zawieszalaby cudza automatyzacje."""
    ns = _exec_launcher_kind(AppKind.CONSOLE)
    prompts = _arm_launcher(ns, monkeypatch, tmp_path, owns_console=False)

    ns["main"]()

    assert prompts == []


def test_console_launcher_waits_exactly_once_after_a_crash(monkeypatch, tmp_path):
    """Awaria to jedyny moment, gdy tresc okna jest naprawde potrzebna — i
    dokladnie jedno nacisniecie Entera ma je zamknac."""
    ns = _exec_launcher_kind(AppKind.CONSOLE)
    prompts = _arm_launcher(
        ns, monkeypatch, tmp_path, owns_console=True, raises=RuntimeError("bum")
    )

    with pytest.raises(SystemExit) as exit_info:
        ns["main"]()

    assert exit_info.value.code == 1
    assert len(prompts) == 1


def test_console_launcher_waits_after_the_program_calls_sys_exit(monkeypatch, tmp_path):
    """`sys.exit(2)` w kodzie uzytkownika to normalne zakonczenie, nie awaria:
    kod wyjscia musi przejsc na wierzch nietkniety, a okno ma zostac."""
    ns = _exec_launcher_kind(AppKind.CONSOLE)
    prompts = _arm_launcher(ns, monkeypatch, tmp_path, owns_console=True, raises=SystemExit(2))

    with pytest.raises(SystemExit) as exit_info:
        ns["main"]()

    assert exit_info.value.code == 2
    assert len(prompts) == 1


def test_windowed_launcher_never_waits_for_a_keypress(monkeypatch, tmp_path):
    """Program okienkowy nie ma konsoli, w ktorej moglby o cokolwiek zapytac —
    `input()` rzucilby tam wyjatkiem zamiast na cokolwiek poczekac."""
    ns = _exec_launcher_kind(AppKind.WINDOWED)
    prompts = _arm_launcher(ns, monkeypatch, tmp_path, owns_console=True)

    ns["main"]()

    assert prompts == []


def _fake_ctypes(count=None, error=None, windll=True):
    module = types.ModuleType("ctypes")
    module.c_uint = ctypes.c_uint

    def get_console_process_list(buffer, size):
        if error is not None:
            raise error
        return count

    if windll:
        module.windll = types.SimpleNamespace(
            kernel32=types.SimpleNamespace(GetConsoleProcessList=get_console_process_list)
        )
    return module


def test_owns_console_when_no_one_else_is_attached(monkeypatch):
    monkeypatch.setitem(sys.modules, "ctypes", _fake_ctypes(count=1))

    assert _exec_launcher_kind(AppKind.CONSOLE)["_owns_console"]() is True


def test_does_not_own_console_shared_with_a_shell(monkeypatch):
    """Powloka, ktora nas odpalila, liczy sie jako drugi proces przy konsoli."""
    monkeypatch.setitem(sys.modules, "ctypes", _fake_ctypes(count=2))

    assert _exec_launcher_kind(AppKind.CONSOLE)["_owns_console"]() is False


def test_does_not_own_console_without_the_windows_api(monkeypatch):
    """Poza Windowsem `ctypes.windll` nie istnieje. Brak odpowiedzi znaczy
    'nie zatrzymuj', bo zawieszony program jest gorszy od zamknietego okna."""
    monkeypatch.setitem(sys.modules, "ctypes", _fake_ctypes(windll=False))

    assert _exec_launcher_kind(AppKind.CONSOLE)["_owns_console"]() is False


def test_does_not_own_console_when_the_api_call_fails(monkeypatch):
    monkeypatch.setitem(sys.modules, "ctypes", _fake_ctypes(error=OSError("brak konsoli")))

    assert _exec_launcher_kind(AppKind.CONSOLE)["_owns_console"]() is False
