"""Prawdziwe buildy: katalog z kodem -> plik EXE -> uruchomienie tego EXE.

To jedyny dowod, ze produkt dziala. Kazdy przypadek uruchamia powstaly
program jako podproces i sprawdza JEGO wyjscie — build, ktory "sie udal",
a produkuje EXE wywalajace sie przy starcie, jest dokladnie ta awaria,
ktorej ten projekt ma zapobiegac.
"""

import subprocess
from pathlib import Path

import pytest

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


def _assert_source_untouched(root: Path, expected: set[str]) -> None:
    actual = {p.name for p in root.iterdir()}
    assert actual == expected, f"katalog zrodlowy zmieniony: {actual ^ expected}"
    for name in FORBIDDEN_IN_SOURCE:
        assert not (root / name).exists()
    assert not list(root.glob("*.spec"))


def test_console_program_builds_and_prints(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = _project(
        tmp_path,
        "witaj",
        {
            "main.py": "print('WITAJ-SWIECIE')\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = subprocess.run(
        [str(result.artifact)], capture_output=True, text=True, timeout=120, check=False
    )
    assert "WITAJ-SWIECIE" in run.stdout
    _assert_source_untouched(root, {"main.py"})


def test_program_reading_bundled_data_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
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

    run = subprocess.run(
        [str(result.artifact)], capture_output=True, text=True, timeout=120, check=False
    )
    assert "WARTOSC-Z-PLIKU" in run.stdout


def test_txt_source_is_converted_and_built(tmp_path, monkeypatch):
    """Sztandarowa funkcja: kod w .txt, prosto z okna czatu."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
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

    run = subprocess.run(
        [str(result.artifact)], capture_output=True, text=True, timeout=120, check=False
    )
    assert "Z-PLIKU-TXT" in run.stdout


def test_program_with_third_party_dependency(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = _project(
        tmp_path,
        "obrazek",
        {
            "main.py": "from PIL import Image\nprint('PILLOW-OK', Image.new('RGB',(2,2)).size)\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = subprocess.run(
        [str(result.artifact)], capture_output=True, text=True, timeout=180, check=False
    )
    assert "PILLOW-OK" in run.stdout


def test_writing_program_gets_onedir_and_writes_next_to_exe(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
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
    subprocess.run(
        [str(exe)], capture_output=True, text=True, timeout=120, cwd=str(exe.parent), check=False
    )
    assert (exe.parent / "wynik.txt").read_text(encoding="utf-8") == "ZAPISANE"


def test_crashing_console_program_reports_instead_of_vanishing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    root = _project(
        tmp_path,
        "awaria",
        {
            "main.py": "raise ValueError('CELOWY-BLAD')\n",
        },
    )
    result = run_build(root, noop_progress, dest_dir=tmp_path / "out")
    assert result.ok, [i.code for i in result.issues]

    run = subprocess.run(
        [str(result.artifact)],
        capture_output=True,
        text=True,
        timeout=120,
        input="\n",
        check=False,
    )
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


def test_windowed_program_builds_and_runs_without_a_console(tmp_path, monkeypatch):
    """Sekcja 10 specyfikacji wymienia okno tkinter w korpusie golden.

    Okno zamyka sie samo, zeby test nie zawisl; dowodem, ze petla zdarzen
    naprawde ruszyla, jest plik zapisany z `after()`, a nie samo wyjscie zera.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
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
    run = subprocess.run(
        [str(exe)], capture_output=True, text=True, timeout=180, cwd=str(exe.parent), check=False
    )
    assert run.returncode == 0, run.stderr
    assert (exe.parent / "dowod.txt").read_text(encoding="utf-8") == "PETLA-ZDARZEN"
    assert _pe_subsystem(exe) == SUBSYSTEM_GUI, "laikowi mignelo czarne okno konsoli"
    _assert_source_untouched(root, {"main.py"})


def test_crashing_windowed_program_leaves_a_report_instead_of_vanishing(tmp_path, monkeypatch):
    """Sztandarowa obietnica projektu na sciezce GUI: program bez konsoli, ktory
    sie wywala, ma cos POKAZAC i cos ZOSTAWIC, zamiast zniknac bez sladu.

    Okno bledu blokuje sie w `mainloop`, wiec proces jest celowo ubijany po
    czasie — dowodem jest raport zapisany obok EXE, ktory launcher tworzy
    ZANIM pokaze okno.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
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
    process = subprocess.Popen(
        [str(exe)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(exe.parent)
    )
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass  # okno bledu czeka na uzytkownika — dokladnie o to chodzi
    finally:
        process.kill()
        process.wait(timeout=30)

    report = exe.parent / "EXElent-blad.txt"
    assert report.exists(), "program GUI zniknal bez sladu"
    assert "CELOWY-BLAD-GUI" in report.read_text(encoding="utf-8")
