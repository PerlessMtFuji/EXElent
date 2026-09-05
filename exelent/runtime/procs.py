"""Kończenie procesów potomnych — wspólne dla trzech miejsc, które tego
potrzebują.

Przerwany build (PyInstaller uruchamia własne procesy potomne), anulowany
preflight (uv) i awaryjne zamknięcie okna mają ten sam obowiązek: nie
zostawić po sobie niczego, co mieli w tle. Bez `/T` zostają sieroty
trzymające otwarte pliki w workspace.
"""

from __future__ import annotations

import subprocess

# Bez tego użytkownikowi GUI mignie czarne okno konsoli przy każdym
# wywołaniu narzędzia wiersza poleceń.
CREATE_NO_WINDOW = 0x08000000


def kill_tree(pid: int) -> int:
    """Zabija proces i całe jego potomstwo.

    Zwraca kod wyjścia taskkill, żeby wywołujący mógł wykryć nieudane
    zabicie (proces może wciąż trzymać otwarte pliki w workspace).
    """
    result = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    return result.returncode
