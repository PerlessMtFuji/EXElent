"""Walking the user's directory and classifying what is in it."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from exelent.analysis.textconv import convert_text_to_python, decode_bytes
from exelent.constants import (
    EXCLUDED_DIRS,
    MAX_SCAN_BYTES,
    MAX_SCAN_FILES,
    MAX_SINGLE_FILE_IMPORTS,
)
from exelent.models import ScanResult

DATA_SUFFIXES = frozenset(
    {
        ".json",
        ".csv",
        ".txt",
        ".ini",
        ".cfg",
        ".yaml",
        ".yml",
        ".xml",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".wav",
        ".mp3",
        ".ogg",
        ".ttf",
        ".otf",
        ".md",
        ".toml",
        ".html",
        ".htm",
    }
)
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".ico", ".bmp", ".gif"})
ICON_STEMS = frozenset({"icon", "ikona", "logo", "app", "favicon"})

_CODE_HINT = re.compile(r"^\s*(def |class |import |from \S+ import |print\()", re.MULTILINE)


def looks_like_python(text: str) -> bool:
    """Whether the text looks like Python code, even if it does not parse yet.

    A candidate is text that either (a) parses as real Python after
    conversion (stripping markdown fences, normalizing quotes etc. — see
    ``textconv``), or (b) has at least one structural code signal at the
    start of a line. (a) catches short, clean programs pasted from a chat
    window that cannot be distinguished by signals alone — and this is
    the product's flagship path. (b) still catches broken code that the
    user should be warned about, instead of silently classifying it as data.
    """
    if not text.strip():
        return False
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        pass
    except ValueError:
        # ``ast.parse`` raises ValueError (not SyntaxError) on NUL bytes —
        # e.g. a binary file renamed to .txt. This is not Python; classify
        # as data instead of crashing the scan with an exception.
        return False
    if convert_text_to_python(text.encode("utf-8", errors="replace")).ok:
        return True
    return len(_CODE_HINT.findall(text)) >= 1


def _read_head(path: Path, limit: int = 64_000) -> tuple[str, bool]:
    """Read at most ``limit`` bytes — enough to identify the file type.

    We read only the needed prefix, not the entire file. Returns
    ``(text, truncated)``.

    We decode via ``decode_bytes`` — the SAME function as the converter — so
    a TXT in UTF-16/BOM is seen as a program, not as garbage from hard utf-8
    (B02: scanner and converter decode the same way). The prefix may cut a
    2-byte UTF-16 unit; in that case ``decode_bytes`` raises
    ``UnicodeDecodeError`` on the BOM branch and for CLASSIFICATION alone
    we fall back to tolerant utf-8.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read(limit)
            truncated = len(raw) == limit and handle.read(1) != b""
    except OSError:
        return "", False
    try:
        return decode_bytes(raw)[0], truncated
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), truncated


