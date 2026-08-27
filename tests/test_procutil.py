"""`run_bounded` — timeout, ktory NAPRAWDE ogranicza czas.

`subprocess.run(..., capture_output=True, timeout=T)` tego nie robi: ubija
BEZPOSREDNIE dziecko, po czym czyta potok do konca, a potok zamyka sie dopiero,
gdy skonczy WNUK, ktory odziedziczyl uchwyty. EXE w trybie ONEFILE ma dokladnie
ten ksztalt (bootloader + prawdziwy program), wiec test golden przy regresji nie
zapalal sie na czerwono, tylko wisial. Zmierzone: timeout 3 s, dziecko zyjace
30 s, powrot po 30.1 s.

Testy sa szybkie, bo dowodza mechanizmu na zwyklych procesach Pythona — zaden
z nich nie buduje EXE.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from procutil import is_running, run_bounded

CHILD_LIFETIME = 30
BOUND = 3


def _tree(tmp_path: Path, marker: Path | None = None) -> list[str]:
    """Rodzic, ktory startuje dziecko i sam czeka — jak bootloader ONEFILE."""
    child = tmp_path / "dziecko.py"
    record = (
        f"import os, pathlib; pathlib.Path(r'{marker}').write_text(str(os.getpid()))\n"
        if marker
        else ""
    )
    child.write_text(f"import time\n{record}time.sleep({CHILD_LIFETIME})\n", encoding="utf-8")
    parent = tmp_path / "rodzic.py"
    parent.write_text(
        f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, r'{child}'])\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    return [sys.executable, str(parent)]


def test_a_normal_program_returns_its_output(tmp_path):
    script = tmp_path / "zwykly.py"
    script.write_text("print('GOTOWE')\n", encoding="utf-8")

    done = run_bounded([sys.executable, str(script)], timeout=30)

    assert done.returncode == 0
    assert "GOTOWE" in done.stdout


def test_input_reaches_the_program(tmp_path):
    script = tmp_path / "pytajacy.py"
    script.write_text("print('CZESC-' + input().strip().upper())\n", encoding="utf-8")

    done = run_bounded([sys.executable, str(script)], timeout=30, input="ala\n")

    assert "CZESC-ALA" in done.stdout


def test_timeout_bounds_the_call_even_when_a_grandchild_holds_the_pipes(tmp_path):
    started = time.monotonic()

    done = run_bounded(_tree(tmp_path), timeout=BOUND, allow_timeout=True)

    elapsed = time.monotonic() - started
    assert elapsed < CHILD_LIFETIME / 2, f"wrocilo po {elapsed:.1f}s, a timeout to {BOUND}s"
    assert done.returncode is None, "przekroczony czas ma byc widoczny w wyniku"


def test_the_whole_tree_is_dead_afterwards(tmp_path):
    marker = tmp_path / "pid.txt"

    run_bounded(_tree(tmp_path, marker), timeout=BOUND, allow_timeout=True)

    pid = int(marker.read_text(encoding="utf-8").strip())
    assert not is_running(pid), "wnuk przezyl sprzatanie i trzyma swoje zasoby"


def test_an_overrun_is_a_failure_by_default(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded(_tree(tmp_path), timeout=BOUND)
