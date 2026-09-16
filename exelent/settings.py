"""Persistent user settings. Plain JSON, scalar values only.

Every operation is safe in both directions: a corrupt or inaccessible file
returns defaults, and a failed write does not interrupt work. Settings are
a convenience, so they must never be the reason the program fails to start —
just like the recent projects list.
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
    """`None` means "follow the system language" — preserves the existing
    behavior for anyone who has not made a choice."""


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
    # A wrong TYPE is just as possible as a wrong file — a hand-edited JSON
    # may have "yes" where true is expected.
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
