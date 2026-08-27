"""Uruchamianie zbudowanych programow tak, zeby timeout NAPRAWDE ograniczal czas.

`subprocess.run(..., capture_output=True, timeout=T)` tego nie robi. Po
przekroczeniu czasu ubija BEZPOSREDNIE dziecko, a potem czyta potok do konca —
a potok zamyka sie dopiero, gdy skonczy WNUK, ktory odziedziczyl uchwyty. EXE w
trybie ONEFILE ma dokladnie ten ksztalt: bootloader rozpakowuje `_MEI...` i
uruchamia w nim prawdziwy program. Zmierzone na tej maszynie: timeout 3 s przy
dziecku zyjacym 30 s -> powrot po 30.1 s.

Skutek w tescie golden byl gorszy niz porazka: przy regresji w programie z
oknem test nie zapalal sie na czerwono, tylko wisial, a w nocnym CI oznacza to
zajety runner i BRAK sygnalu.
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import suppress
from pathlib import Path

# Ile czekamy na domkniecie potokow PO ubiciu drzewa. Normalnie to ulamek
# sekundy. Ma wlasna granice, bo gdy `taskkill` zawiedzie (proces podniesiony,
# brak `taskkill` w obrazie CI), potok trzyma ktos, kogo nie ubilismy — a
# wtedy `communicate()` bez timeoutu czeka do konca zycia RODZICA. Zmierzone:
# 300.1 s przy `timeout=3`. Test ma sie zaswiecic na czerwono, nigdy wisiec.
DRAIN_TIMEOUT = 10.0


def kill_tree(process: subprocess.Popen) -> None:
    """Ubija cale drzewo procesow, nie tylko rodzica."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:  # pragma: no cover - projekt jest windowsowy, ale nie klam o tym
        process.kill()
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=30)


def _tasklist(filter_expression: str) -> str:
    listing = subprocess.run(
        ["tasklist", "/FI", filter_expression],
        capture_output=True,
        text=True,
        check=False,
    )
    return listing.stdout


def is_running(pid: int) -> bool:
    output = _tasklist(f"PID eq {pid}")
    return "No tasks" not in output and str(pid) in output


def is_running_name(name: str) -> bool:
    output = _tasklist(f"IMAGENAME eq {name}")
    return "No tasks" not in output and name.lower() in output.lower()


def run_bounded(
    command,
    *,
    timeout: float,
    input: str | None = None,
    cwd: Path | None = None,
    allow_timeout: bool = False,
) -> subprocess.CompletedProcess:
    """Uruchamia program i wraca w zadanym czasie — takze gdy zyje jego dziecko.

    `allow_timeout=True` znaczy "przekroczenie czasu jest tu spodziewane"
    (program z oknem, ktore czeka na uzytkownika) i oddaje wynik z
    `returncode is None`. Domyslnie przekroczenie czasu jest PORAZKA: test ma
    sie zaswiecic na czerwono, a nie wisiec.
    """
    process = subprocess.Popen(
        [str(part) for part in command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
    )
    try:
        out, err = process.communicate(input=input, timeout=timeout)
        return subprocess.CompletedProcess(process.args, process.returncode, out, err)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            # Drzewo nie zyje, wiec potoki zamykaja sie od reki — chyba ze
            # ubicie zawiodlo. Wtedy rezygnujemy z wyjscia zamiast wisiec:
            # wynik bez logu jest do uratowania, zawieszony CI nie jest.
            out, err = process.communicate(timeout=DRAIN_TIMEOUT)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        if allow_timeout:
            return subprocess.CompletedProcess(process.args, None, out, err)
        raise subprocess.TimeoutExpired(process.args, timeout, output=out, stderr=err) from None
