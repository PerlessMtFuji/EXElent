"""Window shell: three-screen stack, title, theme, language and the path through the program.

Here we test what no single screen can see: that a folder chosen on screen 1
arrives as an analysis on screen 2, that the plan from screen 2 actually starts
the build, and that closing the window during a build does not leave an orphaned
process in the system.
"""

import threading
from dataclasses import replace

import pytest

from exelent.deps.sizes import DownloadPlan
from exelent.i18n import CATALOGS, set_language
from exelent.models import AppKind, BuildPlan, BuildResult, OutputMode
from exelent.runtime import Progress
from exelent.settings import Settings, save_settings
from exelent.ui import worker as worker_module
from exelent.ui.app import SCREEN_BUILD, SCREEN_DROP, SCREEN_REVIEW, MainWindow
from exelent.ui.screen_build import BuildScreen
from exelent.ui.screen_drop import DropScreen
from exelent.ui.screen_review import ReviewScreen


@pytest.fixture(autouse=True)
def _restore_language():
    """`MainWindow` sets the system language globally — without this, test order
    would determine which language the remaining tests run in."""
    yield
    set_language("pl")


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_window_has_three_screens(window):
    assert window.stack.count() == 3


def test_starts_on_first_screen(window):
    assert window.stack.currentIndex() == 0


def test_go_to_changes_screen(window):
    window.go_to(1)
    assert window.stack.currentIndex() == 1


def test_out_of_range_never_leaves_the_window_without_a_screen(window):
    """An invariant, not a branch: a stack without a current widget is a gray
    blank window. `QStackedWidget` guarantees this today, and this test is a
    tripwire in case `go_to` ever starts routing on its own — for example,
    "helpfully" clamping the index to range."""
    for index in (99, -1, -5):
        window.go_to(index)
        assert window.stack.currentIndex() == 0
        assert window.stack.currentWidget() is not None


def test_title_is_app_name(window):
    assert "EXElent" in window.windowTitle()


def test_the_window_wears_the_theme(window):
    """The theme must be APPLIED, not merely defined — without this the window
    looks like default Qt and the palette is dead code."""
    from exelent.ui.theme import PALETTE_DARK, PALETTE_LIGHT

    sheet = window.styleSheet()
    assert sheet, "okno bez arkusza stylow"
    assert PALETTE_DARK["bg"] in sheet or PALETTE_LIGHT["bg"] in sheet


def test_language_switch_emits_signal(window, qtbot):
    with qtbot.waitSignal(window.language_changed, timeout=1000) as blocker:
        window.set_language("en")
    assert blocker.args == ["en"]


def test_the_first_screen_is_the_drop_screen(window):
    assert isinstance(window.stack.widget(0), DropScreen)


def _choose_folder_and_wait(window, qtbot, folder):
    """B11: analysis is now asynchronous — we wait for the worker signal."""
    with qtbot.waitSignal(window._analysis_worker.finished, timeout=10_000):
        window.screen_drop.folder_chosen.emit(folder)


def test_choosing_a_folder_moves_to_the_second_screen(window, tmp_path, qtbot):
    """The screen signal must be CONNECTED: without this, dropping a folder
    looks like the program is unresponsive."""
    _choose_folder_and_wait(window, qtbot, tmp_path)
    assert window.stack.currentIndex() == SCREEN_REVIEW


def test_the_second_screen_is_the_review_screen(window):
    assert isinstance(window.stack.widget(SCREEN_REVIEW), ReviewScreen)


def test_choosing_a_folder_shows_its_analysis(window, tmp_path, qtbot):
    """Merely switching screens is not enough: without running the analysis the
    user gets screen 2 with the previous project or nothing."""
    (tmp_path / "main.py").write_text("print(1)", encoding="utf-8")
    _choose_folder_and_wait(window, qtbot, tmp_path)
    assert "main.py" in window.screen_review.row_entry.value_text()


def test_an_unreadable_folder_does_not_crash_the_window(window, tmp_path, qtbot):
    """The directory can disappear between the drop and the analysis. The core
    returns with a blocker then, so the window should show a message, not a traceback."""
    _choose_folder_and_wait(window, qtbot, tmp_path / "nie-ma-takiego")
    assert window.stack.currentIndex() == SCREEN_REVIEW
    assert window.screen_review.build_button.isEnabled() is False
    assert window.screen_review.warnings_label.text() != ""


