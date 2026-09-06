"""Orkiestracja analizy: katalog na wejściu, ProjectAnalysis na wyjściu.

Nic tu nie zapisuje na dysk. Konwersja TXT żyje w pamięci aż do zadania,
które tworzy kopię roboczą — katalog użytkownika pozostaje nietknięty.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from exelent.analysis.apptype import (
    collect_code_issues,
    collect_hidden_imports,
    detect_app_kind,
    detect_output_mode,
)
from exelent.analysis.entrypoint import entry_is_certain, local_module_names, rank_entry_candidates
from exelent.analysis.scanner import scan_directory, scan_single_file
from exelent.analysis.textconv import NO_CODE, convert_text_to_python
from exelent.deps.resolve import resolve_dependencies
from exelent.deps.sizes import LARGE_WARNING_MB, estimate_exe_size
from exelent.models import Issue, ProjectAnalysis, ScanResult, Severity

OTHER_LANGUAGE_SUFFIXES = {".js", ".ts", ".java", ".cs", ".cpp", ".c", ".go", ".rb", ".php"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _rel_key(root: Path, path: Path) -> str:
    """Znormalizowany klucz sciezki wzgledem korzenia — do wykrywania kolizji.

    Male litery, bo Windows nie rozroznia wielkosci liter: `Main.py` i `main.py`
    to na dysku ten sam plik."""
    return path.relative_to(root).as_posix().lower()


def _detect_other_language(scan: ScanResult) -> str | None:
    """Sufiks jezyka, jesli to on wypelnia projekt zamiast Pythona.

    W trybie jednoplikowym `scan.root` to katalog NADRZEDNY dropnietego pliku —
    zwykle cudzy folder (Pobrane). Chodzenie po nim (`rglob`) to dokladnie ta
    szkoda, ktora zadanie 7 mialo usunac: pojedynczy dropniety plik nie moze
    uruchamiac skanu calego sasiedztwa. Sygnal jednoplikowy jest wiec wziety
    wylacznie z sufiksu dropnietego pliku, bez zadnego chodzenia po dysku.
    """
    if scan.single_file is not None:
        suffix = scan.single_file.suffix.lower()
        return suffix if suffix in OTHER_LANGUAGE_SUFFIXES else None
    counts: Counter[str] = Counter()
    for path in scan.root.rglob("*"):
        if path.suffix.lower() in OTHER_LANGUAGE_SUFFIXES:
            counts[path.suffix.lower()] += 1
    if not counts or scan.py_files:
        return None
    suffix, count = counts.most_common(1)[0]
    return suffix if count >= 2 else None


def analyze_project(root: Path) -> ProjectAnalysis:
    source = Path(root)
    if source.is_dir():
        scan = scan_directory(source)
    else:
        scan = scan_single_file(source)
    root = scan.root
    issues: list[Issue] = []

    if scan.truncated:
        if scan.single_file is not None:
            issues.append(Issue("single_file_too_many", Severity.WARNING))
        else:
            issues.append(
                Issue("scan_truncated", Severity.WARNING, {"files": str(scan.file_count)})
            )

    sources: dict[Path, str] = {p: _read(p) for p in scan.py_files}
    converted: dict[str, str] = {}
    conversion_failures: list[dict[str, str]] = []

    # Kolizje: cel konwersji nie moze nadpisac istniejacego pliku .py ani
    # innej konwersji. Klucz jest znormalizowany do malych liter, bo Windows
    # nie rozroznia wielkosci liter w nazwach (A06).
    taken: dict[str, Path] = {p: p for p in (_rel_key(root, s) for s in scan.py_files)}

    for txt in scan.text_candidates:
        result = convert_text_to_python(txt.read_bytes())
        if result.ok and result.code is not None:
            virtual = txt.with_suffix(".py")
            rel = virtual.relative_to(root).as_posix()
            key = _rel_key(root, virtual)
            if key in taken:
                # Nie nadpisujemy cudzego kodu po cichu. Blokada, dopoki
                # uzytkownik nie rozstrzygnie, ktory plik jest wejsciem.
                issues.append(
                    Issue("txt_collision", Severity.BLOCKER, {"file": txt.name, "target": rel})
                )
                continue
            taken[key] = virtual
            # Klucz konwersji to SCIEZKA WZGLEDNA, nie sama nazwa: `pkg/help.txt`
            # ma trafic do `pkg/help.py`, a `a/help.txt` i `b/help.txt` musza
            # zostac dwoma osobnymi modulami (A06).
            converted[rel] = result.code
            sources[virtual] = result.code
            if "fence_label" in result.steps:
                # Cicha zmiana cudzego pliku jest gorsza niz brak zmiany.
                # Pozostale kroki konwersji (ogrodzenia, numery linii, prompty)
                # zdejmuja rzeczy, ktore NIE SA Pythonem i nikt ich nie broni.
                # Ten zdejmuje linie, ktora jest skladniowo poprawnym kodem —
                # wiec jesli kiedys trafi w cos, co uzytkownik naprawde napisal,
                # ta notatka jest jedynym sladem, po ktorym da sie to odkryc.
                issues.append(Issue("fence_label_removed", Severity.INFO, {"file": txt.name}))
        else:
            conversion_failures.append(
                {
                    "file": txt.name,
                    "line": str(result.error_line or 0),
                    "detail": result.error_text or "",
                }
            )

    # A failed conversion only strands the user when it leaves the project
    # with nothing usable at all; otherwise the build can proceed on the
    # other sources and the user just needs to be told one file was skipped.
    txt_severity = Severity.WARNING if sources else Severity.BLOCKER
    for data in conversion_failures:
        # Pusty wynik (sama otoczka czatu, pusty blok) dostaje osobny, ludzki
        # komunikat zamiast "blad w linii 0" (A05).
        if data["detail"] == NO_CODE:
            issues.append(Issue("txt_no_code", txt_severity, {"file": data["file"]}))
        else:
            issues.append(Issue("txt_syntax_error", txt_severity, data))

    if not sources:
        other = _detect_other_language(scan)
        if other:
            issues.append(Issue("other_language", Severity.BLOCKER, {"suffix": other}))
        elif not conversion_failures:
            # "Nie widze tu Pythona" tylko wtedy, gdy naprawde go nie widzimy.
            # Gdy plik ZOSTAL rozpoznany jako kod i przewrocil sie dopiero na
            # skladni, `txt_syntax_error` juz powiedzial, co i w ktorej linii
            # poprawic. Doklejenie drugiego BLOCKERa zaprzecza pierwszemu, a
            # przy pojedynczym upuszczonym pliku nazywa przy okazji katalog
            # NADRZEDNY ("nie widze programu w folderze Pobrane"), ktorego
            # uzytkownik nigdy nie wskazywal.
            issues.append(Issue("no_python_found", Severity.BLOCKER, {"dir": root.name}))
        return ProjectAnalysis(
            root=root,
            scan=scan,
            suggested_name=scan.single_file.stem if scan.single_file else root.name,
            issues=tuple(issues),
        )

    candidates = rank_entry_candidates(root, sources)
    certain = entry_is_certain(candidates)
    if not certain:
        issues.append(
            Issue(
                "multiple_entry_points",
                Severity.WARNING,
                {
                    "first": candidates[0].path.name,
                    "second": candidates[1].path.name,
                },
            )
        )

    app_kind, kind_certain = detect_app_kind(sources)
    output_mode = detect_output_mode(sources)
    issues.extend(collect_code_issues(sources))

    # Ścieżka, a nie sam tekst: resolver rozwija `-r`/`-c` względem katalogu
    # manifestu (A07).
    dependencies = resolve_dependencies(
        sources, local_module_names(root, sources), requirements_path=scan.requirements
    )
    hidden_imports = collect_hidden_imports(sources)

    heavy_packages = [dep.package for dep in dependencies if dep.heavy]
    low, high, heaviest = estimate_exe_size(heavy_packages)
    if heaviest:
        # Widełki, a nie jedna liczba: PyInstaller wyrzuca z paczki to, czego
        # kod nie dotyka, więc stałe „kilkaset megabajtów" mijało się z
        # prawdą o 26-megabajtowym EXE (zgłoszenie 7). Powyżej progu to nadal
        # ostrzeżenie — poniżej jest zwykłą informacją, nie alarmem.
        size_data = {"low": str(low), "high": str(high), "packages": ", ".join(heaviest[:3])}
        if high >= LARGE_WARNING_MB:
            issues.append(Issue("size_estimate_large", Severity.WARNING, size_data))
        else:
            issues.append(Issue("size_estimate", Severity.INFO, size_data))

    return ProjectAnalysis(
        root=root,
        scan=scan,
        entry_candidates=candidates,
        entry_certain=certain,
        app_kind=app_kind,
        app_kind_certain=kind_certain,
        output_mode=output_mode,
        dependencies=dependencies,
        hidden_imports=hidden_imports,
        converted=converted,
        suggested_name=scan.single_file.stem if scan.single_file else root.name,
        suggested_icon=scan.icon_files[0] if scan.icon_files else None,
        issues=tuple(issues),
        single_file=scan.single_file,
        extra_sources=(
            tuple(p for p in scan.py_files if p != scan.single_file) if scan.single_file else ()
        ),
    )
