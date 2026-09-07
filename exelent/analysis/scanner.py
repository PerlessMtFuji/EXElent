"""Chodzenie po katalogu użytkownika i klasyfikacja tego, co w nim leży."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from exelent.analysis.textconv import convert_text_to_python
from exelent.constants import (
    EXCLUDED_DIRS,
    MAX_SCAN_BYTES,
    MAX_SCAN_FILES,
    MAX_SINGLE_FILE_IMPORTS,
)
from exelent.models import ScanResult

DATA_SUFFIXES = frozenset(
    {
        ".json",
        ".csv",
        ".txt",
        ".ini",
        ".cfg",
        ".yaml",
        ".yml",
        ".xml",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".wav",
        ".mp3",
        ".ogg",
        ".ttf",
        ".otf",
        ".md",
    }
)
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".ico", ".bmp", ".gif"})
ICON_STEMS = frozenset({"icon", "ikona", "logo", "app", "favicon"})

_CODE_HINT = re.compile(r"^\s*(def |class |import |from \S+ import |print\()", re.MULTILINE)


def looks_like_python(text: str) -> bool:
    """Czy tekst wygląda na kod Pythona, nawet jeśli jeszcze się nie parsuje.

    Kandydatem jest tekst, który albo (a) po konwersji (odcięcie ogrodzeń
    markdown, normalizacja cudzysłowów itd. — patrz `textconv`) parsuje się
    jako prawdziwy Python, albo (b) ma choć jeden strukturalny sygnał kodu
    na początku linii. (a) łapie krótkie, czyste programy wklejone z okna
    czatu, których nie da się odróżnić po samych sygnałach — a to jest
    flagowa ścieżka produktu. (b) nadal łapie zepsuty kod, o którym trzeba
    użytkownika ostrzec, zamiast po cichu zaklasyfikować go jako dane.
    """
    if not text.strip():
        return False
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        pass
    if convert_text_to_python(text.encode("utf-8", errors="replace")).ok:
        return True
    return len(_CODE_HINT.findall(text)) >= 1


def _read_head(path: Path, limit: int = 64_000) -> str:
    """Czyta co najwyżej `limit` bajtów — do rozpoznania rodzaju pliku.

    `read_bytes()[:limit]` wciągało do pamięci CAŁY plik (np. 2 GB .txt) i
    dopiero potem obcinało. Otwieramy i czytamy tylko potrzebny prefiks (A10)."""
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _module_imports(code: str) -> list[tuple[int, str | None, tuple[str, ...]]]:
    """`(poziom, moduł, nazwy)` dla każdego importu. Plik z błędem składni →
    pusta lista: nie wiemy, co importuje, ale to nie powód, żeby go pominąć.

    Poziom > 0 to import względny (`from ..pkg import x`); moduł bywa `None`
    (`from . import helper`); nazwy z `from X import a, b` mogą być podmodułami."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out: list[tuple[int, str | None, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((0, alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append((node.level, node.module, tuple(a.name for a in node.names)))
    return out


def _resolve_module(base: Path, parts: list[str]) -> list[Path]:
    """Pliki modułu `a.b.c` względem `base`: `__init__.py` każdego pakietu po
    drodze plus sam moduł (`a/b/c.py` albo `a/b/c/__init__.py`). Pusta lista,
    gdy moduł nie istnieje lokalnie albo pakiet pośredni nie jest pakietem."""
    if not parts:
        return []
    files: list[Path] = []
    cur = base
    for part in parts[:-1]:
        cur = cur / part
        init = cur / "__init__.py"
        if not init.is_file():
            return []
        files.append(init)
    leaf = cur / f"{parts[-1]}.py"
    package = cur / parts[-1] / "__init__.py"
    if leaf.is_file():
        files.append(leaf)
    elif package.is_file():
        files.append(package)
    else:
        return []
    return files


def _relative_base(current: Path, root: Path, level: int) -> Path | None:
    """Katalog bazowy importu względnego. `None`, gdy `..` wychodzi ponad korzeń
    projektu — to już poza zakresem pojedynczego pliku (nie wciągamy Pobranych)."""
    base = current.parent
    for _ in range(level - 1):
        base = base.parent
    if base == root or root in base.parents:
        return base
    return None


