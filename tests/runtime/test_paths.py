import re
from pathlib import Path

from exelent.runtime import paths
from exelent.runtime.paths import (
    clean_current_session,
    path_hash,
    session_id,
    state_dir,
    work_dir_for,
)


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


def test_two_files_in_one_folder_get_different_work_dirs(tmp_path, monkeypatch):
    """Without this, the second build deletes the first build's environment.

    `path_hash` is the only value that separates these runs.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    a = work_dir_for(tmp_path, single_file=tmp_path / "a.py")
    b = work_dir_for(tmp_path, single_file=tmp_path / "b.py")
    assert a != b


def test_directory_work_dir_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert work_dir_for(tmp_path) == work_dir_for(tmp_path, single_file=None)


def test_two_sessions_of_the_same_project_get_different_work_dirs(tmp_path, monkeypatch):
    """A13: two EXElent instances building the same project need separate work dirs.

    Otherwise one instance's `materialize_workspace` deletes the other one's
    source copy in the middle of its build.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(paths, "_SESSION_ID", "aaaaaaaa")
    first = work_dir_for(tmp_path)
    monkeypatch.setattr(paths, "_SESSION_ID", "bbbbbbbb")
    second = work_dir_for(tmp_path)
    assert first != second
    assert first.parent == second.parent == tmp_path / "EXElent" / "b"


def test_clean_current_session_removes_only_this_session(tmp_path, monkeypatch):
    """`clean_current_session` removes only directories from this session.

    Another instance may still be building, so its directory must remain
    untouched (A09/A13).
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(paths, "_SESSION_ID", "bbbbbbbb")
    other = work_dir_for(tmp_path)
    other.mkdir(parents=True)
    (other / "venv").mkdir()

    monkeypatch.setattr(paths, "_SESSION_ID", "aaaaaaaa")
    mine = work_dir_for(tmp_path)
    mine.mkdir(parents=True)

    clean_current_session()

    assert not mine.exists()
    assert other.exists()  # another session remains untouched


def test_session_id_is_short_ascii():
    assert re.fullmatch(r"[0-9a-f]{8}", session_id())
