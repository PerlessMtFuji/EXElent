"""Log builda -> kody Issue. Warstwa prezentacji tlumaczy kody na zdania.

Zasada: uzytkownik nigdy nie widzi surowego tracebacku jako glownego komunikatu.
Kazdy nierozpoznany blad staje sie kandydatem na nowy wzorzec ponizej.

Zasada nadrzedna dla samych wzorcow: diagnoza musi byc albo rozrozniajaca,
albo neutralna — nigdy pewna siebie i bledna. Ten modul istnieje, zeby
zastapic sciane tracebacku zdaniem plus akcja. Zdanie z ZLA akcja jest
gorsze niz brak zdania: uzytkownik traci godzine na wylaczanie antywirusa,
build dalej pada, i przestaje ufac kazdemu kolejnemu komunikatowi. Gdy dowod
w logu nie rozroznia dwoch przyczyn jednoznacznie, wzorzec ma zglosic
neutralny kod, a nie zgadywac bardziej konkretny.
"""

from __future__ import annotations

import re

from exelent.models import Issue, Severity

# Surowy sygnal "Windows odmowil dostepu". Sam w sobie nie rozroznia przyczyn.
_ACCESS_DENIED = r"(?:WinError 5\b|Access is denied)"

# Fragment wskazujacy, ze chodzi o katalog wyjsciowy builda.
#
# Wymagamy separatora sciezki po ktorejs ze stron, wiec "dist" musi byc
# realnym segmentem sciezki ("...\dist\app.exe", "C:/proj/dist"), a nie
# przypadkowym slowem. Jawne (?!-info) odcina wszechobecne katalogi metadanych
# pakietow ("numpy-1.26.4.dist-info") — myslnik jest znakiem niebedacym
# znakiem slowa, wiec samo \b ich NIE wyklucza. Separator moze byc "/", "\"
# albo podwojony "\\": logi PyInstallera i powtorzone reprezentacje sciezek
# w tracebackach zawieraja wszystkie te formy.
_DIST_SEGMENT = r"(?:[\\/]{1,2}dist\b(?!-info)|\bdist\b(?!-info)[\\/]{1,2})"

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
    # Koniunkcja celowa: samo "WinError 5" / "Access is denied" jest jednym z
    # najbardziej ogolnych bledow Windows i ma mnostwo przyczyn niezwiazanych
    # z antywirusem (plik otwarty w innym programie, blokada OneDrive,
    # katalog wymagajacy podniesienia uprawnien). Zglaszamy antivirus_blocked
    # tylko, gdy w logu jest TAKZE dowod, ze chodzi o artefakt builda (dist).
    #
    # Oba dowody musza pochodzic z TEGO SAMEGO zdarzenia, czyli z tej samej
    # linii logu. Wczesniejsza wersja uzywala niezakotwiczonych lookaheadow z
    # re.DOTALL, wiec kazdy z nich przeszukiwal caly log niezaleznie: dowolny
    # niepowiazany "WinError 5" gdziekolwiek plus slowo "dist" gdziekolwiek
    # indziej dawaly pewna i BLEDNA diagnoze. Tutaj "^" z re.MULTILINE
    # zakotwicza oba lookaheady na poczatku tej samej linii, a "[^\n]*" nie
    # przekracza konca linii, wiec wspolwystepowanie w skali dokumentu nie
    # wystarcza.
    (
        re.compile(
            rf"^(?=[^\n]*{_ACCESS_DENIED})(?=[^\n]*{_DIST_SEGMENT})",
            re.MULTILINE,
        ),
        "antivirus_blocked",
        Severity.BLOCKER,
    ),
    # WinError 32 ("plik jest uzywany przez inny proces") jest odrozniane od
    # antywirusa — najczestsza przyczyna to wciaz dzialajacy poprzedni EXE
    # przy rebuildzie, a odpowiednia akcja to "zamknij program i sprobuj
    # ponownie", zupelnie inna niz przy antywirusie.
    (
        re.compile(r"WinError 32\b|used by another process"),
        "file_in_use",
        Severity.BLOCKER,
    ),
    # Neutralny fallback: "WinError 5" / "Access is denied" bez dowodu, ze to
    # dist ani ze to WinError 32 — nie zgadujemy przyczyny, mowimy tylko, ze
    # Windows odmowil dostepu do pliku. Tlumiony w explain_log(), gdy w tym
    # samym logu wystapil juz bardziej konkretny kod (antivirus_blocked /
    # file_in_use), zeby nie pokazywac dwoch komunikatow o tym samym zdarzeniu.
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

_SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.WARNING: 1, Severity.INFO: 2}

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
    found.sort(key=lambda issue: _SEVERITY_ORDER[issue.severity])
    return tuple(found)
