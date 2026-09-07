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

_CHECK_SCRIPT = Path(__file__).with_name("_targetcheck.py")


def validate_target_syntax(
    python: Path,
    workspace: Path,
    *,
    python_version: str,
    cancel=None,
) -> Issue | None:
    """Zwraca `target_syntax_error` (BLOCKER) dla pierwszego źródła, które nie
    kompiluje się docelowym `python`; `None`, gdy wszystko się kompiluje.

    Gdy zawiedzie samo narzędzie (interpreter nie wystartował, skrypt nie
    wypisał rozpoznawalnej linii), zwracamy `None` zamiast blokować: to awaria
    NASZA, nie kodu użytkownika, a nieudany moduł i tak złapie później strażnik
    `dropped_project_modules`. Fałszywy BLOCKER z własnej infrastruktury byłby
    gorszy niż brak tej dodatkowej kontroli.
    """
    if cancel is not None and cancel.cancelled:
        return None

    completed = subprocess.run(
        [str(python), str(_CHECK_SCRIPT), str(workspace)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if completed.returncode == 0:
        return None

    line = next((ln for ln in completed.stdout.splitlines() if "\t" in ln), None)
    if line is None:
        return None
    file, lineno, detail = (line.split("\t", 2) + ["", "", ""])[:3]
    return Issue(
        "target_syntax_error",
        Severity.BLOCKER,
        {"file": file, "line": lineno, "detail": detail, "version": python_version},
    )
