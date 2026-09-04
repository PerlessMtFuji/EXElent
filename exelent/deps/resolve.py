"""Od importów w kodzie do listy paczek do zainstalowania."""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from exelent.deps.aliases import ALIASES
from exelent.deps.sizes import is_heavy
from exelent.models import Dependency

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?(?:[<>=!~]=?[^\s#]+)?)")
_DIRECT_REF_PREFIXES = ("git+", "hg+", "svn+", "bzr+")
_DIRECT_REF_SUFFIXES = (".whl", ".tar.gz", ".zip")


def _is_direct_reference(spec: str) -> bool:
    """URL-e i referencje VCS/artefaktów — pip akceptuje je dosłownie, bez
    parsowania jako "nazwa[==wersja]"."""
    return (
        "://" in spec
        or spec.startswith(_DIRECT_REF_PREFIXES)
        or spec.endswith(_DIRECT_REF_SUFFIXES)
    )


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
            if _is_direct_reference(stripped):
                specs.append(stripped)
                continue
            match = _REQ_LINE.match(stripped)
            if match:
                specs.append(match.group(1))
        deps_from_req = []
        for spec in sorted(set(specs)):
            base = spec if _is_direct_reference(spec) else re.split(r"[<>=!~\[]", spec)[0]
            deps_from_req.append(
                Dependency(
                    import_name=base,
                    package=spec,
                    heavy=is_heavy(base),
                )
            )
        return tuple(deps_from_req)

    stdlib = sys.stdlib_module_names
    # Klucz to nazwa PAKIETU po aliasowaniu, nie nazwa importu — alias table
    # jest celowo many-to-one (np. win32com/win32api/win32gui/pythoncom ->
    # pywin32, matplotlib/mpl_toolkits -> matplotlib), więc deduplikacja i
    # `optional` muszą liczyć się po stronie rozwiązanego pakietu, inaczej
    # ten sam pakiet trafia na listę dwa razy ze sprzecznymi flagami.
    package_optional: dict[str, bool] = {}
    package_import_names: dict[str, set[str]] = {}

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
                package = ALIASES.get(name, name)
                optional = node.lineno in optional_lines
                package_optional[package] = package_optional.get(package, True) and optional
                package_import_names.setdefault(package, set()).add(name)

    deps = [
        Dependency(
            # Dla pakietu osiąganego wieloma nazwami importu wybieramy
            # alfabetycznie pierwszą — deterministyczny, stabilny wybór.
            import_name=min(package_import_names[package]),
            package=package,
            optional=optional,
            heavy=is_heavy(package),
        )
        for package, optional in package_optional.items()
    ]
    deps.sort(key=lambda d: d.package.lower())
    return tuple(deps)
