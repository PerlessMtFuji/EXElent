"""Prawdziwe buildy: katalog z kodem -> plik EXE -> uruchomienie tego EXE.

To jedyny dowod, ze produkt dziala. Kazdy przypadek uruchamia powstaly
program jako podproces i sprawdza JEGO wyjscie — build, ktory "sie udal",
a produkuje EXE wywalajace sie przy starcie, jest dokladnie ta awaria,
ktorej ten projekt ma zapobiegac.
"""

from pathlib import Path

import pytest
from procutil import is_running_name, run_bounded

from exelent.cli import run_build
from exelent.models import OutputMode
from exelent.runtime import noop_progress

pytestmark = pytest.mark.slow

# Artefakty builda (build/, dist/, *.spec) nigdy nie moga pojawic sie w
# katalogu uzytkownika — sekcja 7 specyfikacji.
FORBIDDEN_IN_SOURCE = ("build", "dist", "__pycache__", "_exelent_launcher.py")


def _project(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    root = tmp_path / name
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def shared_state(tmp_path_factory):
    """Jeden katalog stanu na CALY przebieg golden.

    Kazdy test podstawial wlasny `LOCALAPPDATA`, wiec kazdy od nowa pobieral
    `uv.exe` i instalowal CPythona — szesc razy to samo, po kilkadziesiat
    megabajtow, i to w przebiegu, ktory i tak jest najdrozszy w projekcie.
    Izolacja, ktorej te testy naprawde potrzebuja, dotyczy katalogu ROBOCZEGO,
    a ten jest kluczowany hashem sciezki projektu — kazdy test ma wlasny
    `tmp_path`, wiec wspolny katalog stanu niczego miedzy nimi nie miesza.
    """
    state = tmp_path_factory.mktemp("exelent-state")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOCALAPPDATA", str(state))
        yield state


def _assert_source_untouched(root: Path, expected: set[str]) -> None:
    """§7 specyfikacji: katalog uzytkownika ma zostac dokladnie taki, jaki byl.

    Sprawdzane jest CALE drzewo, nie sam najwyzszy poziom. Wersja plytka
    przepuszczala dokladnie te smieci, ktore PyInstaller robi najchetniej:
    `__pycache__` obok modulu w podkatalogu, `build/` wewnatrz pakietu,
    plik `.spec` zapisany glebiej niz w korzeniu. Dla projektu plaskiego
    obie wersje znacza to samo — roznica zaczyna sie tam, gdzie uzytkownik
    trzyma kod w folderach, czyli w kazdym projekcie wiekszym od jednego pliku.
    """
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")}
    assert actual == expected, f"katalog zrodlowy zmieniony: {actual ^ expected}"
    for name in FORBIDDEN_IN_SOURCE:
        assert not list(root.rglob(name)), f"build zostawil `{name}` w katalogu zrodlowym"
    assert not list(root.rglob("*.spec"))


def test_console_program_builds_and_prints(tmp_path, shared_state):
    root = _project(
        tmp_path,
        "witaj",
        {
            "main.py": "print('WITAJ-SWIECIE')\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=120)
    assert "WITAJ-SWIECIE" in run.stdout
    _assert_source_untouched(root, {"main.py"})


def test_program_reading_bundled_data_file(tmp_path, shared_state):
    root = _project(
        tmp_path,
        "dane",
        {
            "main.py": "import json\nprint(json.load(open('dane.json'))['klucz'])\n",
            "dane.json": '{"klucz": "WARTOSC-Z-PLIKU"}',
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=120)
    assert "WARTOSC-Z-PLIKU" in run.stdout


def test_txt_source_is_converted_and_built(tmp_path, shared_state):
    """Sztandarowa funkcja: kod w .txt, prosto z okna czatu."""
    root = _project(
        tmp_path,
        "z-czatu",
        {
            "program.txt": "Oto twoj program:\n\n```python\nprint('Z-PLIKU-TXT')\n```\n\nMilego!",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]
    assert not (root / "program.py").exists(), "katalog zrodlowy musi zostac nietkniety"
    _assert_source_untouched(root, {"program.txt"})

    run = run_bounded([_exe_of(result)], timeout=120)
    assert "Z-PLIKU-TXT" in run.stdout


def test_program_with_third_party_dependency(tmp_path, shared_state):
    root = _project(
        tmp_path,
        "obrazek",
        {
            "main.py": "from PIL import Image\nprint('PILLOW-OK', Image.new('RGB',(2,2)).size)\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "PILLOW-OK" in run.stdout


def test_two_packages_vendoring_the_same_dll_both_load(tmp_path, shared_state):
    """Zgloszenie: numpy + pandas w jednym programie dawaly EXE, ktore umieralo
    na `DLL load failed while importing _multiarray_umath`.

    delvewheel wektoruje `msvcp140-<hash>.dll` i do `numpy.libs`, i do
    `pandas.libs` — pod ta sama nazwa pliku. PyInstaller rozwiazuje zaleznosci
    binarne po samej nazwie i bierze PIERWSZE trafienie, wiec do paczki wchodzi
    wylacznie kopia z `pandas.libs`, a numpy przy imporcie widzi tylko
    `numpy.libs`, bo jedynie ten katalog rejestruje jego lata delvewheel.

    Kolejnosc importow jest czescia przypadku i ma zostac taka, jaka jest:
    numpy idzie PIERWSZY, zanim cokolwiek pokaze Windowsowi `pandas.libs`.

    Zaden test na napisach tego nie zlapie — biblioteka gubi sie miedzy
    hookami PyInstallera a ladowaczem DLL Windowsa, wiec dowodem moze byc
    tylko EXE, ktore naprawde wstalo.
    """
    root = _project(
        tmp_path,
        "liczby",
        {
            "main.py": (
                "import numpy as np\n"
                "import pandas as pd\n"
                "print('LICZBY-OK', int(np.arange(4).sum()), len(pd.DataFrame({'a': [1, 2]})))\n"
            ),
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=300)
    assert "LICZBY-OK 6 2" in run.stdout


def test_writing_program_gets_onedir_and_writes_next_to_exe(tmp_path, shared_state):
    root = _project(
        tmp_path,
        "zapis",
        {
            "main.py": "open('wynik.txt','w',encoding='utf-8').write('ZAPISANE')\nprint('OK')\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    exe = result.artifact / "zapis.exe" if result.artifact.is_dir() else result.artifact
    run_bounded([exe], timeout=120, cwd=exe.parent)
    assert (exe.parent / "wynik.txt").read_text(encoding="utf-8") == "ZAPISANE"


# --- B01: zapis nie ginie, choc heurystyka go nie widzi; cwd jest trwaly ---
#
# Wspolny motyw: EXE uruchamiany z OBCEGO katalogu roboczego (cwd=tmp_path, nie
# katalog EXE) musi zapisac plik OBOK SIEBIE i zostawic go po zakonczeniu. To
# jedyny dowod, ze launcher kotwiczy cwd w trwalym katalogu EXE, a nie w
# tymczasowym `_MEIPASS`, ktory znika razem z zapisem.


def test_aliased_open_write_persists_next_to_exe(tmp_path, shared_state):
    """Zapis przez alias `open` wymykal sie heurystyce, dostawal ONEFILE i ginal
    w `_MEIPASS`. Zalecany tryb to teraz ONEDIR, a zapis zostaje."""
    root = _project(
        tmp_path,
        "alias-zapis",
        {"main.py": "zapis = open\nzapis('wynik.txt', 'w', encoding='utf-8').write('ALIAS')\n"},
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    run_bounded([exe], timeout=120, cwd=tmp_path)
    assert (exe.parent / "wynik.txt").read_text(encoding="utf-8") == "ALIAS"


def test_pathlib_open_write_persists_next_to_exe(tmp_path, shared_state):
    """`Path(...).open('w')` — inny wzorzec zapisu, ta sama obietnica."""
    root = _project(
        tmp_path,
        "path-zapis",
        {
            "main.py": (
                "from pathlib import Path\n"
                "Path('wynik.txt').open('w', encoding='utf-8').write('PATH-OPEN')\n"
            )
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    run_bounded([exe], timeout=120, cwd=tmp_path)
    assert (exe.parent / "wynik.txt").read_text(encoding="utf-8") == "PATH-OPEN"


def test_pillow_save_persists_next_to_exe(tmp_path, shared_state):
    """`Image.save(...)` nie byl na liscie metod zapisu, wiec program z Pillow
    dostawal ONEFILE i tracil obraz. Plik ma powstac obok EXE i zostac."""
    root = _project(
        tmp_path,
        "pillow-zapis",
        {
            "main.py": (
                "from PIL import Image\n"
                "Image.new('RGB', (2, 2)).save('obraz.png')\n"
                "print('PILLOW-ZAPIS-OK')\n"
            )
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    run = run_bounded([exe], timeout=180, cwd=tmp_path)
    assert "PILLOW-ZAPIS-OK" in run.stdout
    saved = exe.parent / "obraz.png"
    assert saved.exists() and saved.stat().st_size > 0


def test_manual_onefile_write_persists_next_to_exe(tmp_path, shared_state):
    """Reczny wybor ONEFILE: zapis MA zostac obok EXE (launcher kotwiczy cwd w
    trwalym katalogu EXE, nie w `_MEIPASS`). Odczyt zasobow to osobne, jawne
    ograniczenie tego trybu — tutaj sprawdzamy wylacznie brak utraty danych."""
    root = _project(
        tmp_path,
        "onefile-zapis",
        {"main.py": "open('wynik.txt', 'w', encoding='utf-8').write('ONEFILE-ZAPIS')\n"},
    )
    result = run_build(
        root, noop_progress, output_mode=OutputMode.ONEFILE, dest_dir=tmp_path / "out"
    )
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    run_bounded([exe], timeout=120, cwd=tmp_path)
    assert (exe.parent / "wynik.txt").read_text(encoding="utf-8") == "ONEFILE-ZAPIS"


def test_rebuild_keeps_the_previous_version_and_its_data(tmp_path, shared_state):
    """A01 + A14 od konca: kolejny build nie nadpisuje poprzedniego EXE ani
    danych zapisanych obok niego — laduje pod kolejnym numerem."""
    root = _project(tmp_path, "ponownie", {"main.py": "print('WERSJA')\n"})
    out = tmp_path / "out"

    first = run_build(root, noop_progress, dest_dir=out)
    assert first.ok, [i.code for i in first.issues]
    # Uzytkownik zapisuje dane obok pierwszego EXE.
    (out / "moje-dane.txt").write_bytes(b"WAZNE DANE")

    second = run_build(root, noop_progress, dest_dir=out)
    assert second.ok, [i.code for i in second.issues]

    assert first.artifact.exists(), "pierwsza wersja zniknela"
    assert first.artifact != second.artifact, "druga wersja nadpisala pierwsza"
    assert (out / "moje-dane.txt").read_bytes() == b"WAZNE DANE", "dane uzytkownika zniknely"
    run = run_bounded([_exe_of(second)], timeout=120)
    assert "WERSJA" in run.stdout


def test_crashing_console_program_reports_instead_of_vanishing(tmp_path, shared_state):
    root = _project(
        tmp_path,
        "awaria",
        {
            "main.py": "raise ValueError('CELOWY-BLAD')\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=120, input="\n")
    assert "CELOWY-BLAD" in run.stderr
    assert run.returncode == 1


# --- Important I5: sciezka WINDOWED nie byla budowana ani razu ---


def _exe_of(result) -> Path:
    """ONEDIR oddaje katalog, ONEFILE plik — testy dotykaja obu."""
    artifact = result.artifact
    return next(artifact.glob("*.exe")) if artifact.is_dir() else artifact


# IMAGE_SUBSYSTEM_WINDOWS_GUI / _WINDOWS_CUI z naglowka PE.
SUBSYSTEM_GUI = 2
SUBSYSTEM_CONSOLE = 3


def _pe_subsystem(exe: Path) -> int:
    """Czy Windows otworzy dla tego pliku okno konsoli.

    Czytane z naglowka, bo uruchomienie tego nie pokaze: program tkinter
    dziala tak samo w obu wariantach, a jedyna roznica — czarne okno konsoli
    migajace laikowi przed oczami — jest niewidoczna dla `subprocess`.
    """
    raw = exe.read_bytes()
    pe = int.from_bytes(raw[0x3C:0x40], "little")
    assert raw[pe : pe + 4] == b"PE\x00\x00"
    return int.from_bytes(raw[pe + 24 + 68 : pe + 24 + 70], "little")


def test_windowed_program_builds_and_runs_without_a_console(tmp_path, shared_state):
    """Sekcja 10 specyfikacji wymienia okno tkinter w korpusie golden.

    Okno zamyka sie samo, zeby test nie zawisl; dowodem, ze petla zdarzen
    naprawde ruszyla, jest plik zapisany z `after()`, a nie samo wyjscie zera.
    """
    root = _project(
        tmp_path,
        "okno",
        {
            "main.py": (
                "import tkinter\n"
                "okno = tkinter.Tk()\n"
                "tkinter.Label(okno, text='OKNO-DZIALA').pack()\n"
                "def zamknij():\n"
                "    open('dowod.txt', 'w', encoding='utf-8').write('PETLA-ZDARZEN')\n"
                "    okno.destroy()\n"
                "okno.after(500, zamknij)\n"
                "okno.mainloop()\n"
            ),
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    run = run_bounded([exe], timeout=180, cwd=exe.parent)
    assert run.returncode == 0, run.stderr
    assert (exe.parent / "dowod.txt").read_text(encoding="utf-8") == "PETLA-ZDARZEN"
    assert _pe_subsystem(exe) == SUBSYSTEM_GUI, "laikowi mignelo czarne okno konsoli"
    _assert_source_untouched(root, {"main.py"})


def test_crashing_windowed_program_leaves_a_report_instead_of_vanishing(tmp_path, shared_state):
    """Sztandarowa obietnica projektu na sciezce GUI: program bez konsoli, ktory
    sie wywala, ma cos POKAZAC i cos ZOSTAWIC, zamiast zniknac bez sladu.

    Okno bledu blokuje sie w `mainloop`, wiec proces jest celowo ubijany po
    czasie — dowodem jest raport zapisany obok EXE, ktory launcher tworzy
    ZANIM pokaze okno.
    """
    root = _project(
        tmp_path,
        "awaria-gui",
        {
            "main.py": "import tkinter\nraise ValueError('CELOWY-BLAD-GUI')\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    # `allow_timeout`, bo okno bledu CZEKA na uzytkownika — dokladnie o to
    # chodzi. `run_bounded` ubija przy tym cale drzewo, wiec nie zostaje
    # sierota trzymajaca swoj katalog `_MEI`.
    run_bounded([exe], timeout=20, cwd=exe.parent, allow_timeout=True)

    report = exe.parent / "EXElent-blad.txt"
    assert report.exists(), "program GUI zniknal bez sladu"
    assert "CELOWY-BLAD-GUI" in report.read_text(encoding="utf-8")
    assert not is_running_name(exe.name), "test zostawil osierocony proces z otwartym oknem"


# --- Minor M10: sekcja 10 specyfikacji wymienia "konsola z input()" ---


def test_console_program_reading_input_builds_and_runs(tmp_path, shared_state):
    """Program, ktory o cos pyta — dla laika najbardziej typowy skrypt.

    ONEFILE rozpakowuje sie przez bootloader, wiec stdin przechodzi przez
    dodatkowy proces; zaden inny test golden tego nie dotyka. Tryb jest tu
    wybrany JAWNIE, bo zalecanym (domyslnym) trybem jest teraz ONEDIR (B01) —
    a to jedyny golden, ktory ma sprawdzac wlasnie sciezke jednoplikowa.
    Podsystem musi zostac konsolowy: program pytajacy o dane bez okna konsoli
    nie ma gdzie zadac pytania.
    """
    root = _project(
        tmp_path,
        "pytanie",
        {
            "main.py": (
                "imie = input('Jak masz na imie? ')\nprint('CZESC-' + imie.strip().upper())\n"
            ),
        },
    )
    result = run_build(
        root, noop_progress, output_mode=OutputMode.ONEFILE, dest_dir=tmp_path / "out"
    )
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    run = run_bounded([exe], timeout=120, input="Ala\n")
    assert run.returncode == 0, run.stderr
    assert "CZESC-ALA" in run.stdout
    assert _pe_subsystem(exe) == SUBSYSTEM_CONSOLE, "program pytajacy stracil konsole"


# --- A03: plik glowny w pakiecie i uklad src/ ---


def test_package_entry_point_runs_and_imports_a_submodule(tmp_path, shared_state):
    """Zgloszenie: `pkg/main.py` z blokiem `plan.entry.stem` dawalo launcher
    `runpy.run_module("main")`, a EXE umieralo na `ImportError: No module named
    main`. Nazwa modulu to `pkg.main`, i tak ma go uruchomic launcher. Dowodem
    jest EXE, ktore uruchomi plik glowny ORAZ zaimportowany podmodul pakietu."""
    root = _project(
        tmp_path,
        "pakiet",
        {
            "pkg/__init__.py": "",
            "pkg/main.py": "from pkg.pomocnik import WITAJ\nprint(WITAJ)\n",
            "pkg/pomocnik.py": "WITAJ = 'PAKIET-DZIALA'\n",
        },
    )
    result = run_build(
        root, noop_progress, entry=root / "pkg" / "main.py", dest_dir=tmp_path / "out"
    )
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "PAKIET-DZIALA" in run.stdout
    _assert_source_untouched(root, {"pkg", "pkg/__init__.py", "pkg/main.py", "pkg/pomocnik.py"})


def test_single_file_pulls_in_its_local_submodule(tmp_path, shared_state):
    """Tryb jednoplikowy: uzytkownik wskazuje SAM `main.py`, a ten importuje
    podmodul pakietu lezacego obok. Domkniecie importow (A03) ma wciagnac
    pkg/__init__.py i pkg/child.py do builda — inaczej EXE umiera u odbiorcy na
    `ModuleNotFoundError: No module named 'pkg'`."""
    root = _project(
        tmp_path,
        "jeden-plik",
        {
            "main.py": "from pkg.child import W\nprint(W)\n",
            "pkg/__init__.py": "",
            "pkg/child.py": "W = 'PODMODUL-DZIALA'\n",
        },
    )
    result = run_build(root / "main.py", noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "PODMODUL-DZIALA" in run.stdout


def test_src_layout_package_builds_and_runs(tmp_path, shared_state):
    """Uklad `src/`: korzeniem importow jest `src/`, wiec modul to `pkg.main`,
    a `src` musi trafic na `--paths`, inaczej PyInstaller nie znajdzie pakietu."""
    root = _project(
        tmp_path,
        "src-uklad",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/main.py": "from pkg.dane import X\nprint('SRC-OK', X)\n",
            "src/pkg/dane.py": "X = 7\n",
        },
    )
    result = run_build(
        root, noop_progress, entry=root / "src" / "pkg" / "main.py", dest_dir=tmp_path / "out"
    )
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "SRC-OK 7" in run.stdout


def test_root_dunder_main_runs_as_main_and_exits_cleanly(tmp_path, shared_state):
    """Zgloszenie: root `__main__.py` dawal build "sukces", ale EXE konczyl kodem
    1 na `ValueError: __main__.__spec__ is None` — bo w zamrozonym EXE modul
    `__main__` to launcher. Alias (B03) uruchamia program pod bezpieczna nazwa z
    run_name="__main__". Dowod: `__name__` to `__main__`, marker na stdout i
    ZAMIERZONY kod wyjscia 7 (nie 1 z awarii runpy)."""
    root = _project(
        tmp_path,
        "dunder",
        {
            "__main__.py": (
                "import sys\n"
                "assert __name__ == '__main__', __name__\n"
                "print('DUNDER-MAIN-DZIALA')\n"
                "sys.exit(7)\n"
            ),
        },
    )
    result = run_build(
        root, noop_progress, entry=root / "__main__.py", dest_dir=tmp_path / "out"
    )
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "DUNDER-MAIN-DZIALA" in run.stdout
    assert run.returncode == 7, run.stderr
    _assert_source_untouched(root, {"__main__.py"})


# --- A04: zasoby w ONEDIR czytane z katalogu obok EXE, nie z _internal ---


def test_onedir_reads_root_and_nested_resources_from_any_cwd(tmp_path, shared_state):
    """Zgloszenie: open('config.json') i open('assets/nested.json') w ONEDIR
    nie znajdowaly plikow — trafialy do `_internal`, a zasob zagniezdzony gubil
    katalog `assets/`. EXE uruchamiamy z INNEGO katalogu, zeby dowiesc, ze
    launcher ustawia cwd na katalog zasobow, a uklad wzgledny jest zachowany."""
    root = _project(
        tmp_path,
        "zasoby",
        {
            "main.py": (
                "import json\n"
                "root = json.load(open('config.json', encoding='utf-8'))['a']\n"
                "nested = json.load(open('assets/nested.json', encoding='utf-8'))['b']\n"
                "print('ZASOBY', root, nested)\n"
            ),
            "config.json": '{"a": "KORZEN"}',
            "assets/nested.json": '{"b": "ZAGNIEZDZONY"}',
        },
    )
    result = run_build(
        root, noop_progress, output_mode=OutputMode.ONEDIR, dest_dir=tmp_path / "out"
    )
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    # Uruchomienie z katalogu tymczasowego, NIE z katalogu EXE: jesli launcher
    # nie ustawi cwd, open() nie znajdzie nic.
    run = run_bounded([exe], timeout=180, cwd=tmp_path)
    assert "ZASOBY KORZEN ZAGNIEZDZONY" in run.stdout


# --- A06: konwersja TXT z podkatalogu zachowuje sciezke i importuje sie ---


def test_nested_txt_module_is_converted_in_place_and_imported(tmp_path, shared_state):
    """`pkg/pomoc.txt` ma zostac `pkg/pomoc.py` (nie `pomoc.py` w korzeniu),
    zeby `from pkg.pomoc import ...` zadzialalo w gotowym EXE."""
    root = _project(
        tmp_path,
        "txt-podkatalog",
        {
            "main.py": "from pkg.pomoc import WITAJ\nprint(WITAJ)\n",
            "pkg/__init__.py": "",
            "pkg/pomoc.txt": "WITAJ = 'TXT-Z-PAKIETU'\n",
        },
    )
    result = run_build(
        root, noop_progress, entry=root / "main.py", dest_dir=tmp_path / "out"
    )
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "TXT-Z-PAKIETU" in run.stdout
    # Katalog zrodlowy nietkniety: konwersja zyje w kopii roboczej.
    _assert_source_untouched(
        root, {"main.py", "pkg", "pkg/__init__.py", "pkg/pomoc.txt"}
    )


# --- A07: import pominiety w requirements.txt trafia do EXE mimo to ---


def test_import_missing_from_requirements_is_supplemented_and_runs(tmp_path, shared_state):
    """Manifest jest autorytatywny co do WERSJI, ale import spoza niego dopisujemy
    z widocznym sladem (A07) — i tu jest tego jedyny dowod w prawdziwym EXE.

    `requirements.txt` deklaruje `six` (zainstalowany z manifestu), a kod uzywa
    JESZCZE `idna`, ktorego w manifescie brak — kod dla laika generuje AI, ktore
    latwo pomija pakiet. Gdyby resolver zwracal wylacznie liste zadeklarowana
    (zachowanie sprzed A07), `idna` nie wszedlby do srodowiska builda i EXE
    witaloby odbiorce `ModuleNotFoundError: No module named 'idna'`. Oba pakiety
    sa bezzaleznosciowe i pure-python, wiec `six` nie wciaga `idna` bokiem —
    obecnosc `idna` w gotowym EXE moze pochodzic tylko z dopisania.

    Slad `dependency_not_declared` (WARNING, bo brak wymaganego importu lamie EXE)
    dociera z analizy przez `carried` az do `result.issues`, gdzie uzytkownik go
    widzi — punycode `bücher` -> `xn--bcher-kva` dowodzi, ze `idna` naprawde
    wykonalo swoja prace, a nie tylko sie zaimportowalo.
    """
    root = _project(
        tmp_path,
        "brakujaca-zaleznosc",
        {
            "requirements.txt": "six\n",
            "main.py": (
                "import six\n"
                "import idna\n"
                "print('BRAK-DEP-OK', six.__name__, idna.encode('bücher').decode('ascii'))\n"
            ),
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "BRAK-DEP-OK six xn--bcher-kva" in run.stdout

    # Slad dopisania jest widoczny w wyniku — i dotyczy WYLACZNIE pominietego
    # `idna`, nie zadeklarowanego `six`.
    traces = [i for i in result.issues if i.code == "dependency_not_declared"]
    assert [i.data["package"] for i in traces] == ["idna"]
    _assert_source_untouched(root, {"main.py", "requirements.txt"})


def test_poetry_dependency_installs_and_runs(tmp_path, shared_state):
    """Projekt Poetry: zaleznosc w `[tool.poetry.dependencies]` ze skladnia `^`
    ma sie zainstalowac i trafic do EXE (A07).

    Testy jednostkowe dowodza tlumaczenia `^1.16` -> `six<2.0.0,>=1.16`, ale
    tylko prawdziwy build sprawdza, ze uv taki specyfikator PRZYJMUJE i ze pakiet
    naprawde wchodzi do paczki — string poprawny dla `packaging`, lecz odrzucony
    przez uv, przewrocilby sie dopiero tutaj. `six` jest pure-python i
    bezzaleznosciowy, wiec jego obecnosc w EXE moze pochodzic tylko z odczytania
    manifestu Poetry."""
    root = _project(
        tmp_path,
        "projekt-poetry",
        {
            "pyproject.toml": (
                "[tool.poetry]\n"
                'name = "projekt-poetry"\n'
                'version = "0.1.0"\n'
                "[tool.poetry.dependencies]\n"
                'python = "^3.12"\n'
                'six = "^1.16"\n'
            ),
            "main.py": "import six\nprint('POETRY-OK', six.__name__)\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "POETRY-OK six" in run.stdout
    _assert_source_untouched(root, {"main.py", "pyproject.toml"})


def test_manually_added_hidden_import_reaches_the_exe(tmp_path, shared_state):
    """Reczne dopisanie modulu, ktorego statyczny skan nie widzi (A07).

    `main.py` laduje `pkg.plugin` przez importlib pod WYLICZONA nazwa
    (sklejona ze stringow), wiec `collect_hidden_imports` — ktory rozpoznaje
    tylko literaly — nie ma jej skad zobaczyc. Bez `--hidden-import` PyInstaller
    nie spakowalby tego submodulu i EXE padloby u odbiorcy na
    `ModuleNotFoundError: No module named 'pkg.plugin'`. Obecnosc modulu w
    gotowym EXE moze pochodzic tylko z recznego dopisania przekazanego przez
    ekran 2 do planu."""
    root = _project(
        tmp_path,
        "reczny-modul",
        {
            "main.py": (
                "import importlib\n"
                "nazwa = 'pkg.' + 'plugin'\n"  # wyliczona, nie literal
                "mod = importlib.import_module(nazwa)\n"
                "print('HIDDEN-OK', mod.WARTOSC)\n"
            ),
            "pkg/__init__.py": "",
            "pkg/plugin.py": "WARTOSC = 'MODUL-DOPISANY-RECZNIE'\n",
        },
    )
    result = run_build(
        root, noop_progress, dest_dir=tmp_path / "out", extra_modules=["pkg.plugin"]
    )
    assert result.ok, [i.code for i in result.issues]

    run = run_bounded([_exe_of(result)], timeout=180)
    assert "HIDDEN-OK MODUL-DOPISANY-RECZNIE" in run.stdout
    _assert_source_untouched(root, {"main.py", "pkg", "pkg/__init__.py", "pkg/plugin.py"})
