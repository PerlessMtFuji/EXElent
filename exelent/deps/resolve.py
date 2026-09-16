"""From code imports (and manifests) to the list of packages to install."""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from exelent.analysis.parsed import ParsedSources
from exelent.constants import TARGET_PYTHON
from exelent.deps.aliases import ALIASES
from exelent.deps.sizes import is_heavy
from exelent.models import Dependency, Issue, Severity

_DIRECT_REF_PREFIXES = ("git+", "hg+", "svn+", "bzr+")
_DIRECT_REF_SUFFIXES = (".whl", ".tar.gz", ".zip")

# Marker environment of the TARGET build: always Windows + Python 3.12 because
# that is the EXE being produced, not the interpreter currently running EXElent.
# Therefore `pkg; sys_platform == "darwin"` must NOT install on Windows.
_TARGET_MARKER_ENV = {
    "os_name": "nt",
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "python_version": TARGET_PYTHON,
    # B05: do not assume patch `.0` — uv installs the newest available version
    # (for example 3.12.11), so `python_full_version >= '3.12.5'` must match.
    # Use a high patch above every real 3.12.x release; when uncertain, INCLUDE
    # the dependency (uv will reject it if the installed interpreter disagrees).
    "python_full_version": f"{TARGET_PYTHON}.99",
    "implementation_name": "cpython",
    "implementation_version": f"{TARGET_PYTHON}.99",
    "platform_python_implementation": "CPython",
}

# Number of nested `-r`/`-c` levels to read. A safeguard against cycles that
# the visited-file set might miss (symlinks).
_MAX_MANIFEST_DEPTH = 20


def _is_direct_reference(spec: str) -> bool:
    """URLs and VCS/artifact references accepted by pip literally, without
    parsing as "name[==version]"."""
    return (
        "://" in spec
        or spec.startswith(_DIRECT_REF_PREFIXES)
        or spec.endswith(_DIRECT_REF_SUFFIXES)
    )


def _strip_inline_comment(line: str) -> str:
    """Strip a ` # ...` comment without touching `#egg=` in a URL (no space)."""
    if line.lstrip().startswith("#"):
        return ""
    for i in range(1, len(line)):
        if line[i] == "#" and line[i - 1] in " \t":
            return line[:i].rstrip()
    return line.strip()


def _manifest_lines(
    path: Path,
    seen: set[Path],
    stack: list[Path],
    depth: int,
    issues: list[Issue],
    *,
    constraints: list[str] | None = None,
) -> list[str]:
    """Requirement lines from a file, expanding `-r`/`-c` relative to its directory.

    A cycle or missing file does not abort best-effort analysis, but leaves an
    entry in `issues`: silently skipping `-r` means an incomplete dependency
    list, which the user must know. `stack` is the current traversal path — a
    cycle returns to a file ON that path; including the same file through two
    branches (a diamond) is deduplication, not a cycle.

    `-c` / `--constraint` supplies version CONSTRAINTS, not installation
    requirements: a `numpy==1.24` entry in a constraint file does NOT install
    numpy; it restricts the version ONLY if numpy is required elsewhere (B05).
    `constraints` collects these lines separately for the caller to apply.
    """
    resolved = path.resolve()
    if resolved in stack:
        issues.append(Issue("requirements_cycle", Severity.WARNING, {"file": path.name}))
        return []
    if depth > _MAX_MANIFEST_DEPTH or resolved in seen:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        issues.append(Issue("requirements_missing", Severity.WARNING, {"file": path.name}))
        return []
    seen.add(resolved)
    stack.append(resolved)

    lines: list[str] = []
    for raw in text.splitlines():
        line = _strip_inline_comment(raw)
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith(("-r ", "--requirement ")):
            ref = line.split(None, 1)[1].strip()
            lines.extend(
                _manifest_lines(
                    path.parent / ref, seen, stack, depth + 1, issues, constraints=constraints
                )
            )
        elif lowered.startswith(("-c ", "--constraint ")):
            ref = line.split(None, 1)[1].strip()
            # Constraint-file lines go to a separate list rather than install
            # requirements (B05). Report a missing file/cycle the same way.
            constraint_lines = _manifest_lines(
                path.parent / ref, seen, stack, depth + 1, issues, constraints=constraints
            )
            if constraints is not None:
                constraints.extend(constraint_lines)
        elif line.startswith("-"):
            # Other pip options (-e, --index-url, --hash) are not package names.
            # Diagnostics: the user must know they were skipped (B05).
            option = line.split()[0] if line.split() else line
            issues.append(
                Issue(
                    "requirements_unsupported_option",
                    Severity.WARNING,
                    {"option": option, "file": path.name},
                )
            )
            continue
        else:
            lines.append(line)
    stack.pop()
    return lines


