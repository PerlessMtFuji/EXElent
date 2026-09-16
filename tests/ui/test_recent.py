"""Recently used paths stored as JSON beside the rest of the application state.

The list is a convenience rather than a source of truth. Every read must
survive a corrupt file, a folder deleted behind the application's back, and an
unwritable state directory. None may put a traceback on the welcome screen.
"""

import json
from pathlib import Path

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
    (project,) = _dirs(tmp_path, "calculator")
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
    """Without deduplication, a repeated entry occupies two of five slots.

    It then pushes out the oldest project, defeating the list for someone who
    repeatedly builds the same folder.
    """
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
    """Without this, `[:limit]` in `load_recent` would be an untested branch.

    `remember` already truncates the stored file to LIMIT.
    """
    for path in _dirs(tmp_path, "a", "b", "c"):
        recent.remember(path)
    assert len(recent.load_recent(limit=2)) == 2


def test_missing_directories_are_dropped(tmp_path):
    (gone,) = _dirs(tmp_path, "gone")
    recent.remember(gone)
    gone.rmdir()
    assert recent.load_recent() == []


def test_recent_keeps_single_files(tmp_path):
    """After adding single-file mode, an `is_dir()` filter would drop files."""
    script = tmp_path / "test.py"
    script.write_text("print('x')\n", encoding="utf-8")

    recent.remember(script)

    assert script.resolve() in recent.load_recent()


def test_corrupt_file_does_not_crash():
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / "recent.json").write_text("{this is not json", encoding="utf-8")
    assert recent.load_recent() == []


def test_json_that_is_not_a_list_does_not_crash():
    """`json.loads("5")` returns a non-iterable number.

    Without the type check this would raise TypeError instead of returning an
    empty list.
    """
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / "recent.json").write_text("5", encoding="utf-8")
    assert recent.load_recent() == []


def test_an_unwritable_list_is_not_an_error(tmp_path):
    """An unwritable state directory must not break folder selection.

    The recent list is a convenience rather than a prerequisite for operation.
    """
    (project,) = _dirs(tmp_path, "project")
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / "recent.json").mkdir()
    recent.remember(project)
    assert recent.load_recent() == []


def test_the_file_holds_plain_paths(tmp_path):
    """Keep the format human-readable because users may delete it manually."""
    (project,) = _dirs(tmp_path, "project")
    recent.remember(project)
    raw = json.loads((state_dir() / "recent.json").read_text(encoding="utf-8"))
    assert raw == [str(project)]


# --- tile labels ---


def test_distinct_names_stay_short():
    labels = recent.display_labels([Path(r"C:\a\project"), Path(r"C:\b\other")])
    assert labels == ["project", "other"]


def test_colliding_names_grow_until_they_differ():
    """Two `test.txt` paths need enough parents to distinguish them."""
    labels = recent.display_labels(
        [
            Path(r"C:\Users\x\Downloads\test\test.txt"),
            Path(r"C:\Users\x\Downloads\test.txt"),
        ]
    )
    assert labels[0] != labels[1]
    assert labels == [str(Path("test/test.txt")), str(Path("Downloads/test.txt"))]


def test_only_the_colliding_entries_grow():
    labels = recent.display_labels(
        [
            Path(r"C:\p\test\code.py"),
            Path(r"C:\p\other\code.py"),
            Path(r"C:\p\solo.py"),
        ]
    )
    assert labels[2] == "solo.py"
    assert labels[0] != labels[1]


def test_labels_survive_a_path_that_runs_out_of_parents():
    """Do not loop when a path has no more parents to add."""
    labels = recent.display_labels([Path("code.py"), Path(r"C:\a\code.py")])
    assert len(labels) == 2
    assert labels[0] != labels[1]


def test_empty_list_is_fine():
    assert recent.display_labels([]) == []
