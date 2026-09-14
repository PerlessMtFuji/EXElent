"""Leniwy cache sparsowanych drzew AST — jedno parsowanie na plik (B11).

Analiza przechodzi przez wiele etapów (typ aplikacji, punkt wejścia,
importy, zależności, ostrzeżenia), z których KAŻDY potrzebuje AST tych
samych źródeł. Bez cache każdy etap parsuje je od nowa — w projekcie
z 10 plikami to 60–70 wywołań `ast.parse` zamiast 10.

`ParsedSources` jest widokiem nad istniejącym `dict[Path, str]`:
implementuje `Mapping[Path, str]`, więc dotychczasowy kod nie wie,
że dostał cache zamiast zwykłego słownika. Drzewa AST są tworzone
LENIWIE — dopiero przy pierwszym zapytaniu o dany plik.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path


class ParsedSources(Mapping[Path, str]):
    """Mapping[Path, str] z cachowanymi drzewami AST.

    Zachowuje kontrakt ``Mapping[Path, str]`` (klucze = ścieżki, wartości =
    kod źródłowy), więc może zastąpić ``dict[Path, str]`` wszędzie tam,
    gdzie dotychczasowy kod oczekiwał ``Mapping[Path, str]``.

    Drzewa AST są leniwie cachowane: każdy plik jest parsowany co najwyżej
    raz, niezależnie od liczby etapów analizy (B11).
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
        """Zwraca sparsowane AST dla pliku lub ``None`` przy błędzie składni.

        Wynik jest cachowany: powtórne wywołanie dla tej samej ścieżki
        nie parsuje ponownie.
        """
        if path not in self._cache:
            try:
                self._cache[path] = ast.parse(self._sources[path])
            except (SyntaxError, ValueError):
                self._cache[path] = None
        return self._cache[path]

    def trees(self) -> list[ast.Module]:
        """Wszystkie poprawnie sparsowane drzewa."""
        return [t for p in self._sources if (t := self.tree(p)) is not None]