def _check_requires_python(data: dict, issues: list[Issue], file_name: str) -> None:
    """Check `[project].requires-python` against the target runtime (B05).

    A mismatch does not block the build; it is a warning. The author may have
    declared an imprecise range while the code still works. Only failed syntax
    validation by the target interpreter is blocking (B09).
    """
    project = data.get("project")
    if not isinstance(project, dict):
        return
    requires = project.get("requires-python")
    if not isinstance(requires, str) or not requires.strip():
        return
    try:
        spec = SpecifierSet(requires)
    except InvalidSpecifier:
        return
    if not spec.contains(TARGET_PYTHON, prereleases=True):
        issues.append(
            Issue(
                "requires_python_mismatch",
                Severity.WARNING,
                {"declared": requires, "target": TARGET_PYTHON},
            )
        )


def _deps_from_pyproject(path: Path, issues: list[Issue]) -> tuple[Dependency, ...] | None:
    """Dependencies from `[project].dependencies` (PEP 621), or `None` when the
    file is not authoritative and import scanning must be used.

    `None` means "unknown here": `dynamic = ["dependencies"]` (dependencies
    live elsewhere), unreadable TOML, or no declaration in either PEP 621 or
    Poetry. Explicit `dependencies = []` is different: the author says there
    are no dependencies, so return an empty tuple and do NOT guess from imports.
    Ignore `[build-system]`: its `requires` belong to the build backend, not the
    application.

    Precedence: PEP 621 `[project]` before Poetry `[tool.poetry]`. If `[project]`
    exists, it governs (even when that means `None` -> scan). Read
    `[tool.poetry.dependencies]` ONLY when `[project]` is absent; it is a
    fallback for older Poetry projects predating PEP 621 support."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        issues.append(Issue("pyproject_unreadable", Severity.WARNING, {"file": path.name}))
        return None

    # B05: check `requires-python` against the target runtime.
    _check_requires_python(data, issues, path.name)

    project = data.get("project")
    if isinstance(project, dict):
        if "dependencies" in project.get("dynamic", []):
            issues.append(Issue("pyproject_dynamic_deps", Severity.WARNING, {"file": path.name}))
            return None
        declared = project.get("dependencies")
        if declared is None:
            return None
        return _deps_from_manifest(
            [spec for spec in declared if isinstance(spec, str)], issues=issues
        )
    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        poetry_deps = poetry.get("dependencies")
        if isinstance(poetry_deps, dict):
            return _deps_from_poetry(poetry_deps, issues)
    return None


def _text_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = _strip_inline_comment(raw)
        # Without a base file there is no way to expand `-r`, so skip options.
        if line and not line.startswith("-"):
            lines.append(line)
    return lines


def _dep_from_requirement_line(line: str, issues: list[Issue] | None = None) -> Dependency | None:
    """One manifest line -> Dependency, or None when its marker excludes it
    from the target platform or the line is invalid.

    B05: an invalid line produces diagnostics instead of being skipped silently.
    """
    if _is_direct_reference(line):
        return Dependency(import_name=line, package=line, heavy=False, origin="manifest")
    try:
        req = Requirement(line)
    except InvalidRequirement:
        if issues is not None:
            issues.append(
                Issue(
                    "requirements_invalid_spec",
                    Severity.WARNING,
                    {"spec": line[:120]},
                )
            )
        return None
    if req.marker is not None and not req.marker.evaluate(_TARGET_MARKER_ENV):
        return None
    extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
    # The marker has already been evaluated — pass name, extras, and version to
    # uv without the marker (it installs into Windows/3.12 anyway).
    if req.url:
        spec = f"{req.name}{extras} @ {req.url}"
    else:
        spec = f"{req.name}{extras}{req.specifier}"
    return Dependency(
        import_name=req.name, package=spec, heavy=is_heavy(req.name), origin="manifest"
    )


def _apply_constraints(deps: dict[str, Dependency], constraint_lines: list[str]) -> None:
    """Apply version constraints to existing requirements (B05).

    A constraint restricts a package that is ALREADY required; it does not add
    a new requirement. This is the key difference from `-r`: `-c numpy==1.24`
    alone does not install numpy, but restricts it when another requirement
    requests it. Constraints on packages outside the requirement list are
    ignored according to pip semantics:
    https://pip.pypa.io/en/stable/user_guide/#constraints-files
    """
    if not constraint_lines:
        return
    # Map: normalized name -> specifier from the constraint file.
    constraint_map: dict[str, str] = {}
    for line in constraint_lines:
        if _is_direct_reference(line):
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement:
            continue
        if req.marker is not None and not req.marker.evaluate(_TARGET_MARKER_ENV):
            continue
        constraint_map[canonicalize_name(req.name)] = str(req.specifier)

    # Apply constraints to matching requirements.
    for key, dep in list(deps.items()):
        if _is_direct_reference(dep.package):
            continue
        try:
            req = Requirement(dep.package)
        except InvalidRequirement:
            continue
        canon = canonicalize_name(req.name)
        if canon not in constraint_map:
            continue
        constraint_spec = constraint_map[canon]
        if not constraint_spec:
            continue
        # Scal: oryginalne ograniczenie + constraint. Np. `requests>=2.0` +
        # constraint `requests<3.0` daje `requests>=2.0,<3.0`.
        merged = f"{req.specifier},{constraint_spec}" if str(req.specifier) else constraint_spec
        extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
        new_spec = f"{req.name}{extras}{merged}"
        deps[key] = Dependency(
            import_name=dep.import_name,
            package=new_spec,
            optional=dep.optional,
            heavy=dep.heavy,
            origin=dep.origin,
        )


def _deps_from_manifest(
    lines: list[str],
    constraint_lines: list[str] | None = None,
    issues: list[Issue] | None = None,
) -> tuple[Dependency, ...]:
    by_package: dict[str, Dependency] = {}
    for line in lines:
        dep = _dep_from_requirement_line(line, issues)
        if dep is not None:
            by_package.setdefault(dep.package, dep)
    if constraint_lines:
        _apply_constraints(by_package, constraint_lines)
    return tuple(sorted(by_package.values(), key=lambda d: d.package.lower()))


# --- Poetry [tool.poetry.dependencies] -> PEP 508 --------------------
#
# Poetry stores dependencies as a TABLE (name -> constraint), with its own
# version syntax (`^`, `~`) and a special `python` key. Rather than duplicate
# requirement parsing, translate every entry to a PEP 508 line and pass it
# through existing `_deps_from_manifest`; markers, extras, direct references,
# weight, and deduplication then work exactly as for requirements.txt and
# [project].

_PEP440_OPERATORS = (">=", "<=", "==", "!=", "~=", "===", ">", "<")


def _poetry_caret_upper(version: str) -> str:
    """Upper bound for Poetry's caret (`^`) constraint.

    Rule: increment the MOST significant non-zero component and zero the rest
    (`^1.2.3` -> `<2.0.0`, `^0.2.3` -> `<0.3.0`, `^0.0.3` -> `<0.0.4`). All
    zeros increment the least significant declared component (`^0` -> `<1.0.0`,
    `^0.0` -> `<0.1.0`)."""
    parts = [int(p) for p in version.split(".")]
    for i, value in enumerate(parts):
        if value > 0:
            bumped = [*parts[:i], value + 1, *([0] * (len(parts) - i - 1))]
            while len(bumped) < 3:
                bumped.append(0)
            return ".".join(str(x) for x in bumped)
    upper = [0, 0, 0]
    upper[len(parts) - 1] = 1
    return ".".join(str(x) for x in upper)


def _poetry_tilde_range(version: str) -> str:
    """Tilde constraint `~`: allow changes at the lowest declared level
    (`~1.2.3` and `~1.2` -> `<1.3.0`, `~1` -> `<2.0.0`)."""
    parts = [int(p) for p in version.split(".")]
    upper = f"{parts[0]}.{parts[1] + 1}.0" if len(parts) >= 2 else f"{parts[0] + 1}.0.0"
    return f">={version},<{upper}"


def _poetry_version_spec(constraint: str, issues: list[Issue] | None = None) -> str:
    """Poetry version syntax -> PEP 440 specifier (empty means any version).

    A bare version without an operator means EXACTLY that version (`==`) in
    Poetry, rather than a range as in npm.

    B05: an unsupported constraint is not silently widened; it emits diagnostics.
    """
    c = constraint.strip()
    if c in ("", "*"):
        return ""
    if c.startswith("^"):
        base = c[1:]
        try:
            return f">={base},<{_poetry_caret_upper(base)}"
        except ValueError:
            # A version with a non-numeric suffix (prerelease) has no safely
            # computable upper bound. Instead of silently widening to `>=base`,
            # return the lower bound and report the limitation (B05).
            if issues is not None:
                issues.append(
                    Issue(
                        "poetry_version_fallback",
                        Severity.WARNING,
                        {"constraint": c},
                    )
                )
            return f">={base}"
    if c.startswith("~"):
        base = c[1:]
        try:
            return _poetry_tilde_range(base)
        except ValueError:
            if issues is not None:
                issues.append(
                    Issue(
                        "poetry_version_fallback",
                        Severity.WARNING,
                        {"constraint": c},
                    )
                )
            return f">={base}"
    if c.startswith(_PEP440_OPERATORS) or "," in c:
        return c
    if c.endswith(".*"):
        return f"=={c}"
    return f"=={c}"


def _poetry_python_matches(constraint: str) -> bool:
    """Return whether a `python = "..."` constraint includes target 3.12.

    Compare through `SpecifierSet`, not text markers: comparing
    `python_version < "3.8"` as strings gives the wrong result
    ("3.12" < "3.8")."""
    spec = _poetry_version_spec(constraint)
    if not spec:
        return True
    try:
        return SpecifierSet(spec).contains(TARGET_PYTHON, prereleases=True)
    except InvalidSpecifier:
        return True


def _poetry_entry_to_requirement(
    name: str, spec: object, issues: list[Issue] | None = None
) -> str | None:
    """One `[tool.poetry.dependencies]` entry -> a PEP 508 line or `None`
    (an entry deliberately not installed)."""
    if isinstance(spec, str):
        return f"{name}{_poetry_version_spec(spec, issues)}"
    if isinstance(spec, list):
        # Multiple constraints (different versions for different Pythons): take
        # the first one matching target 3.12.
        for entry in spec:
            line = _poetry_entry_to_requirement(name, entry, issues)
            if line is not None:
                return line
        return None
    if not isinstance(spec, Mapping):
        return None
    if spec.get("optional") is True:
        # An optional Poetry dependency lives behind `extras` and is excluded
        # from the default install. Import scanning will find it if code uses it.
        return None
    python = spec.get("python")
    if isinstance(python, str) and not _poetry_python_matches(python):
        return None
    git = spec.get("git")
    if isinstance(git, str):
        ref = git if git.startswith(_DIRECT_REF_PREFIXES) else f"git+{git}"
        for key in ("rev", "branch", "tag"):
            pin = spec.get(key)
            if isinstance(pin, str):
                ref = f"{ref}@{pin}"
                break
        return f"{name} @ {ref}"
    url = spec.get("url")
    if isinstance(url, str):
        return f"{name} @ {url}"
    if "path" in spec:
        # A local path cannot be installed in the isolated build environment.
        return None
    extras_list = spec.get("extras")
    extras = ""
    if isinstance(extras_list, list):
        names = sorted(e for e in extras_list if isinstance(e, str))
        if names:
            extras = f"[{','.join(names)}]"
    version_spec = spec.get("version")
    version = _poetry_version_spec(version_spec, issues) if isinstance(version_spec, str) else ""
    line = f"{name}{extras}{version}"
    markers = spec.get("markers")
    if isinstance(markers, str) and markers:
        line = f"{line}; {markers}"
    return line


def _deps_from_poetry(table: Mapping, issues: list[Issue] | None = None) -> tuple[Dependency, ...]:
    """Dependencies from `[tool.poetry.dependencies]`. The `python` key is the
    interpreter version rather than a package, so skip it. `_deps_from_manifest`
    resolves markers, extras, and direct references on the generated lines."""
    lines: list[str] = []
    for name, spec in table.items():
        if name.lower() == "python":
            continue
        line = _poetry_entry_to_requirement(name, spec, issues)
        if line is not None:
            lines.append(line)
    return _deps_from_manifest(lines, issues=issues)


def _handles_import_error(handler: ast.ExceptHandler) -> bool:
    """Whether this `except` catches specifically a missing import.

    Only `ImportError`/`ModuleNotFoundError`, not any exception ending in
    `Error`. `try: import x except ValueError` does not make `x` optional.
    """
    node = handler.type
    if isinstance(node, ast.Name):
        names = [node.id]
    elif isinstance(node, ast.Tuple):
        names = [e.id for e in node.elts if isinstance(e, ast.Name)]
    else:
        return False
    return any(n in {"ImportError", "ModuleNotFoundError"} for n in names)


def _import_lines_in(nodes: list[ast.stmt]) -> set[int]:
    lines: set[int] = set()
    for parent in nodes:
        for child in ast.walk(parent):
            if isinstance(child, ast.Import | ast.ImportFrom):
                lines.add(child.lineno)
    return lines


def _dead_import_lines(tree: ast.AST) -> set[int]:
    """Import lines in blocks that NEVER execute at runtime.

    ``if TYPE_CHECKING:`` (from ``typing``) exists solely for static type tools;
    at runtime ``TYPE_CHECKING`` is ``False``. ``if False:`` is a dead branch
    that CPython does not even compile to bytecode. Imports in these blocks are
    not runtime dependencies and should not feed package-install lists.
    """
    dead: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_dead = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Constant) and test.value is False
        )
        if is_dead:
            dead |= _import_lines_in(node.body)
    return dead


def _optional_import_lines(tree: ast.AST) -> set[int]:
    """Import lines that are OPTIONAL (need not be installed).

    Treat try/except branches separately: for `try: import orjson / except
    ImportError: import simplejson`, the `try` branch is PRIMARY (install it so
    at least one works), while the `except` branch is an optional fallback.
    When `except` has no import of its own (`numpy = None`), the import from
    `try` is optional because the code handles its absence.
    """
    optional: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not any(_handles_import_error(h) for h in node.handlers):
            continue
        try_lines = _import_lines_in(node.body)
        except_lines: set[int] = set()
        for handler in node.handlers:
            except_lines |= _import_lines_in(handler.body)
        if except_lines:
            # Fallback chain: keep the primary import required so at least one
            # branch is guaranteed to install.
            optional |= except_lines
        else:
            optional |= try_lines
    return optional


def _deps_from_imports(
    sources: Mapping[Path, str], local_modules: set[str]
) -> tuple[Dependency, ...]:
    """Dependencies detected by scanning source `import ...` statements.

    The key is the aliased PACKAGE name rather than the import name. The alias
    table is intentionally many-to-one (for example win32com/win32api/win32gui/
    pythoncom -> pywin32, matplotlib/mpl_toolkits -> matplotlib), so
    deduplication and `optional` must operate on the resolved package."""
    stdlib = sys.stdlib_module_names
    package_optional: dict[str, bool] = {}
    package_import_names: dict[str, set[str]] = {}

    # B11: use the AST cache when sources is ParsedSources.
    parsed = sources if isinstance(sources, ParsedSources) else ParsedSources(sources)
    for path in sources:
        tree = parsed.tree(path)
        if tree is None:
            continue
        dead_lines = _dead_import_lines(tree)
        optional_lines = _optional_import_lines(tree)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue
                names = [node.module.split(".")[0]]
            if not names or node.lineno in dead_lines:
                continue
            for name in names:
                if name in stdlib or name in local_modules or name.startswith("_"):
                    continue
                package = ALIASES.get(name, name)
                optional = node.lineno in optional_lines
                package_optional[package] = package_optional.get(package, True) and optional
                package_import_names.setdefault(package, set()).add(name)

    deps = [
        Dependency(
            # For a package reached through multiple import names, choose the
            # alphabetically first one for a deterministic, stable result.
            import_name=min(package_import_names[package]),
            package=package,
            optional=optional,
            heavy=is_heavy(package),
            origin="import",
        )
        for package, optional in package_optional.items()
    ]
    deps.sort(key=lambda d: d.package.lower())
    return tuple(deps)


def _supplement_with_detected(
    manifest_deps: tuple[Dependency, ...],
    scanned: tuple[Dependency, ...],
    issues: list[Issue],
) -> tuple[Dependency, ...]:
    """The manifest is authoritative for VERSIONS, but detected imports absent
    from it are appended with a visible trace.

    AI-generated code for non-technical users may omit a package from
    `requirements` or leave scaffolded `dependencies = []`; a silent omission
    yields an EXE greeting the user with "No module named ...". Compare
    normalized distribution names (PEP 503), so `import PIL` with declared
    `Pillow` is the same package, not a discrepancy. Do NOT report the reverse
    direction (declared but not imported): dynamic imports, data packages, or
    plugins would create false alarms. A manifest declaration's `import_name`
    carries `Requirement.name` (for direct references, the full URL, which will
    not match a bare import name — acceptable here)."""
    declared = {canonicalize_name(d.import_name) for d in manifest_deps}
    result = list(manifest_deps)
    for dep in scanned:
        if canonicalize_name(dep.package) in declared:
            continue
        result.append(dep)
        # A missing required import breaks the EXE -> warning. Code handles an
        # optional import (try/except), so adding it merely enables a feature
        # -> information, not an alarm.
        severity = Severity.INFO if dep.optional else Severity.WARNING
        issues.append(Issue("dependency_not_declared", severity, {"package": dep.package}))
    result.sort(key=lambda d: d.package.lower())
    return tuple(result)


def resolve_extra_modules(
    entries: Iterable[str],
    local_modules: set[str],
) -> tuple[tuple[str, ...], tuple[Dependency, ...]]:
    """Modules added MANUALLY by the user because static scanning could not see
    them (dynamic import, plugin, `importlib`) -> (hidden imports, dependencies
    to install).

    Bundle every entry LITERALLY as a PyInstaller hidden import: a dotted name
    (`pkg.plugins.foo`) stays whole because that is the submodule PyInstaller
    missed. The TOP-LEVEL name also becomes a package to install (after aliasing,
    such as `sklearn` -> `scikit-learn`) unless it is a standard-library or local
    module, so `--hidden-import` has something to import. Deduplicate hidden
    imports by literal entry and packages by aliased name."""
    stdlib = sys.stdlib_module_names
    hidden: list[str] = []
    seen: set[str] = set()
    by_package: dict[str, Dependency] = {}
    for raw in entries:
        name = raw.strip()
        if not name:
            continue
        if name not in seen:
            seen.add(name)
            hidden.append(name)
        top = name.split(".")[0]
        if not top or top in stdlib or top in local_modules or top.startswith("_"):
            continue
        package = ALIASES.get(top, top)
        by_package.setdefault(
            package,
            Dependency(import_name=top, package=package, heavy=is_heavy(package), origin="user"),
        )
    deps = tuple(sorted(by_package.values(), key=lambda d: d.package.lower()))
    return tuple(hidden), deps


def _deps_from_hidden_imports(
    hidden: tuple[str, ...], local_modules: set[str]
) -> tuple[Dependency, ...]:
    """Dependencies from dynamic imports (`importlib.import_module('PIL.Image')`).

    Hidden imports are passed to PyInstaller's `--hidden-import`, but PyInstaller
    does NOT install them; the build environment must. Previously `PIL.Image` as
    a hidden import did not feed the package-install list, so `Pillow` was not
    installed unless it appeared separately in the manifest or a regular
    `import PIL`. (B04: dynamic imports feed both hidden imports and dependencies.)
    """
    stdlib = sys.stdlib_module_names
    by_package: dict[str, Dependency] = {}
    for name in hidden:
        top = name.split(".")[0]
        if not top or top in stdlib or top in local_modules or top.startswith("_"):
            continue
        package = ALIASES.get(top, top)
        by_package.setdefault(
            package,
            Dependency(import_name=top, package=package, heavy=is_heavy(package), origin="dynamic"),
        )
    return tuple(sorted(by_package.values(), key=lambda d: d.package.lower()))


def resolve_dependencies(
    sources: Mapping[Path, str],
    local_modules: set[str],
    requirements_text: str | None = None,
    *,
    requirements_path: Path | None = None,
    pyproject_path: Path | None = None,
    hidden_imports: tuple[str, ...] = (),
    issues: list[Issue] | None = None,
) -> tuple[Dependency, ...]:
    # `issues` is an optional diagnostics channel (manifest cycle/missing file,
    # unreadable pyproject, import absent from manifest). It defaults to a
    # throwaway list so older callers keep working unchanged.
    sink = issues if issues is not None else []
    # The manifest outranks VERSION guessing from imports. Precedence is
    # deterministic and independent of scan order: requirements.txt (a concrete
    # install list) before pyproject.toml.
    # (deklaracja abstrakcyjna). `None` = brak autorytatywnego manifestu.
    manifest_deps: tuple[Dependency, ...] | None = None
    if requirements_path is not None:
        constraints: list[str] = []
        req_lines = _manifest_lines(requirements_path, set(), [], 0, sink, constraints=constraints)
        manifest_deps = _deps_from_manifest(req_lines, constraints or None, issues=sink)
    elif requirements_text is not None:
        manifest_deps = _deps_from_manifest(_text_lines(requirements_text), issues=sink)
    elif pyproject_path is not None:
        # `None` here means a non-authoritative pyproject (dynamic/Poetry/unreadable).
        manifest_deps = _deps_from_pyproject(pyproject_path, sink)

    # Static + dynamic imports both feed the dependency list (B04).
    scanned = _deps_from_imports(sources, local_modules)
    dynamic = _deps_from_hidden_imports(hidden_imports, local_modules)
    # Merge dynamic into static imports, deduplicating by package.
    if dynamic:
        by_package = {d.package.lower(): d for d in scanned}
        for dep in dynamic:
            by_package.setdefault(dep.package.lower(), dep)
        scanned = tuple(sorted(by_package.values(), key=lambda d: d.package.lower()))

    if manifest_deps is None:
        return scanned
    return _supplement_with_detected(manifest_deps, scanned, sink)
