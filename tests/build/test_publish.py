"""A01: publikowanie gotowego artefaktu nigdy nie niszczy poprzedniej wersji
ani danych, ktore uzytkownik zapisal w katalogu wczesniejszego builda."""

from __future__ import annotations

import errno
from pathlib import Path

from exelent.build import publish as publish_module
from exelent.build.publish import publish_artifact


def _make_onefile(dist: Path, name: str = "Program", content: bytes = b"new-exe") -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    exe = dist / f"{name}.exe"
    exe.write_bytes(content)
    return exe


def _make_onedir(dist: Path, name: str = "Program") -> Path:
    root = dist / name
    (root / "_internal").mkdir(parents=True, exist_ok=True)
    (root / f"{name}.exe").write_bytes(b"new-onedir")
    (root / "_internal" / "lib.pyd").write_bytes(b"payload")
    return root


def test_onefile_to_empty_dest_keeps_the_plain_name(tmp_path):
    source = _make_onefile(tmp_path / "dist")
    dest = tmp_path / "out"

    final, issues = publish_artifact(source, dest, "Program", is_onedir=False)

    assert issues == ()
    assert final == dest / "Program.exe"
    assert final.read_bytes() == b"new-exe"


def test_onedir_to_empty_dest_keeps_the_plain_name(tmp_path):
    source = _make_onedir(tmp_path / "dist")
    dest = tmp_path / "out"

    final, issues = publish_artifact(source, dest, "Program", is_onedir=True)

    assert issues == ()
    assert final == dest / "Program"
    assert (final / "Program.exe").read_bytes() == b"new-onedir"
    assert (final / "_internal" / "lib.pyd").read_bytes() == b"payload"


def test_existing_onefile_is_never_overwritten(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    old = dest / "Program.exe"
    old.write_bytes(b"OLD-VERSION-KEEP-ME")

    source = _make_onefile(tmp_path / "dist")
    final, issues = publish_artifact(source, dest, "Program", is_onedir=False)

    assert issues == ()
    assert final == dest / "Program (2).exe"
    assert final.read_bytes() == b"new-exe"
    # Poprzednia wersja bajtowo nietknieta.
    assert old.read_bytes() == b"OLD-VERSION-KEEP-ME"


def test_existing_onedir_user_data_survives_a_rebuild(tmp_path):
    dest = tmp_path / "out"
    prev = dest / "Program"
    prev.mkdir(parents=True)
    (prev / "Program.exe").write_bytes(b"old-onedir")
    db = prev / "user-database.db"
    db.write_bytes(b"\x00\x01USER DATA\x02\x03")
    db_bytes = db.read_bytes()

    source = _make_onedir(tmp_path / "dist")
    final, issues = publish_artifact(source, dest, "Program", is_onedir=True)

    assert issues == ()
    assert final == dest / "Program (2)"
    # Baza danych poprzedniej wersji bajtowo identyczna.
    assert db.read_bytes() == db_bytes
    # Nowy build nie wsiakl w stary katalog.
    assert not (prev / "_internal").exists()


def test_third_build_bumps_to_number_three(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "Program.exe").write_bytes(b"v1")
    (dest / "Program (2).exe").write_bytes(b"v2")

    source = _make_onefile(tmp_path / "dist")
    final, issues = publish_artifact(source, dest, "Program", is_onedir=False)

    assert issues == ()
    assert final == dest / "Program (3).exe"


def test_no_staging_leftovers_after_success(tmp_path):
    source = _make_onefile(tmp_path / "dist")
    dest = tmp_path / "out"

    publish_artifact(source, dest, "Program", is_onedir=False)

    leftovers = [p for p in dest.iterdir() if p.name.startswith(".exelent")]
    assert leftovers == []


def test_copy_failure_preserves_previous_artifact_and_reports(tmp_path, monkeypatch):
    dest = tmp_path / "out"
    dest.mkdir(parents=True)
    prev = dest / "Program.exe"
    prev.write_bytes(b"PRECIOUS")

    source = _make_onefile(tmp_path / "dist")

    def _boom(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(publish_module.shutil, "copy2", _boom)

    final, issues = publish_artifact(source, dest, "Program", is_onedir=False)

    assert final is None
    assert any(i.code == "disk_full" for i in issues)
    # Poprzedni artefakt nietkniety, brak niedokonczonego smiecia.
    assert prev.read_bytes() == b"PRECIOUS"
    leftovers = [p for p in dest.iterdir() if p.name.startswith(".exelent")]
    assert leftovers == []


def test_incomplete_copy_is_rejected(tmp_path, monkeypatch):
    source = _make_onedir(tmp_path / "dist")
    dest = tmp_path / "out"

    # Kopia "udaje sie", ale zostawia niekompletny katalog: brak pliku EXE.
    real_copytree = publish_module.shutil.copytree

    def _partial(src, dst, *args, **kwargs):
        result = real_copytree(src, dst, *args, **kwargs)
        (Path(dst) / "Program.exe").unlink()
        return result

    monkeypatch.setattr(publish_module.shutil, "copytree", _partial)

    final, issues = publish_artifact(source, dest, "Program", is_onedir=True)

    assert final is None
    assert issues != ()
    leftovers = [p for p in dest.iterdir() if p.name.startswith(".exelent")]
    assert leftovers == []
