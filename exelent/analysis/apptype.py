"""App type (windowed vs console) and warnings about code that cannot be
fully packaged.

The output mode (single EXE file vs folder) is NOT decided by source
analysis. Previously a heuristic "does the program write to disk" did this:
no detected writes resulted in ONEFILE, which set the working directory to
``sys._MEIPASS`` — a temporary extraction directory that vanishes when the
process exits. Writes via an alias like ``open``, ``Image.save`` or any
pattern not in the list escaped the heuristic, ended up in ONEFILE and were
lost. Absence of a detected write is not proof that the program writes
nothing (B01), so the recommended and default mode is now always ONEDIR —
see ``planning.onefile_limitation_issues`` and the launcher, which in both
modes anchors cwd in the persistent EXE directory.
"""

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

# Packages whose internal submodules are not fully detected by PyInstaller's
# default analysis.  When the user imports one of these top-level names,
# we tell PyInstaller to recursively collect the listed subpackage trees
# (``--collect-submodules``).  Entries are the *import* name, not the pip name.
PACKAGE_COLLECT_SUBMODULES: dict[str, tuple[str, ...]] = {
    "scipy": ("scipy._external.array_api_compat",),
}

_SECRET = re.compile(r"['\"](?:sk-|ghp_|AIza|xox[bap]-)[A-Za-z0-9_\-]{16,}['\"]")


def _ensure_parsed(sources: Mapping[Path, str]) -> ParsedSources:
    """Wrap a plain dict in ParsedSources if needed (B11)."""
    if isinstance(sources, ParsedSources):
        return sources
    return ParsedSources(sources)


def _trees(sources: Mapping[Path, str]) -> list[ast.AST]:
    parsed = _ensure_parsed(sources)
    return parsed.trees()


def _is_dead_branch(node: ast.If) -> bool:
    """``if TYPE_CHECKING:`` or ``if False:`` block — never executes at runtime."""
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Constant) and test.value is False
    )


def _dead_import_lines(tree: ast.AST) -> set[int]:
    """Lines of imports in dead branches (``if TYPE_CHECKING`` / ``if False``)."""
    dead: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_dead_branch(node):
            for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(child, ast.Import | ast.ImportFrom):
                    dead.add(child.lineno)
    return dead


def _top_imports(sources: Mapping[Path, str]) -> set[str]:
    names: set[str] = set()
    for tree in _trees(sources):
        dead_lines = _dead_import_lines(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and node.lineno not in dead_lines:
                names.update(a.name.split(".")[0] for a in node.names)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and not node.level
                and node.lineno not in dead_lines
            ):
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


def package_submodule_collections(top_imports: set[str]) -> tuple[str, ...]:
    """Subpackage trees that need ``--collect-submodules`` for *top_imports*.

    PyInstaller's default analysis misses lazily-loaded or vendored internal
    subpackages in some libraries.  ``--collect-submodules`` tells it to
    enumerate and bundle them recursively — more resilient than listing each
    submodule path individually, since it tracks the installed version.
    """
    entries: list[str] = []
    for pkg, subs in PACKAGE_COLLECT_SUBMODULES.items():
        if pkg in top_imports:
            entries.extend(subs)
    return tuple(sorted(set(entries)))


def _is_meipass_access(node: ast.AST) -> bool:
    """Recognizes ``sys._MEIPASS`` and ``getattr(sys, '_MEIPASS', ...)``."""
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
    """Detects use of ``__file__`` and ``sys._MEIPASS`` in user code.

    Both patterns reference a location that changes after packaging by
    PyInstaller: ``__file__`` points to the extraction directory in ONEFILE
    mode (not the EXE directory), and ``_MEIPASS`` does not exist during
    normal execution. A program that builds paths to write or read resources
    based on them may behave differently than the author intended.

    We do not rewrite paths in other people's code (B01). Instead we inform
    the user BEFORE building that these patterns were detected, and describe
    the limitations — without presenting the heuristic as a guarantee.
    """
    found: list[str] = []
    for tree in _trees(sources):
        for node in ast.walk(tree):
            # __file__ used as a value (not in a left-hand assignment)
            if isinstance(node, ast.Name) and node.id == "__file__":
                if "__file__" not in found:
                    found.append("__file__")
            # sys._MEIPASS or getattr(sys, '_MEIPASS', ...)
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
