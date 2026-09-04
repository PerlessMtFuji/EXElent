"""Okno zgody przed pobieraniem.

Pytanie o zgode na pobranie ZERA megabajtow uczy uzytkownika klikac OK bez
czytania — dlatego to okno musi umiec sie nie pokazac.
"""

import pytest

from exelent.deps.sizes import DownloadPlan
from exelent.settings import Settings, load_settings, save_settings
from exelent.ui.dialog_download import DownloadDialog, should_ask, should_ask_offline


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_no_question_when_everything_is_cached():
    assert should_ask(DownloadPlan(would_download=0), Settings()) is False


def test_no_question_when_the_user_turned_it_off():
    plan = DownloadPlan(would_download=8, total_bytes=100 * 1024**2)
    assert should_ask(plan, Settings(ask_before_download=False)) is False


def test_question_when_there_is_something_to_download():
    plan = DownloadPlan(would_download=8, total_bytes=100 * 1024**2)
    assert should_ask(plan, Settings()) is True


def test_dialog_shows_the_real_numbers(qtbot):
    plan = DownloadPlan(
        specs=("scipy==1.18.1", "numpy==2.5.2"), would_download=2, total_bytes=48 * 1024**2
    )
    dialog = DownloadDialog(plan)
    qtbot.addWidget(dialog)
    assert "48.0 MB" in dialog.summary_label.text()
    assert "2" in dialog.summary_label.text()
    assert "scipy" in dialog.packages_label.text()


def test_dont_ask_again_persists(qtbot):
    plan = DownloadPlan(would_download=1, total_bytes=1024**2)
    dialog = DownloadDialog(plan)
    qtbot.addWidget(dialog)
    dialog.dont_ask_checkbox.setChecked(True)
    dialog.accept()
    save_settings(Settings(ask_before_download=not dialog.dont_ask_again()))
    assert load_settings().ask_before_download is False


# --- spec 9.2: preflight, ktory nie zdazyl, nie moze skasowac pytania ---


def test_an_unanswered_preflight_still_asks_using_the_table():
    """Zgloszenie 4 powstalo na WOLNYM laczu — czyli dokladnie tam, gdzie
    preflight nie zdazy. Cichy start builda bylby ta sama szkoda."""
    assert should_ask_offline(DownloadPlan(), Settings(), estimate_high_mb=115) is True


def test_a_resolved_plan_with_nothing_to_download_does_not_ask_again():
    """Niepusty `specs` znaczy, ze preflight ODPOWIEDZIAL: nic nie brakuje."""
    cached = DownloadPlan(specs=("six==1.17.0",), would_download=0)
    assert should_ask_offline(cached, Settings(), estimate_high_mb=115) is False


def test_no_offline_question_without_anything_to_estimate():
    assert should_ask_offline(DownloadPlan(), Settings(), estimate_high_mb=0) is False


def test_offline_question_respects_the_user_switch():
    settings = Settings(ask_before_download=False)
    assert should_ask_offline(DownloadPlan(), settings, estimate_high_mb=115) is False


def test_offline_dialog_says_it_is_an_estimate_not_a_measurement(qtbot):
    dialog = DownloadDialog(
        DownloadPlan(), estimate=(60, 115), estimate_packages=("scipy", "pandas")
    )
    qtbot.addWidget(dialog)
    assert "60" in dialog.summary_label.text()
    assert "115" in dialog.summary_label.text()
    assert "scipy" in dialog.packages_label.text()
