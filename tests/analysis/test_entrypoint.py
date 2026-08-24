from pathlib import Path

from exelent.analysis.entrypoint import (
    TEST_FILE_PENALTY,
    entry_is_certain,
    local_module_names,
    rank_entry_candidates,
)


def _srcs(root: Path, mapping: dict[str, str]) -> dict[Path, str]:
    return {root / k: v for k, v in mapping.items()}


def test_single_file_wins_without_heuristics(tmp_path):
    sources = _srcs(tmp_path, {"cokolwiek.py": "print(1)"})
    result = rank_entry_candidates(tmp_path, sources)
    assert result[0].path.name == "cokolwiek.py"


def test_import_graph_root_beats_name(tmp_path):
    # aaa.py importuje main.py, więc to aaa.py jest korzeniem mimo nazwy
    sources = _srcs(
        tmp_path,
        {
            "aaa.py": "import main\nmain.run()",
            "main.py": "def run():\n    pass",
        },
    )
    result = rank_entry_candidates(tmp_path, sources)
    assert result[0].path.name == "aaa.py"


def test_dunder_main_guard_scores(tmp_path):
    sources = _srcs(
        tmp_path,
        {
            "a.py": "x = 1",
            "b.py": "if __name__ == '__main__':\n    print(1)",
        },
    )
    result = rank_entry_candidates(tmp_path, sources)
    assert result[0].path.name == "b.py"


def test_root_beats_subdirectory(tmp_path):
    sources = _srcs(tmp_path, {"main.py": "x=1", "pkg/main.py": "x=1"})
    result = rank_entry_candidates(tmp_path, sources)
    assert result[0].path.parent == tmp_path


def test_tests_are_penalised(tmp_path):
    # Isolate the penalty itself, not just the final ordering: two files
    # identical in every OTHER scored respect (same content, both at root,
    # neither imported, neither importing, no guard/startup, no name match),
    # differing only by the "test_" prefix. If the penalty branch were
    # deleted, this score difference would drop to 0 and the test would fail
    # (regression coverage for review FINDING 2: the old ordering-only test
    # still passed even with the penalty branch removed).
    sources = _srcs(
        tmp_path,
        {
            "widget.py": "x = 1",
            "test_widget.py": "x = 1",
        },
    )
    result = rank_entry_candidates(tmp_path, sources)
    by_name = {c.path.name: c.score for c in result}
    assert by_name["widget.py"] - by_name["test_widget.py"] == TEST_FILE_PENALTY


def test_importer_outranks_imported_despite_weak_signals(tmp_path):
    # Regression for review FINDING 1 / INVARIANT A: main.py stacks every
    # weak heuristic there is (preferred name, __main__ guard, startup call)
    # while app_core.py, the true root, has only the import-graph signal.
    # The import graph must still win: no combination of name/guard/root/
    # startup bonuses may outrank the file that imports it.
    sources = _srcs(
        tmp_path,
        {
            "app_core.py": "import main\nmain.launch()\n",
            "main.py": (
                "import tkinter\n\n\n"
                "def launch():\n"
                "    root = tkinter.Tk()\n"
                "    root.mainloop()\n\n\n"
                "if __name__ == '__main__':\n"
                "    launch()\n"
            ),
        },
    )
    result = rank_entry_candidates(tmp_path, sources)
    assert result[0].path.name == "app_core.py"


def test_test_file_imports_do_not_demote_entry(tmp_path):
    # Regression for INVARIANT B: a test file importing the real entry point
    # must not cost that entry point its "nobody (non-test) imports me"
    # status. Without this, adding a test file to a project would break
    # entry-point detection.
    sources = _srcs(
        tmp_path,
        {
            "main.py": "if __name__ == '__main__':\n    pass",
            "test_main.py": "import main\n",
        },
    )
    result = rank_entry_candidates(tmp_path, sources)
    assert result[0].path.name == "main.py"


def test_gui_startup_call_scores(tmp_path):
    sources = _srcs(
        tmp_path,
        {
            "a.py": "x = 1",
            "okno.py": "import tkinter\nroot = tkinter.Tk()\nroot.mainloop()",
        },
    )
    result = rank_entry_candidates(tmp_path, sources)
    assert result[0].path.name == "okno.py"


def test_returns_all_candidates_sorted(tmp_path):
    sources = _srcs(tmp_path, {"main.py": "", "b.py": "", "c.py": ""})
    result = rank_entry_candidates(tmp_path, sources)
    assert len(result) == 3
    assert [c.score for c in result] == sorted((c.score for c in result), reverse=True)


def test_close_scores_are_not_certain(tmp_path):
    sources = _srcs(
        tmp_path,
        {
            "program_a.py": "if __name__ == '__main__':\n    pass",
            "program_b.py": "if __name__ == '__main__':\n    pass",
        },
    )
    assert entry_is_certain(rank_entry_candidates(tmp_path, sources)) is False


def test_clear_winner_is_certain(tmp_path):
    sources = _srcs(
        tmp_path,
        {
            "main.py": "import util\nif __name__ == '__main__':\n    util.go()",
            "util.py": "def go():\n    pass",
        },
    )
    assert entry_is_certain(rank_entry_candidates(tmp_path, sources)) is True


def test_local_module_names_includes_packages(tmp_path):
    (tmp_path / "pkg").mkdir()
    sources = _srcs(tmp_path, {"main.py": "", "pkg/__init__.py": "", "util.py": ""})
    assert local_module_names(tmp_path, sources) == {"main", "pkg", "util"}
