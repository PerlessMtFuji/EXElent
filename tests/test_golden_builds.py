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

    run = run_bounded([result.artifact], timeout=120)
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

    run = run_bounded([result.artifact], timeout=120)
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

    run = run_bounded([result.artifact], timeout=120)
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

    run = run_bounded([result.artifact], timeout=180)
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

    run = run_bounded([result.artifact], timeout=300)
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

    run = run_bounded([result.artifact], timeout=120, input="\n")
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
    dodatkowy proces; zaden inny test golden tego nie dotyka. Podsystem musi
    zostac konsolowy: program pytajacy o dane bez okna konsoli nie ma gdzie
    zadac pytania.
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
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    exe = _exe_of(result)
    run = run_bounded([exe], timeout=120, input="Ala\n")
    assert run.returncode == 0, run.stderr
    assert "CZESC-ALA" in run.stdout
    assert _pe_subsystem(exe) == SUBSYSTEM_CONSOLE, "program pytajacy stracil konsole"
