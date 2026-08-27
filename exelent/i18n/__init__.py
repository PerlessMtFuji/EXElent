"""Tłumaczenia. Rdzeń zwraca kody Issue, tutaj stają się zdaniami.

Ta warstwa jest jedynym miejscem, w którym powstaje tekst pokazywany
użytkownikowi. Rdzeń nie zna języka: gdyby składał zdania sam, każda zmiana
tekstu wymagałaby ruszania logiki, a GUI nie mogłoby pokazać tego samego
zdarzenia inaczej niż CLI.
"""

from __future__ import annotations

import locale

from exelent.i18n import en, pl
from exelent.models import Issue

CATALOGS: dict[str, dict[str, str]] = {"pl": pl.CATALOG, "en": en.CATALOG}

_current = "pl"


def system_language() -> str:
    """Język systemu, o ile umiemy go obsłużyć — inaczej angielski."""
    try:
        code, _encoding = locale.getlocale()
    except ValueError:
        code = None
    if code and code.lower().startswith("pl"):
        return "pl"
    return "en"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in CATALOGS else "en"


def current_language() -> str:
    return _current


def t(key: str, **params: str) -> str:
    """Zdanie dla klucza. Nieznany klucz wraca jako on sam — nigdy nie rzuca.

    Brakujący parametr też nie jest powodem do wyjątku: lepszy jest szablon
    z nawiasem klamrowym niż ściana tracebacku zamiast komunikatu o błędzie.
    """
    template = CATALOGS[_current].get(key)
    if template is None:
        return key
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template


def describe(issue: Issue) -> str:
    """Issue -> zdanie, razem z danymi, które rdzeń pod nie podłożył."""
    return t(issue.code, **dict(issue.data))
