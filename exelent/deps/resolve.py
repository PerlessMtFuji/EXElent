"""Od importów w kodzie (i z manifestu) do listy paczek do zainstalowania."""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
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

    `None` znaczy „nie wiem stąd": deklaracja `dynamic = ["dependencies"]` (deps
    są gdzie indziej), nieczytelny TOML albo brak jakiejkolwiek deklaracji — ani
    PEP 621, ani Poetry. Jawne `dependencies = []` to co innego — autor mówi
    „brak zależności", więc zwracamy pustą krotkę i NIE zgadujemy z importów.
    Tabeli `[build-system]` nie ruszamy: `requires` to zależności backendu
    budowania, nie aplikacji.

    Pierwszeństwo: PEP 621 `[project]` przed Poetry `[tool.poetry]`. Gdy tabela
    `[project]` istnieje, ona rządzi (nawet gdy to znaczy `None` -> skan);
    `[tool.poetry.dependencies]` czytamy TYLKO, gdy `[project]` nie ma wcale —
    to fallback dla starszych projektów Poetry (przed jego wsparciem PEP 621)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        issues.append(Issue("pyproject_unreadable", Severity.WARNING, {"file": path.name}))
        return None
    project = data.get("project")
    if isinstance(project, dict):
        if "dependencies" in project.get("dynamic", []):
            issues.append(Issue("pyproject_dynamic_deps", Severity.WARNING, {"file": path.name}))
            return None
        declared = project.get("dependencies")
        if declared is None:
            return None
        return _deps_from_manifest([spec for spec in declared if isinstance(spec, str)])
    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        poetry_deps = poetry.get("dependencies")
        if isinstance(poetry_deps, dict):
            return _deps_from_poetry(poetry_deps)
    return None


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


# --- Poetry [tool.poetry.dependencies] -> PEP 508 (A07) --------------------
#
# Poetry trzyma zależności jako TABELĘ (nazwa -> ograniczenie), z własną
# składnią wersji (`^`, `~`) i specjalnym kluczem `python`. Zamiast dublować
# parser wymagań, tłumaczymy każdy wpis na linię PEP 508 i przepuszczamy przez
# istniejące `_deps_from_manifest` — dzięki temu markery, extras, referencje
# bezpośrednie, ciężkość i deduplikacja działają dokładnie tak samo jak dla
# requirements.txt i [project].

_PEP440_OPERATORS = (">=", "<=", "==", "!=", "~=", "===", ">", "<")


