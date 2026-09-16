"""Build log -> Issue codes. The presentation layer translates codes into messages.

Rule: the user never sees a raw traceback as the primary message.
Every unrecognized error becomes a candidate for a new pattern below.

The governing rule for patterns themselves: a diagnosis must be either
discriminating or neutral — never confident and wrong. This module replaces a
wall of traceback with a sentence and an action. A sentence with the WRONG
action is worse than no sentence: the user loses an hour disabling antivirus,
the build still fails, and every later message loses credibility. When log
evidence does not distinguish two causes unambiguously, the pattern must emit
a neutral code instead of guessing a more specific one.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from exelent.models import Issue, Severity

# Raw signal that the system denied access to a file. By itself it does not
# distinguish causes. Two layers report it differently, and both are reachable
# during a build:
#   - Win32 ("WinError 5" / "Access is denied") — CreateFile, DeleteFile,
#     MoveFile, including assembly and movement of the EXE,
#   - CRT ("Errno 13" / "Permission denied") — everything through open().
#     PyInstaller places the bootloader and every collected binary in
#     dist\myapp\_internal\ through shutil.copy2, which OPENS the destination,
#     so antivirus blocking during COLLECT has exactly this form and never
#     reports WinError 5.
# Missing the second form previously produced NO Issue: silence and a generic
# "build failed" with no next step, violating the module rule above. "\b" after
# the number excludes adjacent codes: "Errno 130" is a different error.
_ACCESS_DENIED = r"(?:WinError 5\b|Access is denied|Errno 13\b|Permission denied)"

# Windows explicitly naming antivirus intervention. Unlike raw access denial,
# these messages do NOT require conjunction with dist: their text already
# distinguishes the cause, so adding another condition removes no ambiguity
# and only creates false negatives.
_ANTIVIRUS_EXPLICIT = (
    r"WinError 225\b|WinError 1920\b|contains a virus or potentially unwanted software"
)

# End of a path segment: separator, quote, whitespace, or end of input.
#
# A STRUCTURAL guard rather than a suffix blacklist. Earlier versions listed
# known exceptions one by one — (?!-info) — and admitted another suffix three
# times in a row (".dist-info", then "dist-packages", then "distutils"). The
# condition "the segment name ends exactly here" excludes all three and every
# future suffix because it does not depend on which suffix was added — any
# further character belonging to the same directory name is enough. A separator
# omitted from the class (such as ")") yields a false NEGATIVE and degrades to
# neutral access_denied, which is the safe direction.
_SEGMENT_END = r"(?=[\\/'\"\s]|$)"

# Fragment indicating the build output directory.
#
# "dist" must be a real path segment ("...\dist\app.exe", "C:/proj/dist"), not
# an accidental word: either it has a leading separator and a segment boundary
# after it, or it starts at a token boundary (nothing before belongs to the
# name) and has a trailing separator. A single [\\/] also handles doubled
# (repr "\\") and quadrupled (JSON "\\\\") forms by matching the last repeated
# separator, so the {1,2} quantifier had no effect and was removed.
#
# Deliberate boundary (round 3, DO NOT extend): a real antivirus hit may occur
# in workpath ("...\build\myapp.exe") because newer PyInstaller versions
# assemble the EXE there and move it to dist afterward. Even so, "build" does
# NOT belong here. The cost asymmetry is settled: a false positive sends the
# user into an hour of disabling antivirus for an unrelated cause (this exact
# regression has returned twice), while a false negative yields access_denied,
# which honestly says Windows denied file access. "build" is also common in
# logs ("Building EXE from EXE-00.toc"), so it costs more than "dist".
_DIST_SEGMENT = rf"(?:[\\/]dist{_SEGMENT_END}|(?<![\w.-])dist[\\/])"

PATTERNS: tuple[tuple[re.Pattern[str], str, Severity], ...] = (
    (
        re.compile(r"No solution found when resolving|Could not find a version"),
        "package_not_found",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"No module named ['\"]([\w.]+)['\"]"),
        "module_not_found",
        Severity.BLOCKER,
    ),
    # Unconditional branch: Windows named the antivirus itself. This uses the
    # same code as the branch below, so explain_log() (dedupe by "code") returns
    # exactly one Issue even when the log matches both paths, and neutral
    # access_denied is suppressed by _SUPPRESSED_BY in the same way.
    (
        re.compile(_ANTIVIRUS_EXPLICIT),
        "antivirus_blocked",
        Severity.BLOCKER,
    ),
    # Deliberate conjunction: "WinError 5" / "Access is denied" alone is one
    # of the most generic Windows errors and has many non-antivirus causes (a
    # file open elsewhere, OneDrive lock, directory requiring elevation).
    # Report antivirus_blocked only when the log ALSO proves the affected item
    # is a build artifact (dist).
    #
    # Both pieces of evidence must come from THE SAME event, meaning the same
    # log line. An earlier version used unanchored lookaheads with re.DOTALL,
    # so each independently searched the whole log: any unrelated "WinError 5"
    # plus "dist" elsewhere produced a confident and WRONG diagnosis. Here
    # "^" with re.MULTILINE anchors both lookaheads at the same line start, and
    # "[^\n]*" does not cross the line end, so document-wide co-occurrence is
    # insufficient.
    (
        re.compile(
            rf"^(?=[^\n]*{_ACCESS_DENIED})(?=[^\n]*{_DIST_SEGMENT})",
            re.MULTILINE,
        ),
        "antivirus_blocked",
        Severity.BLOCKER,
    ),
    # WinError 32 ("the file is used by another process") is distinguished from
    # antivirus — the most common cause is a previous EXE still running during
    # rebuild, and the correct action is "close the program and try again",
    # entirely different from antivirus advice.
    (
        re.compile(r"WinError 32\b|used by another process"),
        "file_in_use",
        Severity.BLOCKER,
    ),
    # Neutral fallback: "WinError 5" / "Access is denied" without evidence for
    # dist or WinError 32. Do not guess the cause; say only that Windows denied
    # file access. Suppressed in explain_log() when the same log already yielded
    # a more specific code (antivirus_blocked / file_in_use), avoiding two
    # messages for the same event.
    (
        re.compile(_ACCESS_DENIED),
        "access_denied",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"WinError 206\b|filename or extension is too long"),
        "path_too_long",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"certificate verify failed|SSLCertVerificationError|\bSSLError\b"),
        "ssl_proxy",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"Errno 28\b|No space left on device"),
        "disk_full",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"maximum recursion depth exceeded"),
        "recursion_limit",
        Severity.WARNING,
    ),
    (
        re.compile(r"Failed to execute script"),
        "script_failed",
        Severity.WARNING,
    ),
    (
        re.compile(r"UnicodeDecodeError|UnicodeEncodeError"),
        "encoding_problem",
        Severity.WARNING,
    ),
)


# --- System exceptions, not the build log ------------------------------------
#
# The table above describes the PyInstaller LOG. Here we diagnose `OSError`
# raised by our own code while reading user source files, copying the project
# into the workspace, or checking free disk space.
#
# Why a SEPARATE table when the messages are identical: the base probability is
# different, and diagnosis is a bet on cause. "WinError 1920" on an artifact in
# `dist` most often means antivirus (Task 14 settled this over three rounds).
# The same code while READING a source file usually means a cloud-only file —
# OneDrive Files On-Demand is enabled by default in Polish OOBE and specification
# section 8 names this case explicitly. Advice to "disable antivirus" is then
# confident and WRONG: the user loses an hour, the build still fails, and later
# messages lose credibility.
#
# Therefore `antivirus_blocked` has NO branch here. Evidence for that diagnosis
# is a build artifact in the log, which an exception from reading user files
# does not carry.

# Windows explicitly naming the cloud. Match CONTENT rather than a number: the
# ERROR_CLOUD_FILE_* family contains over a dozen codes that should not be
# copied from memory. A false negative degrades safely to neutral
# `access_denied`; an invented number would produce confident nonsense.
_CLOUD_EXPLICIT = re.compile(r"cloud file|cloud operation|cloud provider|cloud sync", re.IGNORECASE)

# "The file cannot be accessed by the system" does NOT distinguish causes by
# itself, so it counts as cloud-related only with a second piece of evidence:
# the path lies in a synchronized directory (`in_cloud`).
_CANNOT_ACCESS = re.compile(r"WinError 1920\b|cannot be accessed by the system", re.IGNORECASE)

_FILE_IN_USE = re.compile(r"WinError 32\b|used by another process", re.IGNORECASE)
_DISK_FULL = re.compile(r"Errno 28\b|No space left on device", re.IGNORECASE)
_PATH_TOO_LONG = re.compile(r"WinError 206\b|filename or extension is too long", re.IGNORECASE)


def filename_of(exc: OSError) -> str:
    """Filename from the exception — whatever the system put there.

    `OSError.filename` may be bytes (`open(b"...")`) or even a descriptor.
    Diagnostics are the last safety net; a net that raises `TypeError` itself
    ceases to be one and exposes a traceback to the user.
    """
    raw = getattr(exc, "filename", None)
    if raw is None:
        return ""
    with suppress(TypeError, ValueError):
        return os.fsdecode(raw)
    return ""


def os_error_text(exc: OSError) -> str:
    """Exception text with numeric codes and the message placed together.

    THE PATH IS OMITTED, and that is the point: the patterns below ask what the
    system reported, while a filename is USER text. A directory named "Cloud
    Files" must not count as cloud evidence — it once did, masking correct
    diagnoses (`disk_full`, `file_in_use`) because the cloud branch comes first.

    The log table (`explain_log`) correctly treats paths differently: there a
    `dist` segment on the same line IS antivirus evidence (Task 14 ruling).
    The difference is who wrote the text — PyInstaller writes the log.
    """
    parts = [f"[Errno {exc.errno}]" if exc.errno is not None else ""]
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        parts.append(f"[WinError {winerror}]")
    parts.append(str(exc.strerror or exc))
    return " ".join(part for part in parts if part)


def map_os_error(exc: OSError, *, in_cloud: bool = False) -> tuple[Issue, ...]:
    """System errors -> Issue. An empty tuple means "unknown", and that is OK.

    `run_build` converts no match into `unexpected_error`, which honestly says
    "something went wrong". An invented diagnosis would be worse.
    """
    text = os_error_text(exc)
    name = Path(filename_of(exc)).name

    if _CLOUD_EXPLICIT.search(text) or (in_cloud and _CANNOT_ACCESS.search(text)):
        return (Issue("cloud_file_unavailable", Severity.BLOCKER, {"file": name}),)
    if _FILE_IN_USE.search(text):
        return (Issue("file_in_use", Severity.BLOCKER),)
    if _DISK_FULL.search(text):
        return (Issue("disk_full", Severity.BLOCKER),)
    if _PATH_TOO_LONG.search(text):
        return (Issue("path_too_long", Severity.BLOCKER),)
    if re.search(_ACCESS_DENIED, text) or _CANNOT_ACCESS.search(text):
        return (Issue("access_denied", Severity.BLOCKER),)
    return ()


SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.WARNING: 1, Severity.INFO: 2}


def sort_issues(issues: Iterable[Issue]) -> tuple[Issue, ...]:
    """BLOCKERs first, with the rest in input order.

    Public because `explain_log` is not the only place assembling the user's
    Issue list: `run_build` appends analysis warnings. While both sides sorted
    independently, a "code contains an access key" warning appeared before the
    BLOCKER that actually stopped the build — and task 20 presents the first
    Issue most prominently.

    `sorted` is stable, preserving order within one priority.
    """
    return tuple(sorted(issues, key=lambda issue: SEVERITY_ORDER[issue.severity]))


# Some codes are deliberately generic fallbacks for a symptom that a more
# specific pattern also recognises (e.g. "access_denied" is the neutral
# catch-all for the same raw signal "antivirus_blocked" and "file_in_use"
# key off of with extra evidence). When a more specific code has already
# fired for this log, the neutral one is suppressed — showing both would
# repeat the same underlying event as two unrelated-looking messages.
_SUPPRESSED_BY: dict[str, frozenset[str]] = {
    "access_denied": frozenset({"antivirus_blocked", "file_in_use"}),
}


def explain_log(log: str) -> tuple[Issue, ...]:
    """Match every pattern against ``log`` at most once and return sorted Issues.

    Blockers sort first (Task 20 shows the first issue most prominently).
    Each pattern contributes at most one Issue, even if it matches many times.
    A neutral fallback code is dropped when a more specific code (see
    ``_SUPPRESSED_BY``) already matched the same log.
    """
    found: list[Issue] = []
    seen: set[str] = set()
    for pattern, code, severity in PATTERNS:
        if code in seen:
            continue
        match = pattern.search(log)
        if not match:
            continue
        seen.add(code)
        data = {"module": match.group(1)} if match.groups() else {}
        found.append(Issue(code, severity, data))

    found = [issue for issue in found if not (_SUPPRESSED_BY.get(issue.code, frozenset()) & seen)]
    return sort_issues(found)