def _module_imports(code: str) -> list[tuple[int, str | None, tuple[str, ...]]]:
    """``(level, module, names)`` for every import. A file with a syntax error
    yields an empty list: we do not know what it imports, but that is no
    reason to skip it.

    Level > 0 is a relative import (``from ..pkg import x``); module may be
    ``None`` (``from . import helper``); names from ``from X import a, b``
    can be submodules.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out: list[tuple[int, str | None, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((0, alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append((node.level, node.module, tuple(a.name for a in node.names)))
    return out


def _resolve_module(base: Path, parts: list[str]) -> list[Path]:
    """Files of module ``a.b.c`` relative to ``base``: ``__init__.py`` of every
    package along the way plus the module itself (``a/b/c.py`` or
    ``a/b/c/__init__.py``). Empty list when the module does not exist locally
    or an intermediate package is not a package.

    B03/B04: namespace packages (PEP 420) — folders WITHOUT ``__init__.py`` —
    are supported as a fallback: if the folder exists but has no
    ``__init__.py``, the module is still resolved (the leaf file must exist).
    Intermediate packages' ``__init__.py`` is added to the result only when
    it exists.
    """
    if not parts:
        return []
    files: list[Path] = []
    cur = base
    for part in parts[:-1]:
        cur = cur / part
        if not cur.is_dir():
            return []
        init = cur / "__init__.py"
        if init.is_file():
            files.append(init)
        # Namespace package — folder exists but without __init__.py.
        # Continue resolving because the leaf file may exist.
    leaf = cur / f"{parts[-1]}.py"
    package = cur / parts[-1] / "__init__.py"
    if leaf.is_file():
        files.append(leaf)
    elif package.is_file():
        files.append(package)
    else:
        return []
    return files


def _relative_base(current: Path, root: Path, level: int) -> Path | None:
    """Base directory of a relative import. ``None`` when ``..`` goes above the
    project root — that is beyond the scope of a single file (we do not pull
    in Downloads).
    """
    base = current.parent
    for _ in range(level - 1):
        base = base.parent
    if base == root or root in base.parents:
        return base
    return None


def _import_targets(
    current: Path,
    root: Path,
    level: int,
    module: str | None,
    names: tuple[str, ...],
    extra_roots: tuple[Path, ...] = (),
) -> list[Path]:
    if level == 0:
        # Search every import root. For the ``src/`` layout the file
        # ``src/demo/helper.py`` is reachable via ``import demo.helper``
        # from both ``root/src/`` (import root) and normally from ``root/``
        # (only if ``root/demo/`` exists). Check from the most specific
        # first (B04).
        bases = [root, *extra_roots]
    else:
        found = _relative_base(current, root, level)
        if found is None:
            return []
        bases = [found]
    parts = module.split(".") if module else []
    targets: list[Path] = []
    for base in bases:
        resolved = _resolve_module(base, parts) if parts else []
        for name in names:
            resolved += _resolve_module(base, [*parts, name])
        if resolved:
            targets.extend(resolved)
            break  # First matching root wins.
    return targets


def local_import_closure(
    entry: Path,
    root: Path,
    limit: int = MAX_SINGLE_FILE_IMPORTS,
    *,
    extra_roots: tuple[Path, ...] = (),
    initial_code: str | None = None,
) -> tuple[tuple[Path, ...], bool, tuple[Path, ...]]:
    """Local modules that ``entry`` needs, together with their own.

    Returns ``(files_without_entry, exceeded_limit, truncated_files)``.
    When the limit is exceeded the result is an EMPTY tuple, not a truncated
    list: pulling in a random half of the import chain would produce an EXE
    that crashes on a missing module for the recipient — a failure worse and
    later than an honest "cannot handle it, keeping the single file".

    ``truncated_files`` are files whose prefix (1 MB) did not cover the full
    content — their imports may be incomplete (B11).

    ``extra_roots``: additional import roots (e.g. ``root/src/`` for the
    ``src/`` layout). ``initial_code``: code of the main file when reading
    from disk does not give the correct content — e.g. after TXT conversion
    (B04).
    """
    seen: set[Path] = {entry}
    queue = [entry]
    found: list[Path] = []
    truncated_files: list[Path] = []
    first = True

    while queue:
        current = queue.pop(0)
        if first and initial_code is not None:
            code = initial_code
            first = False
        else:
            code, was_truncated = _read_head(current, limit=1_000_000)
            if was_truncated:
                truncated_files.append(current)
            first = False
        for level, module, names in _module_imports(code):
            for target in _import_targets(current, root, level, module, names, extra_roots):
                if target in seen:
                    continue
                if len(found) >= limit:
                    return (), True, ()
                seen.add(target)
                found.append(target)
                queue.append(target)

    return tuple(found), False, tuple(truncated_files)


def scan_directory(
    root: Path,
    *,
    max_files: int = MAX_SCAN_FILES,
    max_bytes: int = MAX_SCAN_BYTES,
) -> ScanResult:
    py: list[Path] = []
    texts: list[Path] = []
    data: list[Path] = []
    icons: list[Path] = []
    requirements: Path | None = None
    pyproject: Path | None = None
    count = 0
    total = 0
    truncated = False

    for dirpath, dirnames, filenames in root.walk():
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            path = dirpath / name
            count += 1
            try:
                total += path.stat().st_size
            except OSError:
                pass
            if count > max_files or total > max_bytes:
                truncated = True
                break

            suffix = path.suffix.lower()
            if suffix in {".py", ".pyw"}:
                py.append(path)
            elif name.lower() == "requirements.txt" and requirements is None:
                # First match wins; walk() goes from root, so the project's
                # manifest beats one from a subdirectory (B05).
                requirements = path
            elif name.lower() == "pyproject.toml" and pyproject is None:
                # First match wins; walk() goes from root, so the project's
                # pyproject beats one from a subdirectory.
                pyproject = path
            elif suffix == ".txt":
                if looks_like_python(_read_head(path)[0]):
                    texts.append(path)
                else:
                    data.append(path)
            elif suffix in IMAGE_SUFFIXES:
                if path.stem.lower() in ICON_STEMS or suffix == ".ico":
                    icons.append(path)
                # An app icon can ALSO be a runtime resource (B07):
                # ``logo.png`` used as the EXE icon must still be accessible
                # via ``Image.open('logo.png')`` in the running program.
                # Not ``else`` — ALWAYS to data, regardless of icon role.
                data.append(path)
            elif suffix in DATA_SUFFIXES:
                data.append(path)
        if truncated:
            break

    return ScanResult(
        root=root,
        py_files=tuple(py),
        text_candidates=tuple(texts),
        data_files=tuple(data),
        icon_files=tuple(icons),
        requirements=requirements,
        pyproject=pyproject,
        file_count=count,
        total_bytes=total,
        truncated=truncated,
    )


def scan_single_file(path: Path) -> ScanResult:
    """Scan for a single file pointed to by the user.

    ``root`` is the parent directory because relative paths in the user's
    code and ``work_dir_for`` need a reference point — but the directory is
    NOT the project. The ``requirements.txt``, icon or data files sitting in
    it belong to something else (usually the Downloads folder) and pulling
    them in would be the very mistake this function guards against.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    py: tuple[Path, ...] = ()
    texts: tuple[Path, ...] = ()

    if suffix in {".py", ".pyw"}:
        py = (path,)
    elif suffix == ".txt" and looks_like_python(_read_head(path)[0]):
        texts = (path,)

    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    # For TXT we convert BEFORE computing the import closure (B04): raw
    # text with markdown fences does not parse as Python, so
    # ``_module_imports`` returns an empty list and ``import helper`` in
    # the TXT does not find the neighbouring ``helper.py``. Conversion is
    # idempotent and cheap.
    initial_code: str | None = None
    if texts:
        try:
            raw = path.read_bytes()
            result = convert_text_to_python(raw)
            if result.ok and result.code is not None:
                initial_code = result.code
        except OSError:
            pass

    extra, truncated, _trunc_files = local_import_closure(
        path,
        path.parent,
        initial_code=initial_code,
    )
    if py:
        py = (path, *extra)
    elif texts:
        # The main file is a conversion candidate, but its neighbours are
        # plain Python — do not run them through conversion.
        py = extra

    return ScanResult(
        root=path.parent,
        py_files=py,
        text_candidates=texts,
        file_count=1,
        total_bytes=size,
        single_file=path,
        truncated=truncated,
    )
