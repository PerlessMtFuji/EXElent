"""Od importów w kodzie do listy paczek do zainstalowania."""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from exelent.deps.aliases import ALIASES, HEAVY_PACKAGES
from exelent.models import Dependency

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?(?:[<>=!~]=?[^\s#]+)?)")


def _optional_import_lines(tree: ast.AST) -> set[int]:
    """Numery linii importów siedzących w try/except ImportError."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        handles_import = any(
            isinstance(h.type, ast.Name)
            and h.type.id in {"ImportError", "ModuleNotFoundError"}
            or (
                isinstance(h.type, ast.Tuple)
                and any(isinstance(e, ast.Name) and e.id.endswith("Error") for e in h.type.elts)
            )
            for h in node.handlers
        )
        if not handles_import:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Import | ast.ImportFrom):
                lines.add(child.lineno)
    return lines


def resolve_dependencies(
    sources: Mapping[Path, str],
    local_modules: set[str],
    requirements_text: str | None = None,
) -> tuple[Dependency, ...]:
    if requirements_text is not None:
        specs: list[str] = []
        for line in requirements_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-")):
                continue
            match = _REQ_LINE.match(stripped)
            if match:
                specs.append(match.group(1))
        return tuple(
            Dependency(
                import_name=re.split(r"[<>=!~\[]", spec)[0],
                package=spec,
                heavy=re.split(r"[<>=!~\[]", spec)[0] in HEAVY_PACKAGES,
            )
            for spec in sorted(set(specs))
        )

    stdlib = sys.stdlib_module_names
    found: dict[str, bool] = {}

    for code in sources.values():
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        optional_lines = _optional_import_lines(tree)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue
                names = [node.module.split(".")[0]]
            for name in names:
                if name in stdlib or name in local_modules or name.startswith("_"):
                    continue
                optional = node.lineno in optional_lines
                found[name] = found.get(name, True) and optional

    deps = [
        Dependency(
            import_name=name,
            package=ALIASES.get(name, name),
            optional=optional,
            heavy=ALIASES.get(name, name) in HEAVY_PACKAGES,
        )
        for name, optional in found.items()
    ]
    deps.sort(key=lambda d: d.package.lower())
    return tuple(deps)
