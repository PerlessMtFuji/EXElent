"""Generator launchera — punktu wejścia każdego zbudowanego EXE.

Robi trzy rzeczy, których PyInstaller sam nie robi:
1. udostępnia wszystkie wektorowane katalogi `*.libs` przy ładowaniu DLL,
2. ustawia katalog roboczy tak, żeby względne ścieżki w kodzie działały,
3. łapie każdy wyjątek i pokazuje go użytkownikowi zamiast cicho zniknąć,
4. zatrzymuje okno konsoli, które sam sobie otworzył, żeby wynik dało się
   przeczytać po dwukliku z Eksploratora.
"""

from __future__ import annotations

from exelent.models import AppKind, OutputMode

LAUNCHER_FILENAME = "_exelent_launcher.py"

_TEMPLATE = '''\
"""Wygenerowane przez EXElent. Nie edytuj — plik powstaje przy każdym buildzie."""

import os
import runpy
import sys
import traceback

ENTRY_MODULE = {entry}


def _set_working_directory():
{chdir_body}


# Katalogi `*.libs` obok pakietow to konwencja delvewheel — tam laduja
# wektorowane biblioteki natywne (numpy.libs, pandas.libs, scipy.libs...).
_DLL_DIRECTORIES = []


def _register_vendored_dll_dirs():
    """Doklada wszystkie katalogi `*.libs` z paczki do wyszukiwania DLL.

    Bez tego numpy i pandas w jednym programie daja EXE, ktore umiera na
    `DLL load failed while importing _multiarray_umath`. delvewheel wektoruje
    `msvcp140-<hash>.dll` do OBU katalogow, pod ta sama nazwa pliku;
    PyInstaller rozwiazuje zaleznosci binarne po samej nazwie i bierze
    PIERWSZE trafienie, wiec do paczki wchodzi wylacznie kopia z
    `pandas.libs`, a kopii numpy nie ma tam wcale. W czasie dzialania lata
    delvewheel w `numpy/__init__.py` rejestruje tylko `numpy.libs` — pandas
    jest importowany dopiero POZNIEJ, wiec jego katalogu nie rejestruje nikt
    i biblioteka lezaca o jeden katalog obok jest nieosiagalna.

    Rejestracja WSZYSTKICH takich katalogow z gory zdejmuje cala te klase
    bledow, nie tylko pare numpy/pandas: tak samo zderzaja sie scipy,
    matplotlib czy opencv, a kolejnosc importow w cudzym kodzie nie jest
    czyms, co EXElent moze przewidziec.

    Uchwyty zostaja w liscie modulu — ich zamkniecie cofa wpis, wiec musza
    zyc tak dlugo jak program.
    """
    base = getattr(sys, "_MEIPASS", None)
    if not base or not hasattr(os, "add_dll_directory"):
        return
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return
    for name in names:
        path = os.path.join(base, name)
        if not name.endswith(".libs") or not os.path.isdir(path):
            continue
        try:
            _DLL_DIRECTORIES.append(os.add_dll_directory(path))
        except OSError:
            pass


def _error_path():
    base = os.path.dirname(sys.executable)
    return os.path.join(base, "EXElent-blad.txt")


def _save_report(text):
    try:
        with open(_error_path(), "w", encoding="utf-8") as handle:
            handle.write(text)
        return _error_path()
    except OSError:
        return None


def _show_error_dialog(text, saved_to):
    try:
        import tkinter
        from tkinter import scrolledtext

        window = tkinter.Tk()
        window.title("Program zakonczyl sie bledem")
        window.geometry("720x420")
        area = scrolledtext.ScrolledText(window, wrap="word")
        area.insert("1.0", text)
        area.configure(state="disabled")
        area.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        def copy():
            window.clipboard_clear()
            window.clipboard_append(text)

        row = tkinter.Frame(window)
        row.pack(fill="x", padx=10, pady=10)
        tkinter.Button(row, text="Kopiuj szczegoly", command=copy).pack(side="left")
        tkinter.Button(row, text="Zamknij", command=window.destroy).pack(side="right")
        if saved_to:
            tkinter.Label(row, text="Zapisano: " + saved_to).pack(side="left", padx=10)
        window.mainloop()
    except Exception:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "Blad programu", 0x10)


def _owns_console():
    """Czy okno konsoli powstalo dla nas i zniknie razem z nami?

    Program konsolowy odpalony dwuklikiem z Eksploratora dostaje wlasne okno,
    ktore Windows zamyka w chwili zakonczenia procesu — uzytkownik widzi samo
    mrugniecie, nawet jesli program wypisal cos wartosciowego. Ten sam plik
    uruchomiony z CMD, PowerShella albo z potoku pisze do CUDZEGO okna, ktore
    zostaje otwarte; zatrzymywanie sie tam na Enter tylko zawieszaloby czyjas
    automatyzacje.

    `GetConsoleProcessList` oddaje liczbe procesow podpietych do konsoli i
    rozdziela te dwa przypadki: 1 = jestesmy sami, wiec okno jest nasze, 2 lub
    wiecej = jest przy nim powloka, ktora nas uruchomila. Gdy odpowiedzi nie ma
    (program okienkowy bez konsoli, inny system), wybieramy wyjscie
    bezpieczniejsze: nie zatrzymywac, bo zawieszony program jest gorszy od
    zamknietego okna.
    """
    try:
        import ctypes

        buffer = (ctypes.c_uint * 8)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buffer, 8)
    except Exception:  # noqa: BLE001 - kazda porazka znaczy "nie zatrzymuj"
        return False
    return count == 1


def _wait_for_keypress():
    if not _owns_console():
        return
    try:
        input("Nacisnij Enter, aby zamknac...")
    except (EOFError, KeyboardInterrupt):
        pass


def _report(exc):
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    saved_to = _save_report(text)
{report_body}


def main():
    _register_vendored_dll_dirs()
    _set_working_directory()
    try:
        runpy.run_module(ENTRY_MODULE, run_name="__main__", alter_sys=True)
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - launcher musi zlapac wszystko
        _report(exc)
        sys.exit(1)
    finally:
{finish_body}


if __name__ == "__main__":
    main()
'''

