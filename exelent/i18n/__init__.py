"""Translations. The core returns Issue codes, here they become sentences.

This layer is the only place where user-facing text is produced. The core
does not know the language: if it assembled sentences itself, every text
change would require touching logic, and the GUI could not present the
same event differently from the CLI.
"""

from __future__ import annotations

import locale

from exelent.i18n import en, pl
from exelent.models import Issue

CATALOGS: dict[str, dict[str, str]] = {"pl": pl.CATALOG, "en": en.CATALOG}

_current = "pl"


# Windows does not provide a language code, only its ENGLISH NAME:
# `locale.getlocale()` returns `('Polish_Poland', '1250')` there, not
# `('pl_PL', ...)`. "Polish" starts with "po", so a bare `startswith("pl")`
# sent the Polish user to the English version — on the only system this program
# supports. The test from task 16 did not catch this because it used the POSIX
# form, which Windows never produces.
_POLISH_LOCALES = ("pl", "polish")


def system_language() -> str:
    """System language, if we can handle it — English otherwise."""
    try:
        code, _encoding = locale.getlocale()
    except ValueError:
        code = None
    if code and code.lower().startswith(_POLISH_LOCALES):
        return "pl"
    return "en"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in CATALOGS else "en"


def current_language() -> str:
    return _current


def t(key: str, **params: str) -> str:
    """Sentence for a key. An unknown key returns itself — never raises.

    A missing parameter is not a reason to raise either: a template with a
    brace is better than a wall of traceback instead of an error message.
    """
    template = CATALOGS[_current].get(key)
    if template is None:
        return key
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template


def describe(issue: Issue) -> str:
    """Issue -> sentence, together with data the core attached to it."""
    return t(issue.code, **dict(issue.data))
