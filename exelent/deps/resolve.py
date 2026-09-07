"""Od importów w kodzie (i z manifestu) do listy paczek do zainstalowania."""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from exelent.constants import TARGET_PYTHON
from exelent.deps.aliases import ALIASES
from exelent.deps.sizes import is_heavy
from exelent.models import Dependency, Issue, Severity

_DIRECT_REF_PREFIXES = ("git+", "hg+", "svn+", "bzr+")
_DIRECT_REF_SUFFIXES = (".whl", ".tar.gz", ".zip")

# Środowisko markerów DOCELOWEGO builda: zawsze Windows + Python 3.12, bo taki
# EXE powstaje — a nie interpreter, na którym akurat działa EXElent (A07).
# `pkg; sys_platform == "darwin"` ma więc NIE instalować się na Windowsie.
_TARGET_MARKER_ENV = {
    "os_name": "nt",
    "sys_platform": "win32",
    "platform_system": "Windows",
    "platform_machine": "AMD64",
    "python_version": TARGET_PYTHON,
    "python_full_version": f"{TARGET_PYTHON}.0",
    "implementation_name": "cpython",
    "implementation_version": f"{TARGET_PYTHON}.0",
    "platform_python_implementation": "CPython",
}

# Ile poziomów zagnieżdżenia `-r`/`-c` czytamy. Zabezpieczenie na wypadek
# cyklu, którego zbiór odwiedzonych plików mógłby nie złapać (dowiązania).
_MAX_MANIFEST_DEPTH = 20


def _is_direct_reference(spec: str) -> bool:
    """URL-e i referencje VCS/artefaktów — pip akceptuje je dosłownie, bez
    parsowania jako "nazwa[==wersja]"."""
    return (
        "://" in spec
        or spec.startswith(_DIRECT_REF_PREFIXES)
        or spec.endswith(_DIRECT_REF_SUFFIXES)
    )


def _strip_inline_comment(line: str) -> str:
    """Zdejmuje komentarz ` # ...`, nie ruszając `#egg=` w URL-u (bez spacji)."""
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
) -> list[str]:
    """Linie wymagań z pliku, z rozwinięciem `-r`/`-c` względem jego katalogu.

    Cykl i brakujący plik nie wywalają analizy (best-effort), ale zostawiają
    ślad w `issues` (A07): milcząco pominięty `-r` znaczy niekompletną listę
    zależności, o czym użytkownik musi wiedzieć. `stack` to bieżąca ścieżka
    zejścia — cykl to powrót do pliku, który JEST na tej ścieżce; ten sam plik
    dołączony dwiema różnymi gałęziami (diament) to nie cykl, tylko dedup."""
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
        if lowered.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            ref = line.split(None, 1)[1].strip()
            lines.extend(_manifest_lines(path.parent / ref, seen, stack, depth + 1, issues))
        elif line.startswith("-"):
            # Inne opcje pip (-e, --index-url, --hash) nie są nazwą paczki.
            continue
        else:
            lines.append(line)
    stack.pop()
    return lines


def _deps_from_pyproject(path: Path, issues: list[Issue]) -> tuple[Dependency, ...] | None:
    """Zależności z `[project].dependencies` (PEP 621) albo `None`, gdy plik nie
    jest autorytatywny i trzeba spaść do skanu importów.

    `None` znaczy „nie wiem stąd": brak tabeli `[project]`, deklaracja
    `dynamic = ["dependencies"]` (deps są gdzie indziej) albo nieczytelny TOML.
    Jawne `dependencies = []` to co innego — autor mówi „brak zależności", więc
    zwracamy pustą krotkę i NIE zgadujemy z importów. Tabeli `[build-system]`
    nie ruszamy: `requires` to zależności backendu budowania, nie aplikacji."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        issues.append(Issue("pyproject_unreadable", Severity.WARNING, {"file": path.name}))
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    if "dependencies" in project.get("dynamic", []):
        issues.append(Issue("pyproject_dynamic_deps", Severity.WARNING, {"file": path.name}))
        return None
    declared = project.get("dependencies")
    if declared is None:
        return None
    return _deps_from_manifest([spec for spec in declared if isinstance(spec, str)])


def _text_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = _strip_inline_comment(raw)
        # Bez pliku bazowego nie ma jak rozwinąć `-r`, więc opcje pomijamy.
        if line and not line.startswith("-"):
            lines.append(line)
    return lines


def _dep_from_requirement_line(line: str) -> Dependency | None:
    """Jedna linia manifestu -> Dependency, albo None gdy marker ją wyklucza
    dla docelowej platformy lub gdy linia jest niepoprawna."""
    if _is_direct_reference(line):
        return Dependency(import_name=line, package=line, heavy=False)
    try:
        req = Requirement(line)
    except InvalidRequirement:
        return None
    if req.marker is not None and not req.marker.evaluate(_TARGET_MARKER_ENV):
        return None
    extras = f"[{','.join(sorted(req.extras))}]" if req.extras else ""
    # Marker już oceniliśmy — do uv przekazujemy nazwę, extras i wersję, bez
    # markera (i tak instaluje w środowisku Windows/3.12).
    if req.url:
        spec = f"{req.name}{extras} @ {req.url}"
    else:
        spec = f"{req.name}{extras}{req.specifier}"
    return Dependency(import_name=req.name, package=spec, heavy=is_heavy(req.name))


def _deps_from_manifest(lines: list[str]) -> tuple[Dependency, ...]:
    by_package: dict[str, Dependency] = {}
    for line in lines:
        dep = _dep_from_requirement_line(line)
        if dep is not None:
            by_package.setdefault(dep.package, dep)
    return tuple(sorted(by_package.values(), key=lambda d: d.package.lower()))


def _handles_import_error(handler: ast.ExceptHandler) -> bool:
    """Czy ten `except` łapie WŁAŚNIE brak importu.

    Tylko `ImportError`/`ModuleNotFoundError` — nie dowolny wyjątek kończący się
    na `Error`. `try: import x except ValueError` nie czyni `x` opcjonalnym (A07).
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


