"""Lines emitted by uv about its work → typed events.

The only place in the program that knows how uv talks. All patterns come
from MEASURED output of uv 0.8.17 on a pipe (not a terminal — on a pipe
uv does not draw progress bars, it prints event lines).

The parser never raises. Progress is cosmetic; an exception from here would
kill a build whose only fault was an unusual line in the log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DOWNLOAD_START = "download_start"
DOWNLOAD_DONE = "download_done"
RESOLVED = "resolved"
WOULD_DOWNLOAD = "would_download"
PREPARED = "prepared"
INSTALLED = "installed"
PACKAGE = "package"
UNCACHED_PACKAGE = "uncached_package"

_UNITS = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}

# Size is in the LAST parenthesised group, not the first: the interpreter
# name contains its own parenthesised group — measured:
#   "Downloading cpython-3.11.13-windows-x86_64-none (download) (24.3MiB)"
# A pattern anchored to the first parenthesis took "(download)" as the size.
_START = re.compile(r"^Downloading (?P<name>.+?) \((?P<size>[\d.]+)(?P<unit>KiB|MiB|GiB)\)$")
_DONE = re.compile(r"^ +Downloading (?P<name>.+?)$")
_RESOLVED = re.compile(r"^Resolved (?P<count>\d+) packages? in ")
_WOULD = re.compile(r"^Would download (?P<count>\d+) packages?$")
_PREPARED = re.compile(r"^Prepared (?P<count>\d+) packages? in ")
_INSTALLED = re.compile(r"^Installed (?P<count>\d+) packages? in ")
# A result line is "name==version". Interpreter installation prints in the
# same shape "cpython-... (python3.11.exe)", which is not a package.
_PACKAGE = re.compile(r"^ \+ (?P<name>[^\s]+==[^\s]+)$")
_UNCACHED_PACKAGE = re.compile(
    r"^(?:DEBUG|TRACE) Identified uncached distribution: (?P<name>[^\s]+==[^\s]+)$"
)


@dataclass(frozen=True)
class UvEvent:
    kind: str
    name: str = ""
    size_bytes: int = 0
    count: int = 0


def parse_line(line: str) -> UvEvent | None:
    """One uv line → event or None if we don't recognise it."""
    stripped = line.rstrip("\r\n")

    match = _START.match(stripped)
    if match:
        size = float(match["size"]) * _UNITS[match["unit"]]
        return UvEvent(DOWNLOAD_START, name=match["name"], size_bytes=int(size))

    match = _PACKAGE.match(stripped)
    if match:
        return UvEvent(PACKAGE, name=match["name"])

    match = _UNCACHED_PACKAGE.match(stripped)
    if match:
        return UvEvent(UNCACHED_PACKAGE, name=match["name"])

    # AFTER `_PACKAGE`, because both start with a space and only order separates them.
    match = _DONE.match(stripped)
    if match:
        return UvEvent(DOWNLOAD_DONE, name=match["name"])

    for pattern, kind in (
        (_RESOLVED, RESOLVED),
        (_WOULD, WOULD_DOWNLOAD),
        (_PREPARED, PREPARED),
        (_INSTALLED, INSTALLED),
    ):
        match = pattern.match(stripped)
        if match:
            return UvEvent(kind, count=int(match["count"]))

    return None
