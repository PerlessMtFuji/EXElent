"""Ostatnio uzywane sciezki. Zwykly plik JSON — nie zapisujemy konfiguracji
buildow, tylko liste folderow, zeby drugi raz nie trzeba bylo ich szukac.

Kazda operacja jest bezpieczna w obie strony: uszkodzony albo niedostepny plik
oddaje pusta liste, a nieudany zapis nie przerywa wyboru folderu. Lista jest
wygoda, wiec nie moze byc powodem, dla ktorego program nie rusza.
"""

from __future__ import annotations

import json
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
        if path.is_dir() and path not in result:
            result.append(path)
    return result[:limit]


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
