"""Linie, którymi uv opowiada o swojej pracy → typowane zdarzenia.

To jedyne miejsce w programie, które wie, jak uv mówi. Wszystkie wzorce
pochodzą ze ZMIERZONEGO wyjścia uv 0.8.17 na potoku (nie na terminalu — na
potoku uv nie rysuje pasków, tylko drukuje linie zdarzeń).

Parser nigdy nie rzuca. Postęp jest ozdobą; wyjątek stąd zabiłby build,
którego jedyną winą było nietypowe zdanie w logu.
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

_UNITS = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}

# Rozmiar jest w OSTATNIM nawiasie linii, a nie w pierwszym: nazwa
# interpretera zawiera własny nawias — zmierzone:
#   "Downloading cpython-3.11.13-windows-x86_64-none (download) (24.3MiB)"
# Wzorzec zakotwiczony na pierwszym nawiasie brał "(download)" za rozmiar.
_START = re.compile(r"^Downloading (?P<name>.+?) \((?P<size>[\d.]+)(?P<unit>KiB|MiB|GiB)\)$")
_DONE = re.compile(r"^ +Downloading (?P<name>.+?)$")
_RESOLVED = re.compile(r"^Resolved (?P<count>\d+) packages? in ")
_WOULD = re.compile(r"^Would download (?P<count>\d+) packages?$")
_PREPARED = re.compile(r"^Prepared (?P<count>\d+) packages? in ")
_INSTALLED = re.compile(r"^Installed (?P<count>\d+) packages? in ")
# Pozycja wyniku to "nazwa==wersja". Instalacja interpretera drukuje w tym
# samym kształcie "cpython-... (python3.11.exe)", co pakietem nie jest.
_PACKAGE = re.compile(r"^ \+ (?P<name>[^\s]+==[^\s]+)$")


@dataclass(frozen=True)
class UvEvent:
    kind: str
    name: str = ""
    size_bytes: int = 0
    count: int = 0


def parse_line(line: str) -> UvEvent | None:
    """Jedna linia uv → zdarzenie albo None, gdy jej nie znamy."""
    stripped = line.rstrip("\r\n")

    match = _START.match(stripped)
    if match:
        size = float(match["size"]) * _UNITS[match["unit"]]
        return UvEvent(DOWNLOAD_START, name=match["name"], size_bytes=int(size))

    match = _PACKAGE.match(stripped)
    if match:
        return UvEvent(PACKAGE, name=match["name"])

    # PO `_PACKAGE`, bo obie zaczynają się od spacji i tylko kolejność je dzieli.
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
