"""Screen 1: the source path drop area.

This screen is the sole entry into the program. The tests cover which inputs
count as a selection, which do not, and whether the choice can be repeated with
one click next time.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QDialog, QFileDialog, QPushButton

from exelent.i18n import CATALOGS, current_language
from exelent.ui import recent, screen_drop, theme
from exelent.ui.screen_drop import DropScreen


@pytest.fixture
def screen(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    widget = DropScreen()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def mime():
    """Create `QMimeData` while retaining references until the test ends.

    Otherwise the object dies with the helper frame and `event.mimeData()`
    points into freed memory. PySide then returns a bare `QObject`, and pytest
    can hit an access violation while rendering the traceback. This fixture
    manages test-object lifetime rather than screen behavior.
    """
    kept = []

    def make(*paths, urls=None, text=None):
        data = QMimeData()
        if text is not None:
            data.setText(text)
        else:
            data.setUrls(
                list(urls) if urls is not None else [QUrl.fromLocalFile(str(p)) for p in paths]
            )
        kept.append(data)
        return data

    yield make
    kept.clear()


def _drop(data):
    return QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _drag_enter(data):
    return QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _recent_buttons(screen):
    widgets = (screen.recent_row.itemAt(i).widget() for i in range(screen.recent_row.count()))
    return [w for w in widgets if isinstance(w, QPushButton)]


# --- text ---


def test_the_screen_shows_sentences_not_key_names(screen):
    """Guard against raw translation keys on the initial user-facing screen."""
    catalog = CATALOGS[current_language()]
    shown = (screen.headline.text(), screen.browse.text(), screen.recent_label.text())
    assert [text for text in shown if text not in catalog.values()] == []


# --- rendering ---


def test_the_drop_zone_is_one_continuous_surface(screen):
    """Labels can inherit the opaque `bg` from the `QWidget` rule.

    The headline and arrow then cut dark rectangles into the lighter zone.
    Only rendering reveals it because the stylesheet string itself is valid.
    Pixel sampling requires no window-background pixels inside the zone; the
    broken version had 3,624 at every fourth point.
    """
    screen.setStyleSheet(theme.build_stylesheet(dark=True))
    screen.resize(900, 620)
    screen.layout().activate()
    pixmap = screen.zone.grab()
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    inset = int(12 * ratio)
    bg = QColor(theme.PALETTE_DARK["bg"]).rgb()
    holes = sum(
        image.pixel(x, y) == bg
        for y in range(inset, image.height() - inset, 4)
        for x in range(inset, image.width() - inset, 4)
    )
    assert holes == 0, f"labels paint their own background: {holes} window-color pixels"


# --- accepted selections ---


def test_the_screen_accepts_drops_at_all(screen):
    """Direct `dropEvent` calls bypass Qt's gate.

    Without `setAcceptDrops(True)`, Qt sends the screen no drag events even
    though direct-call tests remain green.
    """
    assert screen.acceptDrops() is True


def test_dropping_folder_emits_signal(screen, qtbot, mime, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.dropEvent(_drop(mime(project)))
    assert blocker.args == [project]


def test_dropping_a_file_selects_the_file_not_its_folder(screen, qtbot, mime, tmp_path):
    """Dropping one file selects that file rather than its parent directory."""
    script = tmp_path / "test.txt"
    script.write_text("print('x')\n", encoding="utf-8")
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.dropEvent(_drop(mime(script)))
    assert blocker.args == [script]


def test_a_handled_drop_is_accepted(screen, mime, tmp_path):
    """Without `acceptProposedAction`, the source app displays a rejection cursor."""
    event = _drop(mime(tmp_path))
    screen.dropEvent(event)
    assert event.isAccepted()


# --- rejected selections ---


def test_dropping_a_link_from_a_browser_chooses_nothing(screen, qtbot, mime):
    """A web URL maps to an empty local path whose parent is the current directory.

    The guard prevents dragging a link from analyzing the program's cwd.
    """
    data = mime(urls=[QUrl("https://example.com/code.zip")])
    with qtbot.assertNotEmitted(screen.folder_chosen):
        screen.dropEvent(_drop(data))


def test_dropping_nothing_useful_chooses_nothing(screen, qtbot, mime):
    with qtbot.assertNotEmitted(screen.folder_chosen):
        screen.dropEvent(_drop(mime(urls=[])))


def test_dragging_plain_text_is_refused(screen, mime):
    event = _drag_enter(mime(text="this is not a folder"))
    screen.dragEnterEvent(event)
    assert screen.zone.property("active") is False
    assert not event.isAccepted()


# --- frame highlight ---


def test_drag_enter_marks_zone_active(screen, mime, tmp_path):
    event = _drag_enter(mime(tmp_path))
    screen.dragEnterEvent(event)
    assert screen.zone.property("active") is True
    assert event.isAccepted()


def test_leaving_the_zone_clears_the_highlight(screen, mime, tmp_path):
    screen.dragEnterEvent(_drag_enter(mime(tmp_path)))
    screen.dragLeaveEvent(QDragLeaveEvent())
    assert screen.zone.property("active") is False


def test_dropping_clears_the_highlight(screen, mime, tmp_path):
    screen.dragEnterEvent(_drag_enter(mime(tmp_path)))
    screen.dropEvent(_drop(mime(tmp_path)))
    assert screen.zone.property("active") is False


# --- recent list ---


def test_choosing_a_folder_remembers_it(screen, mime, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    screen.dropEvent(_drop(mime(project)))
    assert recent.load_recent() == [project]


def test_recent_list_is_shown(screen, tmp_path):
    project = tmp_path / "earlier"
    project.mkdir()
    recent.remember(project)
    screen.refresh_recent()
    assert [b.text() for b in _recent_buttons(screen)] == ["earlier"]


def test_nothing_remembered_means_no_recent_row(screen):
    screen.refresh_recent()
    assert _recent_buttons(screen) == []
    assert not screen.recent_label.isVisibleTo(screen)


def test_clicking_a_recent_entry_chooses_it(screen, qtbot, tmp_path):
    project = tmp_path / "earlier"
    project.mkdir()
    recent.remember(project)
    screen.refresh_recent()
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        _recent_buttons(screen)[0].click()
    assert blocker.args == [project]


def test_every_recent_entry_points_at_its_own_folder(screen, qtbot, tmp_path):
    """Without a default argument, the lambda closes over the changing loop variable."""
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
        recent.remember(tmp_path / name)
    screen.refresh_recent()
    first = _recent_buttons(screen)[0]
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        first.click()
    assert blocker.args == [tmp_path / first.text()]


def test_refreshing_twice_does_not_double_the_row(screen, tmp_path):
    """`refresh_recent` clears the layout before repopulating it."""
    project = tmp_path / "earlier"
    project.mkdir()
    recent.remember(project)
    screen.refresh_recent()
    screen.refresh_recent()
    assert len(_recent_buttons(screen)) == 1


# --- browse button ---


def test_browsing_chooses_the_folder_from_the_dialog(screen, qtbot, monkeypatch, tmp_path):
    project = tmp_path / "from-dialog"
    project.mkdir()
    monkeypatch.setattr(screen_drop, "choose_source", lambda *a, **k: project)
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.browse.click()
    assert blocker.args == [project]


def test_a_cancelled_dialog_chooses_nothing(screen, qtbot, monkeypatch):
    monkeypatch.setattr(screen_drop, "choose_source", lambda *a, **k: None)
    with qtbot.assertNotEmitted(screen.folder_chosen):
        screen.browse.click()


def test_colliding_recent_entries_are_told_apart(screen, tmp_path):
    """Two different files with the same name need distinct tiles."""
    nested = tmp_path / "test"
    nested.mkdir()
    (nested / "test.txt").write_text("print(1)", encoding="utf-8")
    (tmp_path / "test.txt").write_text("print(2)", encoding="utf-8")
    recent.remember(nested / "test.txt")
    recent.remember(tmp_path / "test.txt")
    screen.refresh_recent()

    labels = [b.text() for b in _recent_buttons(screen)]
    assert len(labels) == 2
    assert labels[0] != labels[1]


def test_a_recent_entry_shows_its_full_path_on_hover(screen, tmp_path):
    project = tmp_path / "earlier"
    project.mkdir()
    recent.remember(project)
    screen.refresh_recent()
    assert _recent_buttons(screen)[0].toolTip() == str(project)


def test_a_grown_label_still_chooses_the_right_path(screen, qtbot, tmp_path):
    """A longer label must retain its own path because text cannot reconstruct it."""
    nested = tmp_path / "test"
    nested.mkdir()
    (nested / "test.txt").write_text("print(1)", encoding="utf-8")
    (tmp_path / "test.txt").write_text("print(2)", encoding="utf-8")
    recent.remember(nested / "test.txt")
    recent.remember(tmp_path / "test.txt")
    screen.refresh_recent()

    first = _recent_buttons(screen)[0]
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        first.click()
    assert blocker.args == [Path(first.toolTip())]


# --- choose button ---


def test_browsing_can_choose_a_single_file(screen, qtbot, monkeypatch, tmp_path):
    """The chooser must return a requested file rather than its entire folder."""
    source = tmp_path / "code.py"
    source.write_text("print(1)", encoding="utf-8")
    monkeypatch.setattr(screen_drop, "choose_source", lambda *a, **k: source)
    with qtbot.waitSignal(screen.folder_chosen, timeout=1000) as blocker:
        screen.browse.click()
    assert blocker.args == [source]


def test_the_dialog_accepts_a_single_file(qtbot, tmp_path):
    """Qt has no "file or directory" mode, so `accept()` must allow files itself."""
    source = tmp_path / "code.py"
    source.write_text("print(1)", encoding="utf-8")
    dialog = screen_drop.SourceDialog(None, "choose")
    qtbot.addWidget(dialog)
    dialog.selectFile(str(source))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert Path(dialog.selectedFiles()[0]) == source


def test_the_dialog_still_accepts_a_folder(qtbot, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    dialog = screen_drop.SourceDialog(None, "choose")
    qtbot.addWidget(dialog)
    dialog.selectFile(str(project))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert Path(dialog.selectedFiles()[0]) == project


def test_the_dialog_shows_files_so_there_is_something_to_click(qtbot):
    """Directory mode hides files unless the nonnative dialog disables ShowDirsOnly."""
    dialog = screen_drop.SourceDialog(None, "choose")
    qtbot.addWidget(dialog)
    assert dialog.testOption(QFileDialog.Option.ShowDirsOnly) is False
    assert dialog.testOption(QFileDialog.Option.DontUseNativeDialog) is True
