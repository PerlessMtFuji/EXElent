"""Chodzenie po katalogu użytkownika i klasyfikacja tego, co w nim leży."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from exelent.analysis.textconv import convert_text_to_python
from exelent.constants import EXCLUDED_DIRS, MAX_SCAN_BYTES, MAX_SCAN_FILES
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
    try:
        return path.read_bytes()[:limit].decode("utf-8", errors="replace")
    except OSError:
        return ""


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

    return ScanResult(
        root=path.parent,
        py_files=py,
        text_candidates=texts,
        file_count=1,
        total_bytes=size,
        single_file=path,
    )
