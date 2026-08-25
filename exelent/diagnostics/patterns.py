"""Log builda -> kody Issue. Warstwa prezentacji tlumaczy kody na zdania.

Zasada: uzytkownik nigdy nie widzi surowego tracebacku jako glownego komunikatu.
Kazdy nierozpoznany blad staje sie kandydatem na nowy wzorzec ponizej.
"""

from __future__ import annotations

import re

from exelent.models import Issue, Severity

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
    (
        re.compile(r"WinError 5\b|Access is denied.*dist"),
        "antivirus_blocked",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"WinError 206|filename or extension is too long"),
        "path_too_long",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"certificate verify failed|SSLCertVerificationError|SSLError"),
        "ssl_proxy",
        Severity.BLOCKER,
    ),
    (
        re.compile(r"Errno 28|No space left on device"),
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

_SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.WARNING: 1, Severity.INFO: 2}


def explain_log(log: str) -> tuple[Issue, ...]:
    """Match every pattern against ``log`` at most once and return sorted Issues.

    Blockers sort first (Task 20 shows the first issue most prominently).
    Each pattern contributes at most one Issue, even if it matches many times.
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
    found.sort(key=lambda issue: _SEVERITY_ORDER[issue.severity])
    return tuple(found)
