"""Ustawienia sa WYGODA i nie moga byc powodem, dla ktorego program nie rusza.

Ta sama zasada rzadzi `ui/recent.py`: uszkodzony plik oddaje wartosci domyslne,
a nieudany zapis nie przerywa pracy.
"""

import json

import pytest

from exelent.settings import Settings, load_settings, save_settings


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_defaults_when_nothing_was_ever_saved():
    settings = load_settings()
    assert settings.ask_before_download is True
    assert settings.language is None


def test_roundtrip():
    save_settings(Settings(ask_before_download=False, language="en"))
    assert load_settings() == Settings(ask_before_download=False, language="en")


def test_corrupt_file_gives_defaults_instead_of_crashing(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ to nie jest json", encoding="utf-8")
    assert load_settings() == Settings()


def test_a_json_list_is_not_settings(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(["czemu nie"]), encoding="utf-8")
    assert load_settings() == Settings()


def test_unknown_keys_are_ignored_and_missing_ones_filled_in(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jakis_stary_klucz": 1, "language": "pl"}), encoding="utf-8")
    settings = load_settings()
    assert settings.language == "pl"
    assert settings.ask_before_download is True


def test_wrong_type_falls_back_to_the_default(tmp_path):
    path = tmp_path / "EXElent" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ask_before_download": "tak"}), encoding="utf-8")
    assert load_settings().ask_before_download is True


def test_failed_write_does_not_raise(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("dysk tylko do odczytu")

    monkeypatch.setattr("pathlib.Path.write_text", boom)
    save_settings(Settings(ask_before_download=False))  # nie rzuca