def _import_targets(
    current: Path,
    root: Path,
    level: int,
    module: str | None,
    names: tuple[str, ...],
) -> list[Path]:
    if level == 0:
        base = root
    else:
        found = _relative_base(current, root, level)
        if found is None:
            return []
        base = found
    parts = module.split(".") if module else []
    targets = _resolve_module(base, parts) if parts else []
    # `from X import a` — `a` bywa podmodułem `X` (a dla `from . import a` po
    # prostu modułem w bieżącym pakiecie). Atrybuty (funkcje, klasy) nie
    # rozwiążą się do pliku i po cichu wypadną.
    for name in names:
        targets += _resolve_module(base, [*parts, name])
    return targets


def local_import_closure(
    entry: Path,
    root: Path,
    limit: int = MAX_SINGLE_FILE_IMPORTS,
) -> tuple[tuple[Path, ...], bool]:
    """Moduły lokalne, których potrzebuje `entry`, wraz z ich własnymi.

    Zwraca `(pliki_bez_entry, przekroczono_limit)`. Po przekroczeniu limitu
    wynikiem jest PUSTA krotka, a nie obcięta lista: wciągnięcie losowej
    połowy łańcucha importów dałoby EXE, które wywala się u odbiorcy na
    brakującym module — czyli awarię gorszą i późniejszą niż uczciwe
    „nie dam rady, zostaje sam plik".
    """
    seen: set[Path] = {entry}
    queue = [entry]
    found: list[Path] = []

    while queue:
        current = queue.pop(0)
        code = _read_head(current, limit=1_000_000)
        for level, module, names in _module_imports(code):
            for target in _import_targets(current, root, level, module, names):
                if target in seen:
                    continue
                if len(found) >= limit:
                    return (), True
                seen.add(target)
                found.append(target)
                queue.append(target)

    return tuple(found), False


def scan_directory(
    root: Path,
    *,
    max_files: int = MAX_SCAN_FILES,
    max_bytes: int = MAX_SCAN_BYTES,
) -> ScanResult:
    py: list[Path] = []
    texts: list[Path] = []
    data: list[Path] = []
    icons: list[Path] = []
    requirements: Path | None = None
    pyproject: Path | None = None
    count = 0
    total = 0
    truncated = False

    for dirpath, dirnames, filenames in root.walk():
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            path = dirpath / name
            count += 1
            try:
                total += path.stat().st_size
            except OSError:
                pass
            if count > max_files or total > max_bytes:
                truncated = True
                break

            suffix = path.suffix.lower()
            if suffix in {".py", ".pyw"}:
                py.append(path)
            elif name.lower() == "requirements.txt":
                requirements = path
            elif name.lower() == "pyproject.toml" and pyproject is None:
                # Pierwszy trafiony wygrywa; walk() idzie od korzenia, więc
                # pyproject projektu bije ten z podkatalogu (A07).
                pyproject = path
            elif suffix == ".txt":
                if looks_like_python(_read_head(path)):
                    texts.append(path)
                else:
                    data.append(path)
            elif suffix in IMAGE_SUFFIXES:
                if path.stem.lower() in ICON_STEMS or suffix == ".ico":
                    icons.append(path)
                else:
                    data.append(path)
            elif suffix in DATA_SUFFIXES:
                data.append(path)
        if truncated:
            break

    return ScanResult(
        root=root,
        py_files=tuple(py),
        text_candidates=tuple(texts),
        data_files=tuple(data),
        icon_files=tuple(icons),
        requirements=requirements,
        pyproject=pyproject,
        file_count=count,
        total_bytes=total,
        truncated=truncated,
    )


def scan_single_file(path: Path) -> ScanResult:
    """Skan dla pojedynczego pliku wskazanego przez użytkownika.

    `root` to katalog nadrzędny, bo ścieżki względne w kodzie użytkownika i
    `work_dir_for` potrzebują punktu odniesienia — ale katalog NIE jest
    projektem. Leżące w nim `requirements.txt`, ikona czy pliki danych należą
    do czegoś innego (najczęściej: do folderu Pobrane) i wciągnięcie ich byłoby
    tą samą pomyłką, przed którą ta funkcja broni.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    py: tuple[Path, ...] = ()
    texts: tuple[Path, ...] = ()

    if suffix in {".py", ".pyw"}:
        py = (path,)
    elif suffix == ".txt" and looks_like_python(_read_head(path)):
        texts = (path,)

    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    extra, truncated = local_import_closure(path, path.parent)
    if py:
        py = (path, *extra)
    elif texts:
        # Plik glowny jest kandydatem do konwersji, ale jego sasiedzi to juz
        # zwykly Python — nie przepuszczamy ich przez konwersje.
        py = extra

    return ScanResult(
        root=path.parent,
        py_files=py,
        text_candidates=texts,
        file_count=1,
        total_bytes=size,
        single_file=path,
        truncated=truncated,
    )
