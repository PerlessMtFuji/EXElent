"""Bezpieczne opublikowanie gotowego artefaktu w katalogu docelowym (A01).

Zasada: kolejny build NIGDY nie nadpisuje istniejącego pliku ani katalogu.
Poprzednia wersja mogła zapisać obok EXE bazę danych albo konfigurację —
skasowanie jej przy publikacji nowego builda to nieodwracalna utrata danych u
odbiorcy, który nie używa gita ani kosza z historią.

Dlatego:

- Nazwa docelowa jest wybierana tak, żeby była wolna: `Program.exe`, a jeśli
  istnieje — `Program (2).exe`, `Program (3).exe`, … (tak jak robi to Eksplorator
  przy kopiowaniu, więc laik to rozpoznaje).
- Artefakt najpierw ląduje w tymczasowym miejscu NA WOLUMINIE DOCELOWYM, jest
  sprawdzany pod kątem kompletności, a dopiero potem finalizowany zmianą nazwy
  w obrębie tego woluminu. Zmiana nazwy na tym samym woluminie jest atomowa:
  albo istnieje kompletny artefakt pod docelową nazwą, albo nie ma nic — nigdy
  połowa skopiowanych plików podszywających się pod gotowy program.
- Każda awaria (brak miejsca, odmowa dostępu, wyścig o nazwę, zablokowany plik)
  zostawia poprzedni artefakt nietknięty i nie zostawia niedokończonych śmieci.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from exelent.diagnostics.patterns import map_os_error
from exelent.models import Issue, Severity

# Prefiks katalogu/pliku roboczego publikacji. Kropka na początku, żeby nie
# rzucał się w oczy w Eksploratorze, i rozpoznawalny człon, żeby dało się
# jednoznacznie odróżnić śmieci tej sesji od plików użytkownika.
_STAGING_PREFIX = ".exelent-publish-"


def _tree_signature(path: Path) -> tuple[int, int]:
    """(liczba plików, suma bajtów) — tanie sprawdzenie kompletności kopii.

    Nie porównujemy bajt po bajcie: dla artefaktu ONEDIR to setki plików i
    kilkaset MB. Zgodność liczby plików i sumy rozmiarów wystarcza, żeby
    wychwycić kopię przerwaną w połowie (brak plików, obcięty plik)."""
    if path.is_file():
        return 1, path.stat().st_size
    count = 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            count += 1
            total += item.stat().st_size
    return count, total


def _unique_target(dest_dir: Path, stem: str, suffix: str, start_at: int = 1) -> Path | None:
    """Pierwsza wolna nazwa: `stem+suffix`, potem `stem (2)+suffix`, …

    `start_at` pozwala wznowić numerację po przegranym wyścigu o nazwę, żeby nie
    zaczynać sprawdzania od początku po każdej kolizji."""
    n = start_at
    while n < start_at + 10_000:
        name = f"{stem}{suffix}" if n == 1 else f"{stem} ({n}){suffix}"
        candidate = dest_dir / name
        if not candidate.exists():
            return candidate
        n += 1
    return None


def publish_artifact(
    source: Path, dest_dir: Path, exe_name: str, *, is_onedir: bool, cancel=None
) -> tuple[Path | None, tuple[Issue, ...]]:
    """Kopiuje `source` do `dest_dir` pod wolną nazwą i zwraca ścieżkę wyniku.

    Zwraca `(ścieżka, ())` przy sukcesie albo `(None, issues)` przy awarii.
    Nigdy nie modyfikuje ani nie usuwa niczego, co już było w `dest_dir`.
    """
    suffix = "" if is_onedir else ".exe"

    # B10: anulowanie PRZED kopiowaniem nie tworzy stagingu.
    if cancel is not None and cancel.cancelled:
        return None, (Issue("build_cancelled", Severity.INFO),)

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, _os_error_issues(exc, dest_dir)

    staging = dest_dir / f"{_STAGING_PREFIX}{uuid.uuid4().hex}"
    try:
        if is_onedir:
            shutil.copytree(source, staging)
        else:
            shutil.copy2(source, staging)
    except OSError as exc:
        _remove_quietly(staging)
        return None, _os_error_issues(exc, source)

    # B10: anulowanie PO skopiowaniu, ale PRZED finalizacją — staging jest
    # kompletny, ale nie opublikowany. Sprzątamy go; poprzedni artefakt
    # zostaje nietknięty.
    if cancel is not None and cancel.cancelled:
        _remove_quietly(staging)
        return None, (Issue("build_cancelled", Severity.INFO),)

    try:
        complete = _is_complete(source, staging, exe_name, is_onedir)
    except OSError:
        _remove_quietly(staging)
        return None, (Issue("publish_incomplete", Severity.BLOCKER, {"name": exe_name}),)

    if not complete:
        _remove_quietly(staging)
        return None, (Issue("publish_incomplete", Severity.BLOCKER, {"name": exe_name}),)

    start_at = 1
    for _ in range(100):
        target = _unique_target(dest_dir, exe_name, suffix, start_at=start_at)
        if target is None:
            break
        try:
            staging.rename(target)
            return target, ()
        except FileExistsError:
            start_at = _next_index(target, exe_name, suffix) + 1
            continue
        except OSError as exc:
            _remove_quietly(staging)
            return None, _os_error_issues(exc, target)

    _remove_quietly(staging)
    return None, (Issue("publish_incomplete", Severity.BLOCKER, {"name": exe_name}),)


def _is_complete(source: Path, staging: Path, exe_name: str, is_onedir: bool) -> bool:
    if _tree_signature(source) != _tree_signature(staging):
        return False
    return not (is_onedir and not (staging / f"{exe_name}.exe").exists())


def _next_index(target: Path, stem: str, suffix: str) -> int:
    """Numer wyliczony z nazwy `stem (n)+suffix`; 1 dla `stem+suffix`."""
    name = target.name
    plain = f"{stem}{suffix}"
    if name == plain:
        return 1
    inner = name[len(stem) + 2 : len(name) - len(suffix) - 1]  # `stem (` … `)suffix`
    try:
        return int(inner)
    except ValueError:
        return 1


def _os_error_issues(exc: OSError, related: Path) -> tuple[Issue, ...]:
    mapped = map_os_error(exc)
    if mapped:
        return mapped
    return (Issue("publish_failed", Severity.BLOCKER, {"path": str(related)}),)


def _remove_quietly(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
