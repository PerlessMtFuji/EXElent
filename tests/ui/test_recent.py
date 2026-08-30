"""Ostatnio uzywane foldery — plik JSON obok reszty stanu.

Lista jest wygoda, nie zrodlem prawdy: kazde jej czytanie ma przezyc plik
uszkodzony, folder skasowany za plecami programu i katalog stanu, do ktorego
nie da sie pisac. Zaden z tych przypadkow nie moze skonczyc sie tracebackiem
na ekranie powitalnym.
"""

import json

import pytest

from exelent.runtime.paths import state_dir
from exelent.ui import recent


@pytest.fixture(autouse=True)
def _state(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))


def _dirs(tmp_path, *names):
    made = []
    for name in names:
        path = tmp_path / name
        path.mkdir()
        made.append(path)
    return made


def test_empty_when_nothing_remembered():
    assert recent.load_recent() == []


def test_remembered_path_comes_back(tmp_path):
    (project,) = _dirs(tmp_path, "kalkulator")
    recent.remember(project)
    assert recent.load_recent() == [project]


def test_most_recent_is_first(tmp_path):
    a, b = _dirs(tmp_path, "a", "b")
    recent.remember(a)
    recent.remember(b)
    assert recent.load_recent()[0] == b


def test_remembering_again_moves_it_to_the_front(tmp_path):
    a, b = _dirs(tmp_path, "a", "b")
    recent.remember(a)
    recent.remember(b)
    recent.remember(a)
    assert recent.load_recent() == [a, b]


def test_duplicates_are_collapsed(tmp_path):
    (a,) = _dirs(tmp_path, "a")
    recent.remember(a)
    recent.remember(a)
    assert recent.load_recent() == [a]


def test_repeating_one_folder_does_not_push_out_the_others(tmp_path):
    """Bez odsiewu duplikatow w `remember` powtorzony wpis zajmuje DWA miejsca
    z pieciu i wypycha najstarszy projekt. Ktos, kto buduje wciaz ten sam
    folder, traci wtedy liste, ktora ma mu oszczedzic szukania."""
    projects = _dirs(tmp_path, "a", "b", "c", "d", "e")
    for path in projects:
        recent.remember(path)
    recent.remember(projects[-1])
    assert projects[0] in recent.load_recent()


def test_limit_is_respected(tmp_path):
    for path in _dirs(tmp_path, *(f"p{i}" for i in range(10))):
        recent.remember(path)
    assert len(recent.load_recent(limit=5)) == 5


def test_a_smaller_limit_returns_fewer(tmp_path):
    """Bez tego `[:limit]` w `load_recent` bylby galezia nie do zgaszenia:
    `remember` i tak przycina plik do LIMIT."""
    for path in _dirs(tmp_path, "a", "b", "c"):
        recent.remember(path)
    assert len(recent.load_recent(limit=2)) == 2


def test_missing_directories_are_dropped(tmp_path):
    (gone,) = _dirs(tmp_path, "zniknal")
    recent.remember(gone)
    gone.rmdir()
    assert recent.load_recent() == []


def test_recent_keeps_single_files(tmp_path, monkeypatch):
    """Po wprowadzeniu trybu jednoplikowego filtr `is_dir()` cicho gubilby
    kazdy wpis bedacy plikiem."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    script = tmp_path / "test.py"
    script.write_text("print('x')\n", encoding="utf-8")

    recent.remember(script)

    assert script.resolve() in recent.load_recent()


def test_corrupt_file_does_not_crash():
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / "recent.json").write_text("{to nie jest json", encoding="utf-8")
    assert recent.load_recent() == []


def test_json_that_is_not_a_list_does_not_crash():
    """`json.loads("5")` daje liczbe, po ktorej nie da sie iterowac — bez
    sprawdzenia typu byloby TypeError zamiast pustej listy."""
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / "recent.json").write_text("5", encoding="utf-8")
    assert recent.load_recent() == []


def test_an_unwritable_list_is_not_an_error(tmp_path):
    """Katalog stanu bez prawa zapisu nie moze wywrocic wyboru folderu —
    lista ostatnich to wygoda, a nie warunek pracy programu."""
    (project,) = _dirs(tmp_path, "projekt")
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / "recent.json").mkdir()
    recent.remember(project)
    assert recent.load_recent() == []


def test_the_file_holds_plain_paths(tmp_path):
    """Format ma byc czytelny dla czlowieka — to jedyny zapis stanu, ktory
    uzytkownik moze chciec skasowac recznie."""
    (project,) = _dirs(tmp_path, "projekt")
    recent.remember(project)
    raw = json.loads((state_dir() / "recent.json").read_text(encoding="utf-8"))
    assert raw == [str(project)]
