"""Typ aplikacji, tryb wyjścia i ostrzeżenia o kodzie, którego nie da się
w pełni spakować.

Wybór między ONEFILE a ONEDIR celowo faworyzuje ONEDIR: błędny ONEDIR to co
najwyżej drobna niedogodność (folder zamiast jednego pliku, widoczna od razu
i odwracalna w Advanced), a błędny ONEFILE bezpowrotnie i po cichu kasuje dane
użytkownika zapisane do katalogu tymczasowego PyInstallera. Dlatego lista
wzorców zapisu poniżej jest celowo nadmiarowa, a każdy przypadek niemożliwy
do jednoznacznego udowodnienia (np. zmienna zamiast literału trybu otwarcia
pliku) liczy się jako zapis."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path

from exelent.models import AppKind, Issue, OutputMode, Severity

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

# Nazwy metod/funkcji zapisujących dane na dysk, dopasowywane po samej nazwie
# (bez względu na moduł/odbiorcę) — patrz uzasadnienie w docstringu modułu.
WRITE_METHODS = frozenset(
    {
        # pliki tekstowe/binarne, pandas, matplotlib, opencv
        "dump",
        "to_csv",
        "to_excel",
        "to_json",
        "to_parquet",
        "to_pickle",
        "to_html",
        "to_sql",
        "to_feather",
        "savefig",
        "write_text",
        "write_bytes",
        "imwrite",
        # shutil
        "copy",
        "copy2",
        "copyfile",
        "copytree",
        "move",
        "make_archive",
        # tworzenie katalogów (os / pathlib)
        "mkdir",
        "makedirs",
        # bazy danych
        "connect",
        # handlery logowania do pliku
        "FileHandler",
        "RotatingFileHandler",
        "TimedRotatingFileHandler",
    }
)

# Konstruktory, których zapisowość zależy od trybu otwarcia — sprawdzane
# przez _resolved_mode zamiast trafiać od razu do WRITE_METHODS.
MODE_CHECKED_NAMES = frozenset({"open", "ZipFile"})
WRITE_MODE_CHARS = "wax+"

_SECRET = re.compile(r"['\"](?:sk-|ghp_|AIza|xox[bap]-)[A-Za-z0-9_\-]{16,}['\"]")


def _trees(sources: Mapping[Path, str]) -> list[ast.AST]:
    trees = []
    for code in sources.values():
        try:
            trees.append(ast.parse(code))
        except SyntaxError:
            continue
    return trees


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


def _call_name(func: ast.expr) -> str | None:
    """Nazwa wywoływanej funkcji/metody, bez względu na to, czy wywołanie jest
    postaci `modul.nazwa(...)` czy gołego `nazwa(...)` (import z `from ... import`)."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _resolved_mode(node: ast.Call, pos: int, kw_name: str) -> str | None:
    """Zwraca literał trybu otwarcia, sentinel `"?"` gdy tryb podano, ale nie
    jako literał (a więc nie do udowodnienia — liczy się jako zapis), albo
    `None` gdy trybu w ogóle nie podano (domyślny odczyt)."""
    if len(node.args) > pos:
        arg = node.args[pos]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return "?"
    for kw in node.keywords:
        if kw.arg == kw_name:
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
            return "?"
    return None


def _is_write_mode(mode: str | None) -> bool:
    if mode is None:
        return False
    if mode == "?":
        return True
    return any(ch in mode for ch in WRITE_MODE_CHARS)


def detect_output_mode(sources: Mapping[Path, str]) -> OutputMode:
    for tree in _trees(sources):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name in MODE_CHECKED_NAMES:
                if _is_write_mode(_resolved_mode(node, 1, "mode")):
                    return OutputMode.ONEDIR
            elif name == "basicConfig":
                if any(kw.arg == "filename" for kw in node.keywords):
                    return OutputMode.ONEDIR
            elif name in WRITE_METHODS:
                return OutputMode.ONEDIR
    return OutputMode.ONEFILE


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

    return tuple(issues)