_CHDIR_BUNDLE = """\
    base = getattr(sys, "_MEIPASS", None)
    if base:
        os.chdir(base)
"""

_CHDIR_EXECUTABLE = """\
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
"""

_REPORT_WINDOWED = """\
    _show_error_dialog(text, saved_to)
"""

_REPORT_CONSOLE = """\
    print(text, file=sys.stderr)
    if saved_to:
        print("Szczegoly zapisano w: " + saved_to, file=sys.stderr)
"""

# Pauza konczaca `main()` obejmuje tak samo przebieg udany, jak i awarie —
# gdyby raport o bledzie czekal na Enter po swojemu, po awarii trzeba by go
# nacisnac dwa razy.
_FINISH_CONSOLE = """\
        _wait_for_keypress()
"""

_FINISH_WINDOWED = """\
        pass
"""


def _quote_module_name(value: str) -> str:
    # Why not repr()? It picks single quotes for a plain identifier, which
    # fails the test suite's double-quote assertion.
    #
    # Why not json.dumps()? It escapes astral code points (above U+FFFF) as
    # a UTF-16 surrogate pair of \uXXXX escapes, per the JSON spec. Python's
    # string-literal grammar does NOT recombine adjacent \u surrogate
    # escapes back into one scalar value, so ENTRY_MODULE would silently
    # decode to two lone-surrogate characters instead of the original one
    # character -- a corrupted round trip that still parses.
    #
    # str.encode("unicode_escape") escapes an astral code point as a single
    # \U000XXXXX escape instead, which Python's grammar *does* decode back
    # to the original scalar. It does not escape a literal double quote
    # though, so that is handled separately below, after the unicode_escape
    # pass (so a backslash it introduces is never re-escaped).
    escaped = value.encode("unicode_escape").decode("ascii")
    escaped = escaped.replace('"', '\\"')
    return '"' + escaped + '"'


def render_launcher(entry_module: str, app_kind: AppKind, output_mode: OutputMode) -> str:
    chdir_body = _CHDIR_BUNDLE if output_mode is OutputMode.ONEFILE else _CHDIR_EXECUTABLE
    windowed = app_kind is AppKind.WINDOWED
    report_body = _REPORT_WINDOWED if windowed else _REPORT_CONSOLE
    finish_body = _FINISH_WINDOWED if windowed else _FINISH_CONSOLE
    return _TEMPLATE.format(
        entry=_quote_module_name(entry_module),
        chdir_body=chdir_body,
        report_body=report_body,
        finish_body=finish_body,
    )
