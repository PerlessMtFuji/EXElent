"""Ostatnio uzywane sciezki. Zwykly plik JSON — nie zapisujemy konfiguracji
buildow, tylko liste folderow, zeby drugi raz nie trzeba bylo ich szukac.

Kazda operacja jest bezpieczna w obie strony: uszkodzony albo niedostepny plik
oddaje pusta liste, a nieudany zapis nie przerywa wyboru folderu. Lista jest
wygoda, wiec nie moze byc powodem, dla ktorego program nie rusza.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from exelent.runtime.paths import state_dir

LIMIT = 5


def _file() -> Path:
    return state_dir() / "recent.json"


def load_recent(limit: int = LIMIT) -> list[Path]:
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    result: list[Path] = []
    for item in raw:
        path = Path(str(item))
        if path.exists() and path not in result:
            result.append(path)
    return result[:limit]


def display_labels(paths: Sequence[Path]) -> list[str]:
    """Napisy na kafelki — najkrotsze, jakie jeszcze rozrozniaja wpisy.

    Sama `path.name` nie wystarcza: `Pobrane\\test\\test.txt` i
    `Pobrane\\test.txt` obie nazywaja sie "test.txt", wiec uzytkownik widzial
    dwa identyczne kafelki prowadzace w rozne miejsca i nie mial jak zgadnac,
    ktory jest ktory.

    Rosna TYLKO wpisy, ktore sie zderzaja — reszta zostaje krotka, bo pelna
    sciezka na kazdym kafelku byla by gorsza od kolizji, ktora naprawia.
    """
    parts = [path.parts for path in paths]
    depths = [1] * len(paths)
    # Kazdy obrot doklada jeden poziom katalogu tym wpisom, ktore wciaz sa
    # nierozroznialne. Ograniczenie petli najdluzsza sciezka daje twardy
    # koniec takze wtedy, gdy dwoch wpisow nie da sie rozroznic w ogole
    # (sciezka wzgledna kontra bezwzgledna o tym samym ogonie).
    for _ in range(max((len(p) for p in parts), default=1)):
        labels = [_tail(parts[i], depths[i]) for i in range(len(paths))]
        counts = Counter(labels)
        grew = False
        for i, label in enumerate(labels):
            if counts[label] > 1 and depths[i] < len(parts[i]):
                depths[i] += 1
                grew = True
        if not grew:
            break
    return [_tail(parts[i], depths[i]) for i in range(len(paths))]


def _tail(parts: tuple[str, ...], depth: int) -> str:
    return str(Path(*parts[-depth:])) if parts else ""


def remember(path: Path) -> None:
    path = Path(path).resolve()
    entries = [path, *(p for p in load_recent(limit=LIMIT * 2) if p != path)]
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        _file().write_text(
            json.dumps([str(p) for p in entries[:LIMIT]], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