def test_the_window_speaks_the_system_language_on_every_screen(qtbot, monkeypatch):
    """Screens take their strings from `t()` in the constructor, so the language
    must be set BEFORE them. Measured: with `set_language` after construction
    an English user would get a Polish screen 1 headline."""
    monkeypatch.setattr("exelent.ui.app.system_language", lambda: "en")
    window = MainWindow()
    qtbot.addWidget(window)
    english = set(CATALOGS["en"].values())
    assert window.screen_drop.headline.text() in english
    assert window.screen_review.headline.text() in english


# --- droga przez program: folder -> przeglad -> build ---


def _plan(tmp_path):
    return BuildPlan(
        root=tmp_path,
        entry=tmp_path / "main.py",
        app_kind=AppKind.CONSOLE,
        output_mode=OutputMode.ONEFILE,
        exe_name="Program",
        dest_dir=tmp_path / "out",
    )


@pytest.fixture
def fake_build(monkeypatch):
    """Fake `execute_build` that blocks until released."""
    # Tests the path through screens, not the modal download dialog. B12 now
    # checks tools even for projects without dependencies, so we disable the
    # consent explicitly just as the user can do in settings.
    save_settings(Settings(ask_before_download=False))
    zwolnij = threading.Event()
    wystartowal = threading.Event()
    stan = {"anulowany": False}

    def fake(plan, progress, cancel, **kwargs):
        wystartowal.set()
        progress(Progress(phase="analyze", fraction=0.35))
        for _ in range(1000):
            if zwolnij.is_set() or cancel.cancelled:
                break
            threading.Event().wait(0.005)
        stan["anulowany"] = cancel.cancelled
        return BuildResult(ok=False)

    monkeypatch.setattr(worker_module, "execute_build", fake)
    stan["zwolnij"] = zwolnij
    stan["wystartowal"] = wystartowal
    return stan


def test_the_third_screen_is_the_build_screen(window):
    assert isinstance(window.stack.widget(SCREEN_BUILD), BuildScreen)


def test_the_build_screen_is_not_the_owner_of_the_thread(window):
    """The screen shows progress, the window owns the thread — otherwise every
    return to screen 1 would have to know how to stop the build."""
    assert window.worker is not None
    assert window.worker.is_running() is False


def test_requesting_a_build_moves_to_the_third_screen_and_starts_it(
    window, qtbot, fake_build, tmp_path
):
    window.screen_review.build_requested.emit(_plan(tmp_path))
    assert window.stack.currentIndex() == SCREEN_BUILD
    assert fake_build["wystartowal"].wait(timeout=5)
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        fake_build["zwolnij"].set()


def test_progress_from_the_worker_reaches_the_screen(window, qtbot, fake_build, tmp_path):
    """Worker signals must be CONNECTED to the screen: without this the progress
    bar stays at zero for the entire build and the program looks frozen."""
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        window.screen_review.build_requested.emit(_plan(tmp_path))
        assert fake_build["wystartowal"].wait(timeout=5)
        fake_build["zwolnij"].set()
    assert window.screen_build.bar.value() > 0
    assert window.screen_build.summary_label.text() != ""


def test_changed_final_plan_restarts_preflight_for_its_packages(
    window, qtbot, fake_build, monkeypatch, tmp_path
):
    starts = []
    monkeypatch.setattr(window.preflight, "matches", lambda *_a: False)
    monkeypatch.setattr(window.preflight, "start", lambda packages: starts.append(tuple(packages)))
    monkeypatch.setattr(
        window.preflight,
        "plan",
        lambda **_kwargs: DownloadPlan(specs=("requests==2.0",), status="complete"),
    )
    plan = replace(_plan(tmp_path), packages=("requests",))

    window.screen_review.build_requested.emit(plan)
    assert starts == [("requests",)]
    assert fake_build["wystartowal"].wait(timeout=5)
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        fake_build["zwolnij"].set()


def test_the_stop_button_stops_the_running_build(window, qtbot, fake_build, tmp_path):
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        window.screen_review.build_requested.emit(_plan(tmp_path))
        assert fake_build["wystartowal"].wait(timeout=5)
        window.screen_build.cancel_button.click()
    assert fake_build["anulowany"] is True


