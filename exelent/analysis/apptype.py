"""Typ aplikacji (okno vs konsola) i ostrzeżenia o kodzie, którego nie da się
w pełni spakować.

O trybie wyjścia (jeden plik EXE vs folder) NIE decyduje analiza źródeł.
Wcześniej robiła to heurystyka „czy program zapisuje na dysk": brak wykrytego
zapisu dawał ONEFILE, a ten ustawiał katalog roboczy na `sys._MEIPASS` —
tymczasowy katalog rozpakowania, który znika przy zakończeniu procesu. Zapis
przez alias `open`, `Image.save` czy dowolny wzorzec spoza listy wymykał się
heurystyce, trafiał do ONEFILE i ginął. Brak rozpoznanego zapisu nie jest
dowodem, że program niczego nie zapisuje (B01), więc zalecanym i domyślnym
trybem jest teraz zawsze ONEDIR — patrz `planning.onefile_limitation_issues`
oraz launcher, który w obu trybach kotwiczy cwd w trwałym katalogu EXE."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path

from exelent.analysis.parsed import ParsedSources
from exelent.models import AppKind, Issue, Severity

GUI_MODULES = frozenset(
    {
        "tkinter",
        "PySide6",
        "PySide2",
        "PyQt5",
        "PyQt6",
        "kivy",
        "pygame",
        "customtkinter",
        "wx",
        "flet",
        "ttkbootstrap",
        "dearpygui",
    }
)
SERVER_MODULES = frozenset({"flask", "fastapi", "django", "aiohttp", "bottle", "starlette"})
EXTERNAL_TOOLS = frozenset({"ffmpeg", "ffprobe", "tesseract", "magick", "pandoc", "yt-dlp"})

_SECRET = re.compile(r"['\"](?:sk-|ghp_|AIza|xox[bap]-)[A-Za-z0-9_\-]{16,}['\"]")


def _ensure_parsed(sources: Mapping[Path, str]) -> ParsedSources:
    """Opakowuje zwykly dict w ParsedSources jesli trzeba (B11)."""
    if isinstance(sources, ParsedSources):
        return sources
    return ParsedSources(sources)


def _trees(sources: Mapping[Path, str]) -> list[ast.AST]:
    parsed = _ensure_parsed(sources)
    return parsed.trees()


def _top_imports(sources: Mapping[Path, str]) -> set[str]:
    names: set[str] = set()
    for tree in _trees(sources):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
    return names


def _calls_named(sources: Mapping[Path, str], name: str) -> bool:
    for tree in _trees(sources):
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
            ):
                return True
    return False


def detect_app_kind(sources: Mapping[Path, str]) -> tuple[AppKind, bool]:
    gui = bool(_top_imports(sources) & GUI_MODULES)
    console = _calls_named(sources, "input")
    if gui:
        return AppKind.WINDOWED, not console
    return AppKind.CONSOLE, True


def _dynamic_imports(sources: Mapping[Path, str]) -> tuple[list[str], bool]:
    literals: list[str] = []
    unresolved = False
    for tree in _trees(sources):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_dynamic = (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
                isinstance(func, ast.Name) and func.id == "__import__"
            )
            if not is_dynamic or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                literals.append(arg.value)
            else:
                unresolved = True
    return literals, unresolved


def collect_hidden_imports(sources: Mapping[Path, str]) -> tuple[str, ...]:
    literals, _ = _dynamic_imports(sources)
    return tuple(sorted(set(literals)))


def _is_meipass_access(node: ast.AST) -> bool:
    """Rozpoznaje ``sys._MEIPASS`` i ``getattr(sys, '_MEIPASS', ...)``."""
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "_MEIPASS"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    ):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "sys"
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "_MEIPASS"
    )


def _frozen_path_patterns(sources: Mapping[Path, str]) -> list[str]:
    """Wykrywa uzycie ``__file__`` i ``sys._MEIPASS`` w kodzie uzytkownika.

    Oba wzorce odwoluja sie do lokalizacji, ktora zmienia sie po spakowaniu
    przez PyInstaller: ``__file__`` wskazuje na katalog rozpakowania w trybie
    ONEFILE (nie na katalog EXE), a ``_MEIPASS`` nie istnieje przy normalnym
    uruchomieniu. Program, ktory na ich podstawie buduje sciezki do zapisu lub
    odczytu zasobow, moze dzialac inaczej niz zamierzal autor.

    Nie przepisujemy sciezek w cudzym kodzie (B01). Zamiast tego informujemy
    uzytkownika PRZED budowaniem, ze te wzorce zostaly rozpoznane, i opisujemy
    ograniczenia — bez przedstawiania heurystyki jako gwarancji.
    """
    found: list[str] = []
    for tree in _trees(sources):
        for node in ast.walk(tree):
            # __file__ uzyte jako wartosc (nie w przypisaniu lewostronnym)
            if isinstance(node, ast.Name) and node.id == "__file__":
                if "__file__" not in found:
                    found.append("__file__")
            # sys._MEIPASS lub getattr(sys, '_MEIPASS', ...)
            elif "_MEIPASS" not in found and _is_meipass_access(node):
                found.append("_MEIPASS")
    return found


def collect_code_issues(sources: Mapping[Path, str]) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    imports = _top_imports(sources)

    for module in sorted(imports & SERVER_MODULES):
        issues.append(Issue("server_app", Severity.WARNING, {"framework": module}))

    joined = "\n".join(sources.values())
    for tool in sorted(EXTERNAL_TOOLS):
        if re.search(rf"['\"]{re.escape(tool)}(?:\.exe)?['\"]", joined):
            issues.append(Issue("external_tool", Severity.WARNING, {"tool": tool}))

    if _SECRET.search(joined):
        issues.append(Issue("secrets_in_code", Severity.WARNING))

    _, unresolved = _dynamic_imports(sources)
    if unresolved:
        issues.append(Issue("dynamic_import_unresolved", Severity.WARNING))

    for pattern in _frozen_path_patterns(sources):
        issues.append(Issue("frozen_path_pattern", Severity.WARNING, {"pattern": pattern}))

    return tuple(issues)
