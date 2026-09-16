"""Validation of prepared sources with the TARGET interpreter before PyInstaller.

The analysis checks syntax with `ast.parse` using the DEVELOPER's interpreter —
and that is wrong in two ways: the parser (not the compiler) lets through some
language rules (`return` outside a function, misplaced `from __future__`), and
the developer version (3.13) is not the version the EXE is built for (3.12).
Code valid on the developer's machine but incompatible with the target Python
thus passed through the entire pipeline: PyInstaller compiled it only when
assembling the PYZ, caught `SyntaxError`, DROPPED the module and finished with
exit code 0 — and the user got an EXE greeting them with
"No module named <their program>".

Here we compile sources with the target interpreter from the build venv, before
PyInstaller. Compilation, not execution — we do not run the user's code.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from exelent.models import Issue, Severity
from exelent.runtime.procs import CREATE_NO_WINDOW, kill_tree

# Protocol marker printed by the checker on a syntax error. An explicit prefix
# replaces the old "first line with a tab" heuristic (B09): any tab in the
# output could be mistaken for an error, and absence of a tab for success. Now
# we recognize an error ONLY by this line, and its absence with a non-zero exit
# code means "validation did not execute", not "no error".
_ERROR_MARKER = "EXELENT_SYNTAX_ERROR"

# B10: validation must not hang indefinitely. A large project compiles in under
# a second; 30 s is a generous margin after which we conclude the interpreter is
# stuck (e.g. waiting on stdin after a configuration error).
_VALIDATE_TIMEOUT_SECONDS = 30

# How long we wait for pipes to close after kill_tree.
_KILL_WAIT_SECONDS = 3.0

# The checker code is EMBEDDED here and passed to the target interpreter via
# `-c`, not read from a file `_targetcheck.py` next to the module. In a frozen
# EXElent.exe such a file next to the module does NOT EXIST (PyInstaller only
# collects what is imported — not paths read from disk), so validation silently
# did not execute and `None` was read as success (B09). As a constant in an
# imported module the source is always in the bundle.
#
# The checker COMPILES each source (does not run it), reading bytes so that
# `compile` honors the encoding declaration (PEP 263) exactly as an import in
# the finished EXE would. The first file that fails to compile prints
# `<marker>\t<relative path>\t<line>\t<message>` and exits with code 1; when
# everything compiles — code 0. Must be self-contained (stdlib only).
_CHECK_SOURCE = f"""\
import os
import sys

MARKER = {_ERROR_MARKER!r}


def main():
    root = sys.argv[1]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith((".py", ".pyw")):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "rb") as handle:
                data = handle.read()
            try:
                compile(data, path, "exec")
            except SyntaxError as exc:
                rel = os.path.relpath(path, root)
                detail = (exc.msg or "").replace("\\t", " ").replace("\\n", " ")
                sys.stdout.write(f"{{MARKER}}\\t{{rel}}\\t{{exc.lineno or 0}}\\t{{detail}}\\n")
                return 1
    return 0


sys.exit(main())
"""


def _validation_failed(python_version: str, detail: str) -> Issue:
    """Validation DID NOT EXECUTE (the interpreter did not start, the checker
    crashed or broke the protocol). This is a control failure, not confirmation
    of correctness — hence BLOCKER, not a silent `None` read as success (B09).
    The `dropped_project_modules` guard remains as ADDITIONAL protection, not
    a substitute."""
    return Issue(
        "validation_failed",
        Severity.BLOCKER,
        {"version": python_version, "detail": detail[:200]},
    )


def validate_target_syntax(
    python: Path,
    workspace: Path,
    *,
    python_version: str,
    cancel=None,
) -> Issue | None:
    """Four disjoint outcomes (B09): `None` — syntax correct;
    `target_syntax_error` (BLOCKER) — first source that does not compile with
    the target `python`; `validation_failed` (BLOCKER) — the check did not
    execute or broke the protocol; `None` also after cancellation (the build
    then ends as interrupted at a later stage).

    A check that did not execute is NO LONGER treated as absence of error: a
    false success from our own infrastructure produced an EXE without the user's
    code, ending with "No module named ...".
    """
    if cancel is not None and cancel.cancelled:
        return None

    try:
        process = subprocess.Popen(
            [str(python), "-c", _CHECK_SOURCE, str(workspace)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        # The target interpreter did not start at all — the check did not happen.
        return _validation_failed(python_version, str(exc))

    # B10: loop checking cancel token and timeout simultaneously.
    # Validation is compilation (not execution) of sources — a fast operation.
    # Timeout guards against a stuck interpreter; cancel reacts to window close
    # or the "Cancel" button.
    deadline = time.monotonic() + _VALIDATE_TIMEOUT_SECONDS
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.cancelled:
                kill_tree(process.pid)
                try:
                    process.communicate(timeout=_KILL_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                return None  # cancelled — the build ends as interrupted later
            if time.monotonic() > deadline:
                kill_tree(process.pid)
                try:
                    process.communicate(timeout=_KILL_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                return _validation_failed(python_version, "timeout after 30s")

    if process.returncode == 0:
        return None

    prefix = _ERROR_MARKER + "\t"
    line = next((ln for ln in stdout.splitlines() if ln.startswith(prefix)), None)
    if line is None:
        # Non-zero exit code without the protocol marker: the checker did not
        # reach the check or crashed. This is a validation failure, not "no error".
        detail = (stderr or stdout or "").strip().replace("\n", " ")
        return _validation_failed(python_version, detail)

    _marker, file, lineno, detail = (line.split("\t", 3) + ["", "", "", ""])[:4]
    return Issue(
        "target_syntax_error",
        Severity.BLOCKER,
        {"file": file, "line": lineno, "detail": detail, "version": python_version},
    )
