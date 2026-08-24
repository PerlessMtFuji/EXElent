"""Typ aplikacji, tryb wyjścia i ostrzeżenia o kodzie, którego nie da się
w pełni spakować."""

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
WRITE_METHODS = frozenset(
    {"dump", "to_csv", "to_excel", "savefig", "write_text", "write_bytes", "imwrite"}
)

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


def detect_output_mode(sources: Mapping[Path, str]) -> OutputMode:
    for tree in _trees(sources):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(ch in mode for ch in "wax+"):
                    return OutputMode.ONEDIR
            elif isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS:
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
