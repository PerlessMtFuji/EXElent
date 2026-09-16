"""Fact row: confidence indicator, recommendation, and restore link.

The recommendation answers the question a user may ask later: "what did the
program choose before I changed it?" The row compares strings because that is
the only representation shared by list, text-field, and button editors.
"""

import pytest
from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton

from exelent.ui.rows import FactRow


@pytest.fixture
def combo_row(qtbot):
    combo = QComboBox()
    combo.addItem("Program w oknie (zalecane)", "windowed")
    combo.addItem("Program konsolowy", "console")
    row = FactRow("Rodzaj programu", combo)
    qtbot.addWidget(row)
    return row, combo


def test_link_is_hidden_when_nothing_is_recommended(combo_row):
    row, _combo = combo_row
    assert row.restore_visible() is False


def test_link_is_hidden_while_the_value_matches_the_recommendation(combo_row):
    row, _combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    assert row.restore_visible() is False


def test_link_appears_when_the_user_picks_something_else(combo_row):
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    assert row.restore_visible() is True


def test_link_disappears_again_when_the_value_comes_back(combo_row):
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    combo.setCurrentIndex(0)
    assert row.restore_visible() is False


def test_clicking_the_link_asks_the_screen_instead_of_setting_the_value(qtbot, combo_row):
    """The row asks the screen to set a value in an arbitrary editor.

    Doing it directly would require knowledge of QComboBox, QLineEdit, and
    QPushButton, exactly the coupling that `value_text()` deliberately avoids.
    """
    row, combo = combo_row
    row.set_recommended("Program w oknie (zalecane)")
    combo.setCurrentIndex(1)
    with qtbot.waitSignal(row.restore_requested, timeout=1000):
        row.restore_button().click()
    assert combo.currentIndex() == 1  # the row did not set anything itself


def test_button_editor_raises_type_error_on_set_recommended(qtbot):
    """An editor without change signals should raise instead of failing silently.

    QPushButton emits neither `currentIndexChanged` nor `textChanged`, so the
    row could never reveal the restore link. That is worse than rejecting it.
    """
    button = QPushButton("Choose icon")
    row = FactRow("Icon", button)
    qtbot.addWidget(row)
    with pytest.raises(TypeError, match="does not emit change signals"):
        row.set_recommended("some-recommendation")


@pytest.fixture
def line_edit_row(qtbot):
    line_edit = QLineEdit()
    line_edit.setText("default name")
    row = FactRow("Filename", line_edit)
    qtbot.addWidget(row)
    return row, line_edit


def test_line_edit_editor_tracks_text_changes(line_edit_row):
    """QLineEdit emits textChanged, so the restore link should work.

    Exercise the whole cycle: set a recommendation, change the text so the
    link appears, and restore the original so the link disappears.
    """
    row, line_edit = line_edit_row
    row.set_recommended("default name")
    assert row.restore_visible() is False

    line_edit.setText("new name")
    assert row.restore_visible() is True

    line_edit.setText("default name")
    assert row.restore_visible() is False
