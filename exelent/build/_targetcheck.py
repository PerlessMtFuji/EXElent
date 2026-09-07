"""Uruchamiane DOCELOWYM interpreterem (np. 3.12), nie deweloperskim.

Kompiluje każde źródło z workspace — KOMPILUJE, nie uruchamia (patrz A05: sama
kontrola składni nie wykonuje programu). Pierwszy plik, który się nie kompiluje,
wypisuje jako `<ścieżka względna>\\t<linia>\\t<komunikat>` i kończy kodem 1;
gdy wszystko się kompiluje — kod 0.

Musi być samowystarczalny (tylko stdlib) i działać pod docelowym Pythonem, bo
odpala go interpreter z venva builda, nie ten, w którym żyje EXElent.
"""

import os
import sys


def main() -> int:
    root = sys.argv[1]
    for dirpath, dirnames, filenames in os.walk(root):
        # __pycache__ to skompilowany bytecode, nie źródła użytkownika.
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "rb") as handle:
                data = handle.read()
            try:
                # Bajty, nie tekst: `compile` honoruje deklarację kodowania
                # (PEP 263) dokładnie tak, jak zrobi to import w gotowym EXE.
                compile(data, path, "exec")
            except SyntaxError as exc:
                rel = os.path.relpath(path, root)
                detail = (exc.msg or "").replace("\t", " ").replace("\n", " ")
                sys.stdout.write(f"{rel}\t{exc.lineno or 0}\t{detail}\n")
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
