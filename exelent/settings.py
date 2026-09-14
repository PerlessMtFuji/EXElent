"""Trwałe ustawienia użytkownika. Zwykły JSON, wyłącznie wartości skalarne.

Każda operacja jest bezpieczna w obie strony: uszkodzony albo niedostępny plik
oddaje wartości domyślne, a nieudany zapis nie przerywa pracy. Ustawienia są
wygodą, więc nie mogą być powodem, dla którego program nie rusza — dokładnie
jak lista ostatnich projektów.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from exelent.runtime.paths import state_dir


@dataclass(frozen=True)
class Settings:
    ask_before_download: bool = True
    language: str | None = None
    """`None` znaczy „idź za językiem systemu" — zachowuje dotychczasowe
    zachowanie dla każdego, kto niczego nie wybrał."""


def _file() -> Path:
    return state_dir() / "settings.json"


def load_settings() -> Settings:
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    default = Settings()
    ask = raw.get("ask_before_download", default.ask_before_download)
    language = raw.get("language", default.language)
    # Zly TYP jest tak samo mozliwy jak zly plik — recznie edytowany JSON
    # potrafi miec "tak" tam, gdzie ma byc true.
    return Settings(
        ask_before_download=ask if isinstance(ask, bool) else default.ask_before_download,
        language=language if isinstance(language, str) or language is None else default.language,
    )


def save_settings(settings: Settings) -> None:
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        _file().write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
