import re
from pathlib import Path

from exelent.runtime.paths import path_hash, state_dir, work_dir_for


def test_state_dir_is_under_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert state_dir() == tmp_path / "EXElent"


def test_path_hash_is_short_ascii():
    value = path_hash(Path(r"C:\Users\Ktoś\Pulpit\mój program"))
    assert re.fullmatch(r"[0-9a-f]{8}", value)


def test_path_hash_is_stable():
    p = Path(r"C:\a\b")
    assert path_hash(p) == path_hash(p)


def test_path_hash_differs_per_path():
    assert path_hash(Path(r"C:\a")) != path_hash(Path(r"C:\b"))


def test_work_dir_is_short_and_ascii(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    work = work_dir_for(Path(r"C:\Users\Ktoś\zażółć gęślą jaźń"))
    assert work.parent == tmp_path / "EXElent" / "b"
    assert str(work).isascii()
