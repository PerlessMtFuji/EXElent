"""Analysis orchestration: directory in, ProjectAnalysis out.

Nothing here writes to disk. TXT conversion lives in memory until the task
that creates a working copy — the user's directory remains untouched.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from exelent.analysis.apptype import (
    collect_code_issues,
    collect_hidden_imports,
    detect_app_kind,
)
from exelent.analysis.entrypoint import (
    entry_is_certain,
    local_module_names,
    rank_entry_candidates,
)
from exelent.analysis.parsed import ParsedSources
from exelent.analysis.scanner import scan_directory, scan_single_file
from exelent.analysis.textconv import NO_CODE, convert_text_to_python
from exelent.constants import EXCLUDED_DIRS, MAX_SCAN_FILES
from exelent.deps.resolve import resolve_dependencies
from exelent.deps.sizes import LARGE_WARNING_MB, estimate_exe_size
from exelent.models import Issue, OutputMode, ProjectAnalysis, ScanResult, Severity

OTHER_LANGUAGE_SUFFIXES = {".js", ".ts", ".java", ".cs", ".cpp", ".c", ".go", ".rb", ".php"}


def _read(path: Path) -> str | None:
    """Read a source file. Returns ``None`` on I/O error (B11).

    Permission denied, disappearing files and broken encoding are NOT
    reasons to abort the entire analysis: the user should see diagnostics
    naming the file, and the remaining files should still be visible.
    """
    try:
        # utf-8-sig: automatically strips BOM (U+FEFF) from the beginning.
        # A BOM file is legal UTF-8 (PEP 263, ``utf-8-sig`` encoding),
        # but ``ast.parse`` rejects U+FEFF as "invalid non-printable character".
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _module_name_collisions(py_files: tuple[Path, ...], root: Path) -> list[tuple[str, list[Path]]]:
    """Modules with the same bare name in different folders.

    A file inside a package (``__init__.py`` beside it) has a qualified name —
    ``pkg_a.util`` vs ``pkg_b.util`` do not clash. But two ``util.py`` files
    in folders WITHOUT ``__init__.py`` both import as ``util``; the winner is
    decided by ``sys.path`` order, which can be arbitrary when packaging.
    This is a warning, not a blocker: the build can proceed, but the user
    must know that one module will shadow the other.

    B03/B04: case-insensitive — on Windows ``Helper.py`` and ``helper.py``
    are the same file, but ``import Helper`` and ``import helper`` on Linux
    are different modules. We build on Windows, so we match case-insensitively.
    Namespace packages (folders without ``__init__.py``) are treated as loose
    modules — their files can collide with others at the same level.
    """
    by_name: dict[str, list[Path]] = {}
    for path in py_files:
        if path.name == "__init__.py":
            continue
        # B03: namespace packages — a folder without __init__.py can still
        # be a package. A file in such a folder is a loose module (collides
        # like any other), unless the folder is an explicit package.
        if (path.parent / "__init__.py").exists():
            continue
        by_name.setdefault(path.stem.lower(), []).append(path)
    collisions: list[tuple[str, list[Path]]] = []
    for name, files in by_name.items():
        if len({f.parent for f in files}) > 1:
            collisions.append((name, sorted(files)))
    return collisions


def _rel_key(root: Path, path: Path) -> str:
    """Normalized path key relative to root — for collision detection.

    Lowercase because Windows is case-insensitive: ``Main.py`` and ``main.py``
    are the same file on disk.
    """
    return path.relative_to(root).as_posix().lower()


def _detect_other_language(scan: ScanResult) -> str | None:
    """Language suffix if it fills the project instead of Python.

    In single-file mode ``scan.root`` is the PARENT directory of the dropped
    file — usually someone else's folder (Downloads). Walking it (``rglob``)
    is exactly the harm that task 7 was meant to eliminate: a single dropped
    file must not trigger a scan of the entire neighbourhood. The single-file
    signal therefore comes solely from the dropped file's suffix, without
    any directory walking.

    B11: we use ``scan.root.walk()`` with the SAME exclusions and limit as the
    scanner, instead of an unrestricted ``rglob``. Without this a project
    inside a folder with ``node_modules`` could walk millions of files.
    """
    if scan.single_file is not None:
        suffix = scan.single_file.suffix.lower()
        return suffix if suffix in OTHER_LANGUAGE_SUFFIXES else None
    counts: Counter[str] = Counter()
    seen = 0
    for dirpath, dirnames, filenames in scan.root.walk():
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        for name in filenames:
            suffix = Path(name).suffix.lower()
            if suffix in OTHER_LANGUAGE_SUFFIXES:
                counts[suffix] += 1
            seen += 1
            if seen >= MAX_SCAN_FILES:
                break
        if seen >= MAX_SCAN_FILES:
            break
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

    # B11: inaccessible files (ACL denial, disappearing file) do not abort analysis.
    # The user gets diagnostics naming the file; remaining files keep working.
    sources: dict[Path, str] = {}
    for p in scan.py_files:
        text = _read(p)
        if text is None:
            issues.append(
                Issue(
                    "file_read_error",
                    Severity.WARNING,
                    {"file": p.relative_to(root).as_posix()},
                )
            )
            continue
        sources[p] = text
    converted: dict[str, str] = {}
    conversion_failures: list[dict[str, str]] = []

    # Collisions: conversion target must not overwrite an existing .py file
    # or another conversion. Key is normalized to lowercase because Windows
    # is case-insensitive.
    taken: dict[str, Path] = {p: p for p in (_rel_key(root, s) for s in scan.py_files)}

    for txt in scan.text_candidates:
        try:
            raw_bytes = txt.read_bytes()
        except OSError:
            issues.append(
                Issue(
                    "file_read_error",
                    Severity.WARNING,
                    {"file": txt.relative_to(root).as_posix()},
                )
            )
            continue
        result = convert_text_to_python(raw_bytes)
        if result.ok and result.code is not None:
            virtual = txt.with_suffix(".py")
            rel = virtual.relative_to(root).as_posix()
            key = _rel_key(root, virtual)
            if key in taken:
                # Do not silently overwrite someone else's code. Block until
                # the user decides which file is the input.
                issues.append(
                    Issue("txt_collision", Severity.BLOCKER, {"file": txt.name, "target": rel})
                )
                continue
            taken[key] = virtual
            # Conversion key is a RELATIVE PATH, not just the name: ``pkg/help.txt``
            # should go to ``pkg/help.py``, and ``a/help.txt`` and ``b/help.txt``
            # must remain two separate modules.
            converted[rel] = result.code
            sources[virtual] = result.code
            if result.code_blocks:
                # Multiple code blocks in a single TXT (B02): inform the user
                # about boundaries and how they were joined, so they can judge
                # whether the blocks are a continuation or alternatives.
                ranges = ", ".join(f"{b.start_line}–{b.end_line}" for b in result.code_blocks)
                issues.append(
                    Issue(
                        "txt_multiple_blocks",
                        Severity.WARNING,
                        {
                            "file": txt.name,
                            "count": str(len(result.code_blocks)),
                            "ranges": ranges,
                        },
                    )
                )
            if "fence_label" in result.steps:
                # Silently changing someone else's file is worse than not
                # changing it. Other conversion steps (fences, line numbers,
                # prompts) strip things that are NOT Python and nobody
                # defends them. This one strips a line that is syntactically
                # valid code — so if it ever hits something the user actually
                # wrote, this note is the only trace to discover it.
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
        # Empty result (just chat wrapper, empty block) gets a separate,
        # human-friendly message instead of "error on line 0".
        if data["detail"] == NO_CODE:
            issues.append(Issue("txt_no_code", txt_severity, {"file": data["file"]}))
        else:
            issues.append(Issue("txt_syntax_error", txt_severity, data))

    # B11: wrap the complete dict in ParsedSources — one parse per file,
    # shared across all analysis stages.
    parsed = ParsedSources(sources)

    # Real .py files had no syntax check until now: analysis (``_trees``)
    # silently skipped unparseable trees, so an invalid program passed through
    # the entire pipeline and only crashed as a running EXE (the build
    # reported "success"). TXT conversions are already checked by
    # convert_text_to_python, so we only validate original .py files.
    for py in scan.py_files:
        if py not in parsed:
            continue  # B11: unreadable file — diagnostics already added
        tree = parsed.tree(py)
        if tree is None:
            # ast.parse returned None (SyntaxError) — re-parse to extract
            # the error message.
            try:
                ast.parse(parsed[py])
            except SyntaxError as exc:
                issues.append(
                    Issue(
                        "py_syntax_error",
                        Severity.BLOCKER,
                        {"file": py.name, "line": str(exc.lineno or 0), "detail": exc.msg or ""},
                    )
                )

    for name, files in _module_name_collisions(scan.py_files, root):
        issues.append(
            Issue(
                "module_name_collision",
                Severity.WARNING,
                {
                    "module": name,
                    "files": ", ".join(f.relative_to(root).as_posix() for f in files),
                },
            )
        )

    if not parsed:
        other = _detect_other_language(scan)
        if other:
            issues.append(Issue("other_language", Severity.BLOCKER, {"suffix": other}))
        elif not conversion_failures:
            # "No Python found" only when we truly see none. When a file WAS
            # recognized as code and only failed on syntax, ``txt_syntax_error``
            # already says what and on which line to fix. Appending a second
            # BLOCKER contradicts the first, and for a single dropped file it
            # also names the PARENT directory ("no program found in Downloads"),
            # which the user never pointed to.
            issues.append(Issue("no_python_found", Severity.BLOCKER, {"dir": root.name}))
        return ProjectAnalysis(
            root=root,
            scan=scan,
            suggested_name=scan.single_file.stem if scan.single_file else root.name,
            issues=tuple(issues),
        )

    candidates = rank_entry_candidates(root, parsed)
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

    app_kind, kind_certain = detect_app_kind(parsed)
    # Output mode is no longer guessed from content (B01): the recommended
    # mode is always ONEDIR because only it guarantees persistent writes AND
    # reading resources located next to the EXE. ONEFILE remains a manual
    # user choice on the review screen.
    output_mode = OutputMode.ONEDIR
    issues.extend(collect_code_issues(parsed))

    # Hidden imports must be known BEFORE the resolver: a dynamic
    # ``importlib.import_module('PIL.Image')`` feeds both PyInstaller's
    # ``--hidden-import`` and the package install list (B04).
    hidden_imports = collect_hidden_imports(parsed)

    # Path, not just text: the resolver expands ``-r``/``-c`` relative to
    # the manifest's directory. ``dep_issues`` carries manifest diagnostics
    # (cycle, missing file, unreadable pyproject).
    dep_issues: list[Issue] = []
    dependencies = resolve_dependencies(
        parsed,
        local_module_names(root, parsed),
        requirements_path=scan.requirements,
        pyproject_path=scan.pyproject,
        hidden_imports=hidden_imports,
        issues=dep_issues,
    )
    issues.extend(dep_issues)

    heavy_packages = [dep.package for dep in dependencies if dep.heavy]
    low, high, heaviest = estimate_exe_size(heavy_packages)
    if heaviest:
        # A range, not a single number: PyInstaller strips from the package
        # what the code does not touch, so a flat "several hundred megabytes"
        # was off by a factor of ten for a 26 MB EXE (issue 7). Above the
        # threshold it is still a warning — below it is just information,
        # not an alarm.
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
