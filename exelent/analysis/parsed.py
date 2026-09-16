"""Lazy cache of parsed AST trees — one parse per file (B11).

Analysis goes through many stages (app type, entry point, imports,
dependencies, warnings), ALL of which need the AST of the same sources.
Without a cache each stage would parse them from scratch — in a project
with 10 files that means 60–70 calls to ``ast.parse`` instead of 10.

``ParsedSources`` is a view over an existing ``dict[Path, str]``:
it implements ``Mapping[Path, str]``, so existing code does not know
it got a cache instead of a plain dictionary. AST trees are created
LAZILY — only on the first access to a given file.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path


class ParsedSources(Mapping[Path, str]):
    """Mapping[Path, str] with cached AST trees.

    Maintains the ``Mapping[Path, str]`` contract (keys = paths, values =
    source code), so it can replace ``dict[Path, str]`` everywhere that
    existing code expects ``Mapping[Path, str]``.

    AST trees are lazily cached: each file is parsed at most once,
    regardless of the number of analysis stages (B11).
    """

    __slots__ = ("_cache", "_sources")

    def __init__(self, sources: Mapping[Path, str]) -> None:
        self._sources = sources
        self._cache: dict[Path, ast.Module | None] = {}

    # --- Mapping[Path, str] interface ---

    def __getitem__(self, key: Path) -> str:
        return self._sources[key]

    def __iter__(self) -> Iterator[Path]:
        return iter(self._sources)

    def __len__(self) -> int:
        return len(self._sources)

    # --- AST cache ---

    def tree(self, path: Path) -> ast.Module | None:
        """Return the parsed AST for a file, or ``None`` on syntax error.

        The result is cached: a repeat call for the same path does not
        re-parse.
        """
        if path not in self._cache:
            try:
                self._cache[path] = ast.parse(self._sources[path])
            except (SyntaxError, ValueError):
                self._cache[path] = None
        return self._cache[path]

    def trees(self) -> list[ast.Module]:
        """All successfully parsed trees."""
        return [t for p in self._sources if (t := self.tree(p)) is not None]