def _optional_import_lines(tree: ast.AST) -> set[int]:
    """Linie importów, które są OPCJONALNE (nie muszą być zainstalowane).

    Rozbicie gałęzi try/except osobno (A07): przy `try: import orjson / except
    ImportError: import simplejson` gałąź `try` jest PODSTAWOWA (instalujemy ją,
    żeby przynajmniej jedna działała), a gałąź `except` to fallback (opcjonalny).
    Gdy `except` nie ma własnego importu (`numpy = None`), sam import z `try`
    jest opcjonalny — kod radzi sobie z jego brakiem.
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
            # Łańcuch fallbacku: podstawowy import zostaje wymagany, żeby co
            # najmniej jedna gałąź na pewno się zainstalowała.
            optional |= except_lines
        else:
            optional |= try_lines
    return optional


def _deps_from_imports(
    sources: Mapping[Path, str], local_modules: set[str]
) -> tuple[Dependency, ...]:
    """Zależności wykryte ze skanu `import ...` w źródłach.

    Klucz to nazwa PAKIETU po aliasowaniu, nie nazwa importu — alias table
    jest celowo many-to-one (np. win32com/win32api/win32gui/pythoncom ->
    pywin32, matplotlib/mpl_toolkits -> matplotlib), więc deduplikacja i
    `optional` muszą liczyć się po stronie rozwiązanego pakietu."""
    stdlib = sys.stdlib_module_names
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


def _supplement_with_detected(
    manifest_deps: tuple[Dependency, ...],
    scanned: tuple[Dependency, ...],
    issues: list[Issue],
) -> tuple[Dependency, ...]:
    """Manifest jest autorytatywny co do WERSJI, ale wykryte importy spoza
    niego dopisujemy z widocznym śladem (A07).

    Kod dla laika generuje AI, które potrafi pominąć pakiet w `requirements`
    albo zostawić puste `dependencies = []` z samego scaffoldingu — cichy brak
    kończy się EXE witającym „No module named …". Porównujemy po znormalizowanej
    nazwie dystrybucji (PEP 503), więc `import PIL` przy zadeklarowanym `Pillow`
    to ten sam pakiet, a nie rozbieżność. Kierunku odwrotnego (zadeklarowane,
    lecz nieimportowane) NIE zgłaszamy: import dynamiczny, pakiet-dane czy
    wtyczka dałyby fałszywy alarm. `import_name` deklaracji z manifestu niesie
    `Requirement.name` (referencje bezpośrednie: cały URL — nie dopasuje się do
    gołej nazwy importu, co jest tu w porządku)."""
    declared = {canonicalize_name(d.import_name) for d in manifest_deps}
    result = list(manifest_deps)
    for dep in scanned:
        if canonicalize_name(dep.package) in declared:
            continue
        result.append(dep)
        # Brak wymaganego importu łamie EXE → ostrzeżenie. Import opcjonalny
        # (try/except) kod obsługuje sam, więc dopisanie go tylko włącza funkcję
        # → informacja, nie alarm.
        severity = Severity.INFO if dep.optional else Severity.WARNING
        issues.append(Issue("dependency_not_declared", severity, {"package": dep.package}))
    result.sort(key=lambda d: d.package.lower())
    return tuple(result)


def resolve_dependencies(
    sources: Mapping[Path, str],
    local_modules: set[str],
    requirements_text: str | None = None,
    *,
    requirements_path: Path | None = None,
    pyproject_path: Path | None = None,
    issues: list[Issue] | None = None,
) -> tuple[Dependency, ...]:
    # `issues` to opcjonalny kanał diagnostyki (cykl/brak pliku manifestu,
    # nieczytelny pyproject, import spoza manifestu). Domyślnie throwaway, żeby
    # dawni wołający działali bez zmian.
    sink = issues if issues is not None else []
    # Manifest bije zgadywanie WERSJI z importów. Pierwszeństwo jest
    # deterministyczne, nie zależy od kolejności skanowania (A07):
    # requirements.txt (konkretna lista instalacyjna) przed pyproject.toml
    # (deklaracja abstrakcyjna). `None` = brak autorytatywnego manifestu.
    manifest_deps: tuple[Dependency, ...] | None = None
    if requirements_path is not None:
        manifest_deps = _deps_from_manifest(_manifest_lines(requirements_path, set(), [], 0, sink))
    elif requirements_text is not None:
        manifest_deps = _deps_from_manifest(_text_lines(requirements_text))
    elif pyproject_path is not None:
        # `None` stąd = pyproject nieautorytatywny (dynamic/Poetry/nieczytelny).
        manifest_deps = _deps_from_pyproject(pyproject_path, sink)

    scanned = _deps_from_imports(sources, local_modules)
    if manifest_deps is None:
        return scanned
    return _supplement_with_detected(manifest_deps, scanned, sink)