def test_the_new_build_screen_does_not_show_the_previous_one(window, qtbot, fake_build, tmp_path):
    """The window calls `start` BEFORE showing the screen — otherwise the user
    briefly sees the result of the previous build."""
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        window.screen_review.build_requested.emit(_plan(tmp_path))
        fake_build["zwolnij"].set()
    poprzednie = window.screen_build.summary_label.text()
    assert poprzednie != ""

    fake_build["zwolnij"].clear()
    window.screen_review.build_requested.emit(_plan(tmp_path))
    assert window.screen_build.summary_label.text() == ""
    with qtbot.waitSignal(window.worker.finished, timeout=5000):
        fake_build["zwolnij"].set()


def test_restart_returns_to_the_first_screen(window, qtbot, tmp_path):
    window.go_to(SCREEN_BUILD)
    window.screen_build.restart_requested.emit()
    assert window.stack.currentIndex() == SCREEN_DROP


def test_restart_refreshes_the_recent_list(window, monkeypatch, tmp_path):
    """The just-built project was remembered on screen 1, but that screen last
    read the list at program start — without a refresh, the return shows the
    list without the project just used."""
    odswiezenia = []
    monkeypatch.setattr(window.screen_drop, "refresh_recent", lambda: odswiezenia.append(1))
    window.screen_build.restart_requested.emit()
    assert odswiezenia == [1]


def test_closing_the_window_stops_a_running_build(window, fake_build, tmp_path):
    """Closing the window during a build: Qt destroys a running QThread (abort),
    and the PyInstaller process remains an orphan holding files open."""
    window.screen_review.build_requested.emit(_plan(tmp_path))
    assert fake_build["wystartowal"].wait(timeout=5)
    assert window.worker.is_running() is True

    window.close()

    assert window.worker.is_running() is False
    assert fake_build["anulowany"] is True


def test_back_from_review_returns_to_the_drop_screen(qtbot, tmp_path):
    project = tmp_path / "projekt"
    project.mkdir()
    (project / "main.py").write_text("print('x')\n", encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    _choose_folder_and_wait(window, qtbot, project)
    assert window.stack.currentIndex() == SCREEN_REVIEW

    window.screen_review.back_button.click()
    assert window.stack.currentIndex() == SCREEN_DROP


def test_going_back_is_blocked_while_a_build_runs(qtbot, tmp_path, monkeypatch):
    """A second build during the first is silently rejected by `BuildWorker`
    — the user would see a progress screen that never starts."""
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window.worker, "is_running", lambda: True)
    window.go_to(SCREEN_BUILD)

    window.screen_build.back_to_review.emit()
    assert window.stack.currentIndex() == SCREEN_BUILD


def test_language_switch_repaints_the_open_screens(qtbot):
    """`language_changed` existed but nobody listened to it — the switch would
    only take effect after restarting the program."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.set_language("pl")
    polish = window.screen_drop.headline.text()

    window.set_language("en")
    assert window.screen_drop.headline.text() != polish
    assert window.screen_drop.headline.text() == CATALOGS["en"]["drop_headline"]


def test_saved_language_wins_over_the_system_at_startup(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_settings(Settings(language="en"))

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.screen_drop.headline.text() == CATALOGS["en"]["drop_headline"]


def test_closing_forces_shutdown_when_the_build_thread_will_not_stop(window, monkeypatch):
    """A thread that did not exit within the deadline gets destroyed by Qt on
    shutdown — `abort()`, and in a windowed build the process stays in the
    system (WER) along with the bootloader waiting for a child. Closing the
    window should then terminate the program HARD, instead of returning control
    to Qt with a live thread."""
    forced = []
    monkeypatch.setattr(window, "hard_exit", lambda: forced.append(1))
    monkeypatch.setattr(window.preflight, "stop", lambda: True)
    monkeypatch.setattr(window.worker, "shutdown", lambda: False)

    window.close()

    assert forced == [1]


def test_closing_forces_shutdown_when_preflight_will_not_stop(window, monkeypatch):
    forced = []
    monkeypatch.setattr(window, "hard_exit", lambda: forced.append(1))
    monkeypatch.setattr(window.preflight, "stop", lambda: False)
    monkeypatch.setattr(window.worker, "shutdown", lambda: True)

    window.close()

    assert forced == [1]


def test_closing_a_quiet_window_ends_the_program_normally(window, monkeypatch):
    """Hard exit bypasses Qt cleanup, so we use it ONLY when the normal path
    has failed."""
    forced = []
    monkeypatch.setattr(window, "hard_exit", lambda: forced.append(1))
    monkeypatch.setattr(window.preflight, "stop", lambda: True)
    monkeypatch.setattr(window.worker, "shutdown", lambda: True)

    window.close()

    assert forced == []