def _poetry_caret_upper(version: str) -> str:
    """Górna granica ograniczenia karetowego `^` Poetry.

    Reguła: podnieś NAJBARDZIEJ znaczący niezerowy człon i wyzeruj resztę
    (`^1.2.3` -> `<2.0.0`, `^0.2.3` -> `<0.3.0`, `^0.0.3` -> `<0.0.4`). Same
    zera podnoszą najmniej znaczący zadeklarowany człon (`^0` -> `<1.0.0`,
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
    """Ograniczenie tyldowe `~`: dopuszcza zmiany na najniższym zadeklarowanym
    poziomie (`~1.2.3` i `~1.2` -> `<1.3.0`, `~1` -> `<2.0.0`)."""
    parts = [int(p) for p in version.split(".")]
    upper = f"{parts[0]}.{parts[1] + 1}.0" if len(parts) >= 2 else f"{parts[0] + 1}.0.0"
    return f">={version},<{upper}"


def _poetry_version_spec(constraint: str) -> str:
    """Wersja w składni Poetry -> specyfikator PEP 440 (pusty = dowolna).

    Goła wersja bez operatora znaczy w Poetry DOKŁADNIE tę wersję (`==`), a nie
    zakres — inaczej niż w npm."""
    c = constraint.strip()
    if c in ("", "*"):
        return ""
    if c.startswith("^"):
        base = c[1:]
        try:
            return f">={base},<{_poetry_caret_upper(base)}"
        except ValueError:
            # Wersja z przedrostkiem nienumerycznym (prerelease) — bezpieczna
            # dolna granica zamiast wywalania całej analizy.
            return f">={base}"
    if c.startswith("~"):
        base = c[1:]
        try:
            return _poetry_tilde_range(base)
        except ValueError:
            return f">={base}"
    if c.startswith(_PEP440_OPERATORS) or "," in c:
        return c
    if c.endswith(".*"):
        return f"=={c}"
    return f"=={c}"


def _poetry_python_matches(constraint: str) -> bool:
    """Czy ograniczenie `python = "..."` obejmuje docelowego 3.12.

    Porównujemy przez `SpecifierSet`, nie przez marker tekstowy: `python_version
    < "3.8"` porównywane jako napisy dałoby błędny wynik ("3.12" < "3.8")."""
    spec = _poetry_version_spec(constraint)
    if not spec:
        return True
    try:
        return SpecifierSet(spec).contains(TARGET_PYTHON, prereleases=True)
    except InvalidSpecifier:
        return True


def _poetry_entry_to_requirement(name: str, spec: object) -> str | None:
    """Jeden wpis `[tool.poetry.dependencies]` -> linia PEP 508 albo `None`
    (wpis, którego świadomie nie instalujemy)."""
    if isinstance(spec, str):
        return f"{name}{_poetry_version_spec(spec)}"
    if isinstance(spec, list):
        # Wiele ograniczeń (różna wersja dla różnych Pythonów) — bierzemy
        # pierwsze pasujące do docelowego 3.12.
        for entry in spec:
            line = _poetry_entry_to_requirement(name, entry)
            if line is not None:
                return line
        return None
    if not isinstance(spec, Mapping):
        return None
    if spec.get("optional") is True:
        # Zależność opcjonalna Poetry żyje za `extras` i nie wchodzi do
        # domyślnej instalacji. Jeśli kod ją importuje, złapie ją skan importów.
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
        # Lokalnej ścieżki nie zainstalujemy w izolowanym środowisku builda.
        return None
    extras_list = spec.get("extras")
    extras = ""
    if isinstance(extras_list, list):
        names = sorted(e for e in extras_list if isinstance(e, str))
        if names:
            extras = f"[{','.join(names)}]"
    version_spec = spec.get("version")
    version = _poetry_version_spec(version_spec) if isinstance(version_spec, str) else ""
    line = f"{name}{extras}{version}"
    markers = spec.get("markers")
    if isinstance(markers, str) and markers:
        line = f"{line}; {markers}"
    return line


def _deps_from_poetry(table: Mapping) -> tuple[Dependency, ...]:
    """Zależności z `[tool.poetry.dependencies]`. Klucz `python` to wersja
    interpretera, nie pakiet — pomijamy go. Markery, extras i referencje
    bezpośrednie rozstrzyga już `_deps_from_manifest` na gotowych liniach."""
    lines: list[str] = []
    for name, spec in table.items():
        if name.lower() == "python":
            continue
        line = _poetry_entry_to_requirement(name, spec)
        if line is not None:
            lines.append(line)
    return _deps_from_manifest(lines)


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


def resolve_extra_modules(
    entries: Iterable[str],
    local_modules: set[str],
) -> tuple[tuple[str, ...], tuple[Dependency, ...]]:
    """Moduły dopisane RĘCZNIE przez użytkownika, których statyczny skan nie mógł
    zobaczyć (import dynamiczny, wtyczka, `importlib`) -> (ukryte importy,
    zależności do instalacji) (A07).

    Każdy wpis pakujemy DOSŁOWNIE jako ukryty import PyInstallera — nazwa z
    kropką (`pkg.plugins.foo`) zostaje w całości, bo to właśnie submoduł, którego
    PyInstaller sam nie znalazł. Nazwa NAJWYŻSZEGO poziomu staje się dodatkowo
    pakietem do instalacji (po aliasie: `sklearn` -> `scikit-learn`), chyba że to
    moduł biblioteki standardowej albo lokalny — żeby `--hidden-import` miał co
    zaimportować. Deduplikacja: ukryte importy po dosłownym wpisie, pakiety po
    nazwie po aliasie."""
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
            package, Dependency(import_name=top, package=package, heavy=is_heavy(package))
        )
    deps = tuple(sorted(by_package.values(), key=lambda d: d.package.lower()))
    return tuple(hidden), deps


def _deps_from_hidden_imports(
    hidden: tuple[str, ...], local_modules: set[str]
) -> tuple[Dependency, ...]:
    """Zależności z dynamicznych importów (`importlib.import_module('PIL.Image')`).

    Ukryte importy trafiają do `--hidden-import` PyInstallera, ale sam PyInstaller
    ich NIE zainstaluje — musi to zrobić środowisko builda. Dotąd `PIL.Image` jako
    hidden import nie zasilał listy paczek do instalacji, więc `Pillow` nie był
    instalowany, chyba że pojawiał się osobno w manifestie lub zwykłym `import PIL`.
    (B04: dynamiczne importy zasilają zarówno hidden imports, jak i zależności.)
    """
    stdlib = sys.stdlib_module_names
    by_package: dict[str, Dependency] = {}
    for name in hidden:
        top = name.split(".")[0]
        if not top or top in stdlib or top in local_modules or top.startswith("_"):
            continue
        package = ALIASES.get(top, top)
        by_package.setdefault(
            package, Dependency(import_name=top, package=package, heavy=is_heavy(package))
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

    # Import statyczny + dynamiczny: oba zasilają listę zależności (B04).
    scanned = _deps_from_imports(sources, local_modules)
    dynamic = _deps_from_hidden_imports(hidden_imports, local_modules)
    # Scalenie: dynamiczne dopisują do statycznych, deduplikacja po pakiecie.
    if dynamic:
        by_package = {d.package.lower(): d for d in scanned}
        for dep in dynamic:
            by_package.setdefault(dep.package.lower(), dep)
        scanned = tuple(sorted(by_package.values(), key=lambda d: d.package.lower()))

    if manifest_deps is None:
        return scanned
    return _supplement_with_detected(manifest_deps, scanned, sink)
