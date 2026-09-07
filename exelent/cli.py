"""CLI rdzenia — pełna ścieżka od katalogu do EXE bez GUI.

Istnieje po to, żeby logikę dało się testować i uruchamiać bez okna,
i dlatego, że rdzeń nie zależy od Qt.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from exelent.analysis.project import analyze_project
from exelent.build.backend import CancelToken
from exelent.build.pyinstaller import PyInstallerBackend, log_path_for
from exelent.build.validate import validate_target_syntax
from exelent.build.workspace import materialize_workspace
from exelent.diagnostics.patterns import explain_log, filename_of, map_os_error, sort_issues
from exelent.models import BuildPlan, BuildResult, Issue, IssueError, Severity
from exelent.planning import is_cloud_synced, make_plan
from exelent.runtime import Progress, ProgressFn
from exelent.runtime.bootstrap import check_preconditions
from exelent.runtime.env import create_build_env


def _print_progress(update: Progress) -> None:
    print(f"[{update.fraction * 100:5.1f}%] {update.phase}", flush=True)


# Ile paska zajmuje przygotowanie środowiska. Reszta należy do PyInstallera,
# bo to on trwa najdłużej.
ENV_PROGRESS_SHARE = 0.3


class _Progress:
    """Jedna skala 0..1 dla całej drogi, sklejona z dwóch niezależnych.

    `create_build_env` liczy swoje 0..1 i `PyInstallerBackend` swoje — obie
    słusznie, bo żadna nie wie o istnieniu drugiej. Bez sklejenia pasek
    postępu dochodzi do 100% po zainstalowaniu paczek i zaczyna od nowa od
    20% (zmierzone na żywym buildzie), czyli mówi użytkownikowi, że program
    stracił dotychczasową pracę.

    Wartość nigdy nie maleje: PyInstaller wraca do fazy „Analyzing" po
    „Processing module hooks", więc nawet w obrębie jednej skali kolejność
    komunikatów nie jest rosnąca. Cofający się pasek jest gorszy niż stojący.
    """

    def __init__(self, report: ProgressFn) -> None:
        self._report = report
        self._highest = 0.0

    def stage(self, start: float, end: float) -> ProgressFn:
        def report(update: Progress) -> None:
            value = start + (end - start) * min(max(update.fraction, 0.0), 1.0)
            self._highest = max(self._highest, value)
            self._report(replace(update, fraction=self._highest))

        return report


def _unexpected_issues(exc: BaseException) -> tuple[Issue, ...]:
    """Ostatnia siatka bezpieczenstwa: cokolwiek to bylo, ma byc kodem.

    Wyjatek idzie przez `map_os_error`, a NIE przez `explain_log`. Tamta
    tabela opisuje log PyInstallera i ma w sobie pewne siebie ramie
    antywirusowe, ktore dla artefaktu w `dist` jest sluszne, a dla pliku
    zrodlowego uzytkownika bylo by bledna rada: plik z OneDrive daje przy
    odczycie ten sam WinError 1920, a laik po takiej podpowiedzi wylacza
    antywirusa i nic sie nie zmienia.
    """
    if isinstance(exc, OSError):
        in_cloud = False
        filename = filename_of(exc)
        if filename:
            with suppress(OSError, ValueError):
                in_cloud = is_cloud_synced(Path(filename))
        recognised = map_os_error(exc, in_cloud=in_cloud)
        if recognised:
            return recognised
    return (Issue("unexpected_error", Severity.BLOCKER, {"error": type(exc).__name__}),)


def _existing_log(plan: BuildPlan | None) -> Path | None:
    """Log TEGO builda, o ile powstal.

    `plan` przychodzi tu dopiero, gdy ten przebieg skasowal stary log
    (`_clear_stale_log`) — od tego momentu istnienie pliku znaczy "ten
    przebieg cos zapisal". Wczesniej plan bywa juz policzony, ale log pod ta
    sciezka nalezy jeszcze do POPRZEDNIEGO przebiegu: dolaczony do zgloszenia
    opisywalby zupelnie inna awarie, a zadanie 20 podpina pod `log_path`
    przycisk "Zapisz raport".
    """
    if plan is None:
        return None
    path = log_path_for(plan)
    with suppress(OSError):
        if path.exists():
            return path
    return None


def _clear_stale_log(plan: BuildPlan) -> None:
    with suppress(OSError):
        log_path_for(plan).unlink(missing_ok=True)


def run_build(
    root: Path,
    progress: ProgressFn = _print_progress,
    cancel: CancelToken | None = None,
    **overrides,
) -> BuildResult:
    """Pełna droga z KATALOGU do EXE: analiza, plan, build.

    Adapter dla konsoli i dla każdego, kto ma tylko ścieżkę. Właściwe budowanie
    (to samo, którego używa GUI z gotowym planem) mieszka w `execute_build`.
    """
    cancel = cancel or CancelToken()

    # Ostrzezenia analizy (sekrety w kodzie, ciezkie paczki, niepewny plik
    # glowny) sa jedyna droga, ktora CLI moze o nich powiedziec — GUI pokazuje
    # je na ekranie 2, konsola nie ma takiego ekranu.
    carried: list[Issue] = []

    # Granica wyjatkow na etap analizy i planu. `analyze_project` czyta kazdy
    # plik uzytkownika (jeden z odmowa ACL albo dostepny tylko w chmurze konczyl
    # sie surowym tracebackiem), a `make_plan` robi sonde zapisywalnosci i
    # wywolanie Win32. Sam build ma wlasna granice w `execute_build`.
    try:
        analysis = analyze_project(Path(root))
        carried.extend(i for i in analysis.issues if i.severity is not Severity.BLOCKER)

        blockers = tuple(i for i in analysis.issues if i.severity is Severity.BLOCKER)
        if blockers:
            return BuildResult(ok=False, issues=sort_issues((*carried, *blockers)))

        # Brak pliku glownego sprawdzamy TUTAJ, a nie lapiac `ValueError` z
        # `make_plan`: `make_plan` robi dzis I/O (sonda zapisywalnosci, Win32),
        # wiec kazdy przyszly `ValueError` z niego nazwalby sie mylnie
        # "nie znaleziono pliku glownego". Teraz taki blad dostaje uczciwe
        # `unexpected_error` z ogolnego ramienia.
        if (overrides.get("entry") or analysis.entry) is None:
            return BuildResult(
                ok=False,
                issues=sort_issues((*carried, Issue("no_entry_point", Severity.BLOCKER))),
            )

        plan = make_plan(analysis, **overrides)
    except IssueError as exc:
        return BuildResult(ok=False, issues=sort_issues((*carried, *exc.issues)))
    except Exception as exc:  # noqa: BLE001 - to JEST granica, tu sie konczy stos
        return BuildResult(ok=False, issues=sort_issues((*carried, *_unexpected_issues(exc))))

    return execute_build(plan, progress, cancel, carried=carried)


def execute_build(
    plan: BuildPlan,
    progress: ProgressFn = _print_progress,
    cancel: CancelToken | None = None,
    *,
    carried: Sequence[Issue] = (),
) -> BuildResult:
    """Buduje DOKŁADNIE podany plan. Wspólna usługa rdzenia dla GUI i CLI.

    GUI przekazuje gotowy plan z ekranu 2; CLI składa plan z analizy i woła to
    samo. Kluczowe: tu NIE MA ponownej analizy źródeł — wybór pojedynczego
    pliku, poprawiona lista zależności i konwersje TXT są brane wprost z planu,
    więc build nie rozszerza po cichu zakresu do całego folderu (A02).

    `carried` to ostrzeżenia z wcześniejszych etapów (analiza), które mają
    dotrzeć do wyniku niezależnie od tego, jak skończy się build (A08).
    """
    cancel = cancel or CancelToken()
    carried_issues: list[Issue] = list(carried)

    # Plan, ktorego log NALEZY do tego przebiegu — ustawiany dopiero po
    # skasowaniu starego logu. Przed tym pod ta sciezka lezy jeszcze log
    # poprzedniego przebiegu.
    log_owner: BuildPlan | None = None

    def _fail(issues: Sequence[Issue]) -> BuildResult:
        return BuildResult(
            ok=False,
            issues=sort_issues((*carried_issues, *issues)),
            log_path=_existing_log(log_owner),
        )

    try:
        preconditions = check_preconditions(need_network=True)
        if preconditions:
            return _fail(preconditions)

        # Kasowanie starego logu dopiero TUTAJ: od tego miejsca naprawde
        # budujemy, wiec "log istnieje" znaczy "ten przebieg go zapisal".
        _clear_stale_log(plan)
        log_owner = plan

        result = _build(plan, carried_issues, progress, cancel)
    except IssueError as exc:
        return _fail(exc.issues)
    except Exception as exc:  # noqa: BLE001 - to JEST granica, tu sie konczy stos
        return _fail(_unexpected_issues(exc))

    if result.ok and result.artifact is None:
        # Sprzecznosc, nie sukces: w gore poszedlby `BuildResult`, ktory mowi
        # "udalo sie", a nie ma czego pokazac. Zdejmujemy ja tutaj, zeby
        # warstwa prezentacji nie musiala wymyslac, co z takim czyms zrobic.
        vanished = Issue("artifact_vanished", Severity.BLOCKER, {"name": plan.exe_name})
        return replace(
            result,
            ok=False,
            issues=sort_issues((*carried_issues, *result.issues, vanished)),
        )

    return replace(result, issues=sort_issues((*carried_issues, *result.issues)))


def _was_cancelled(result: BuildResult) -> bool:
    return any(issue.code == "build_cancelled" for issue in result.issues)


def _build(
    plan,
    carried: list[Issue],
    progress: ProgressFn,
    cancel: CancelToken,
) -> BuildResult:
    """Wlasciwy build. Wolane wylacznie spod granicy wyjatkow w `execute_build`."""
    workspace = materialize_workspace(plan)

    scale = _Progress(progress)
    env = create_build_env(
        plan.root,
        plan.packages,
        scale.stage(0.0, ENV_PROGRESS_SHARE),
        # Docelowa wersja Pythona bierze sie Z PLANU, nie z domyslnej stalej:
        # plan jest jedynym zrodlem prawdy o tym, co budujemy (A13).
        python_version=plan.python_version,
        single_file=plan.single_file,
        total_download_bytes=plan.total_download_bytes,
        cancel=cancel,
    )
    if env.failed_packages:
        # Wszystkie paczki w planie sa WYMAGANE (opcjonalne odpadly w
        # make_plan). Nieudana instalacja ktorejkolwiek znaczy niekompletne
        # srodowisko — nie budujemy EXE, ktory u odbiorcy padnie na
        # ModuleNotFoundError. Zatrzymujemy sie z blokada, a nie ostrzezeniem
        # ginacym na ekranie sukcesu (A08).
        return BuildResult(
            ok=False,
            issues=(
                Issue(
                    "required_package_failed",
                    Severity.BLOCKER,
                    {"packages": ", ".join(env.failed_packages)},
                ),
            ),
        )

    # Skladnia przygotowanych zrodel sprawdzona DOCELOWYM interpreterem (z planu),
    # a nie deweloperskim ast.parse: kod poprawny w 3.13, lecz niezgodny z 3.12,
    # inaczej przechodzi az do PyInstallera, ktory po cichu wyrzuca modul i konczy
    # z kodem 0 — pozorny sukces bez kodu uzytkownika (A08).
    syntax_issue = validate_target_syntax(
        env.python, workspace, python_version=plan.python_version, cancel=cancel
    )
    if syntax_issue is not None:
        return BuildResult(ok=False, issues=(syntax_issue,))

    result = PyInstallerBackend().build(plan, env, scale.stage(ENV_PROGRESS_SHARE, 1.0), cancel)

    if _was_cancelled(result):
        # Log anulowanego builda urywa sie tam, gdzie uzytkownik nacisnal
        # przycisk — w polowie kroku, czesto w polowie zdania. `explain_log`
        # dopasowalby wzorce do tego urwanego tekstu i opisal awarie, ktora
        # nigdy nie nastapila; przerwanie ma zostac przerwaniem.
        return result

    if not result.ok and result.log_path and result.log_path.exists():
        # Swiadomie caly log, bez `tail()`: `explain_log` jest liniowe
        # (~0.017 s/MB, zmierzone w zadaniu 14), a obciecie do ostatnich N
        # linii potrafiloby ukryc blad, ktory padl wczesnie i tylko odbil sie
        # echem na koncu.
        log = result.log_path.read_text(encoding="utf-8", errors="replace")
        return replace(result, issues=(*result.issues, *explain_log(log)))

    return result


def _print_issues(issues: Sequence[Issue], stream) -> None:
    for issue in issues:
        detail = dict(issue.data)
        print(f"  - [{issue.severity.value}] {issue.code} {detail or ''}", file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exelent", description="Zrob EXE z katalogu z kodem")
    parser.add_argument("directory", type=Path, help="katalog z plikami kodu")
    parser.add_argument("--name", dest="exe_name", help="nazwa pliku wynikowego")
    parser.add_argument("--icon", type=Path, help="plik ikony (.png, .jpg lub .ico)")
    parser.add_argument("--out", dest="dest_dir", type=Path, help="katalog docelowy")
    args = parser.parse_args(argv)

    overrides = {k: v for k, v in vars(args).items() if k != "directory" and v is not None}
    result = run_build(args.directory, **overrides)

    if result.ok and result.artifact:
        print(f"\nGotowe: {result.artifact} ({result.size_bytes / 1024**2:.1f} MB)")
        if result.issues:
            print("Uwagi:", file=sys.stderr)
            _print_issues(result.issues, sys.stderr)
        return 0

    # `run_build` zdejmuje ta sprzecznosc u zrodla, ale `main` drukuje to, co
    # dostalo — a "Build nie powiodl sie" przy `ok=True` bylo mina dla kazdego,
    # kto kiedys poda tu wynik z innego miejsca.
    headline = (
        "\nBuild zakonczyl sie bez pliku wynikowego." if result.ok else "\nBuild nie powiodl sie."
    )
    print(headline, file=sys.stderr)
    _print_issues(result.issues, sys.stderr)
    if result.log_path:
        print(f"  log: {result.log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
