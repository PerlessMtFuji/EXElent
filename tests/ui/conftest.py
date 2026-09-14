"""Wspolna izolacja stanu dla testow UI (A14).

Okno czyta trwaly stan uzytkownika z `%LOCALAPPDATA%\\EXElent`: zapisany jezyk
(`settings.json`), liste ostatnich projektow, logi. Bez izolacji test jezyka
interfejsu przechodzil albo nie w zaleznosci od tego, co deweloper kiedys
kliknal — zapisana preferencja "pl" wygrywala z podstawionym `system_language`.

Pierwszenstwo zapisanej preferencji nad jezykiem systemu jest POPRAWNE i
zostaje. Naprawiamy to, ze test w ogole widzial cudzy zapisany stan: kazdy
test UI dostaje wlasny, pusty katalog stanu.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path_factory, monkeypatch):
    state = tmp_path_factory.mktemp("localappdata")
    monkeypatch.setenv("LOCALAPPDATA", str(state))
