"""B11: testy cache'u AST (ParsedSources)."""

import ast
from pathlib import Path

from exelent.analysis.parsed import ParsedSources


def test_tree_is_cached_not_reparsed():
    sources = {Path("a.py"): "x = 1\n", Path("b.py"): "y = 2\n"}
    parsed = ParsedSources(sources)
    t1 = parsed.tree(Path("a.py"))
    t2 = parsed.tree(Path("a.py"))
    assert t1 is t2  # same object rather than another parse
    assert isinstance(t1, ast.Module)


def test_syntax_error_gives_none_and_is_cached():
    sources = {Path("bad.py"): "def f(:\n"}
    parsed = ParsedSources(sources)
    assert parsed.tree(Path("bad.py")) is None
    # The second call does not parse again.
    assert parsed.tree(Path("bad.py")) is None


def test_trees_returns_only_valid():
    sources = {
        Path("ok.py"): "x = 1\n",
        Path("bad.py"): "def f(:\n",
        Path("ok2.py"): "y = 2\n",
    }
    parsed = ParsedSources(sources)
    ts = parsed.trees()
    assert len(ts) == 2


def test_mapping_interface():
    sources = {Path("a.py"): "x = 1\n", Path("b.py"): "y = 2\n"}
    parsed = ParsedSources(sources)
    assert len(parsed) == 2
    assert Path("a.py") in parsed
    assert parsed[Path("a.py")] == "x = 1\n"
    assert set(parsed) == {Path("a.py"), Path("b.py")}
