"""Walidacja przygotowanych źródeł DOCELOWYM interpreterem przed PyInstallerem.

Analiza sprawdza składnię `ast.parse`-em interpretera DEWELOPERSKIEGO — a to
mija się z prawdą dwukrotnie: parser (nie kompilator) przepuszcza część reguł
języka (`return` poza funkcją, źle umieszczony `from __future__`), a wersja
deweloperska (3.13) nie jest wersją, pod którą powstaje EXE (3.12). Kod poprawny
u dewelopera, lecz niezgodny z docelowym Pythonem, przechodził więc cały potok:
PyInstaller kompilował go dopiero przy składaniu PYZ, łapał `SyntaxError`,
WYRZUCAŁ moduł i kończył kodem 0 — a użytkownik dostawał EXE witające go
„No module named <jego program>".

Tu kompilujemy źródła docelowym interpreterem z venva builda, przed
PyInstallerem. Kompilacja, nie uruchomienie — nie wykonujemy kodu użytkownika.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from exelent.models import Issue, Severity
from exelent.runtime.procs import CREATE_NO_WINDOW

# Marker protokołu wypisywany przez checker przy błędzie składni. Jawny prefiks
# zastępuje dawną heurystykę „pierwsza linia z tabulatorem" (B09): dowolny tab w
# wyjściu mógł zostać wzięty za błąd, a brak tabu — za sukces. Teraz błąd
# rozpoznajemy WYŁĄCZNIE po tej linii, a jej brak przy niezerowym kodzie znaczy
# „walidacja niewykonana", nie „brak błędu".
_ERROR_MARKER = "EXELENT_SYNTAX_ERROR"

# Kod checkera jest OSADZONY tutaj i przekazywany docelowemu interpreterowi
# przez `-c`, a nie czytany z pliku `_targetcheck.py` obok modułu. W zamrożonym
# EXElent.exe takiego pliku obok modułu NIE MA (PyInstaller zbiera tylko to, co
# jest importowane — nie ścieżki czytane z dysku), więc walidacja po cichu się
# nie wykonywała i `None` czytano jako sukces (B09). Jako stała w importowanym
# module źródło jest w paczce zawsze.
#
# Checker KOMPILUJE każde źródło (nie uruchamia — patrz A05), bajtami, żeby
# `compile` uszanował deklarację kodowania (PEP 263) dokładnie tak jak import w
# gotowym EXE. Pierwszy plik, który się nie kompiluje, wypisuje
# `<marker>\t<ścieżka względna>\t<linia>\t<komunikat>` i kończy kodem 1; gdy
# wszystko się kompiluje — kod 0. Musi być samowystarczalny (tylko stdlib).
_CHECK_SOURCE = f"""\
import os
import sys

MARKER = {_ERROR_MARKER!r}


def main():
    root = sys.argv[1]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "rb") as handle:
                data = handle.read()
            try:
                compile(data, path, "exec")
            except SyntaxError as exc:
                rel = os.path.relpath(path, root)
                detail = (exc.msg or "").replace("\\t", " ").replace("\\n", " ")
                sys.stdout.write(f"{{MARKER}}\\t{{rel}}\\t{{exc.lineno or 0}}\\t{{detail}}\\n")
                return 1
    return 0


sys.exit(main())
"""


def _validation_failed(python_version: str, detail: str) -> Issue:
    """Walidacja się NIE WYKONAŁA (interpreter nie wystartował, checker padł lub
    złamał protokół). To awaria kontroli, nie potwierdzenie poprawności — dlatego
    BLOCKER, a nie ciche `None` czytane jako sukces (B09). Strażnik
    `dropped_project_modules` zostaje jako DODATKOWA ochrona, nie zastępstwo."""
    return Issue(
        "validation_failed",
        Severity.BLOCKER,
        {"version": python_version, "detail": detail[:200]},
    )


def validate_target_syntax(
    python: Path,
    workspace: Path,
    *,
    python_version: str,
    cancel=None,
) -> Issue | None:
    """Cztery rozłączne wyniki (B09): `None` — składnia poprawna;
    `target_syntax_error` (BLOCKER) — pierwsze źródło, które nie kompiluje się
    docelowym `python`; `validation_failed` (BLOCKER) — kontrola się nie
    wykonała lub złamała protokół; `None` również po anulowaniu (build kończy
    się wtedy jako przerwany na dalszym etapie).

    Niewykonana kontrola NIE jest już traktowana jak brak błędu: fałszywy sukces
    z własnej infrastruktury dawał EXE bez kodu użytkownika, kończące się
    „No module named ...".
    """
    if cancel is not None and cancel.cancelled:
        return None

    try:
        completed = subprocess.run(
            [str(python), "-c", _CHECK_SOURCE, str(workspace)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except OSError as exc:
        # Docelowy interpreter w ogóle nie wystartował — kontrola się nie odbyła.
        return _validation_failed(python_version, str(exc))

    if completed.returncode == 0:
        return None

    prefix = _ERROR_MARKER + "\t"
    line = next((ln for ln in completed.stdout.splitlines() if ln.startswith(prefix)), None)
    if line is None:
        # Niezerowy kod bez markera protokołu: checker nie doszedł do kontroli
        # albo się wywrócił. To awaria walidacji, nie „brak błędu".
        detail = (completed.stderr or completed.stdout or "").strip().replace("\n", " ")
        return _validation_failed(python_version, detail)

    _marker, file, lineno, detail = (line.split("\t", 3) + ["", "", "", ""])[:4]
    return Issue(
        "target_syntax_error",
        Severity.BLOCKER,
        {"file": file, "line": lineno, "detail": detail, "version": python_version},
    )
