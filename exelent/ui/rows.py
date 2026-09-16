"""Fact row: confidence marker, plain-language sentence, and adjacent editor.

Every row has an editor; users can correct every fact. The planned version
allowed an editor-free row and kept a separate label with `set_value` for it.
That label never entered the layout when an editor existed, so `set_value` on
an editable row silently did nothing. An API that stays silent instead of
working is worse than no API.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from exelent.i18n import t

CERTAIN = "✓"
UNCERTAIN = "?"

# Change signals an editor may expose. Order matters: `QComboBox`
# has `currentIndexChanged`, while `QLineEdit` has `textChanged`. The order
# prioritizes `currentIndexChanged` because it is more reliable.
_CHANGE_SIGNALS = ("currentIndexChanged", "textChanged")


class FactRow(QWidget):
    restore_requested = Signal()

    def __init__(self, caption: str, editor: QWidget) -> None:
        super().__init__()
        self._marker = QLabel(CERTAIN)
        self._marker.setFixedWidth(18)
        self._caption = QLabel(caption, objectName="Muted")
        self._caption.setMinimumWidth(150)
        self._editor = editor
        self._recommended: str | None = None
        self._tracks_changes = False

        self._restore = QPushButton(t("review_restore"), objectName="Link")
        self._restore.setVisible(False)
        self._restore.clicked.connect(self.restore_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)
        layout.addWidget(self._marker)
        layout.addWidget(self._caption)
        layout.addWidget(editor, stretch=1)
        layout.addWidget(self._restore)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        for name in _CHANGE_SIGNALS:
            signal = getattr(editor, name, None)
            if signal is not None:
                signal.connect(self._sync_restore)
                self._tracks_changes = True
                break

    def retranslate(self, caption: str) -> None:
        """Rewrite row text after a language change.

        The restore-recommendation link is text too; leaving it in Polish in an
        English window would be exactly the surprise the language switch is
        supposed to remove.
        """
        self._caption.setText(caption)
        self._restore.setText(t("review_restore"))

    def set_certain(self, certain: bool) -> None:
        """Confidence marker. `?` is not decoration: uncertain analysis says so
        explicitly, while a matching sentence appears in screen warnings — the
        user gets both the signal and its explanation.

        Confidence is INDEPENDENT of recommendation: it says whether analysis
        knew, not whether the user changed something. One symbol for two
        meanings was rejected by the specification.
        """
        self._marker.setText(CERTAIN if certain else UNCERTAIN)

    def set_recommended(self, value: str) -> None:
        """Remember what analysis proposed. Set ONCE during loading.

        A recommendation recalculated after every user change would chase the
        selection and never reveal the restore link, so it would not be a
        recommendation.
        """
        if not self._tracks_changes:
            raise TypeError(
                f"Editor {self._editor.__class__.__name__} does not emit change signals. "
                "FactRow cannot track when the user changes the value, so the restore "
                "link would never appear. This is worse than no API. Do not set a "
                "recommendation on this editor."
            )
        self._recommended = value
        self._sync_restore()

    def _sync_restore(self, *_args) -> None:
        # `*_args` because Qt passes an index or new text depending on which
        # editor signal was connected.
        differs = self._recommended is not None and self.value_text() != self._recommended
        self._restore.setVisible(differs)

    def recommended_text(self) -> str | None:
        return self._recommended

    def restore_visible(self) -> bool:
        """Whether the link is SHOWN as a row element.

        Deliberately not `isVisible()`: that reports ON-SCREEN visibility and
        returns False for everything until the window is shown, including every
        test. The same bug already affected `_toggle_advanced` and `_toggle_log`
        (see their comments).
        """
        return not self._restore.isHidden()

    def restore_button(self) -> QPushButton:
        return self._restore

    def marker(self) -> str:
        return self._marker.text()

    def caption_text(self) -> str:
        return self._caption.text()

    def value_text(self) -> str:
        """The value visible in this row, whether its editor is a combo box,
        text field, or button."""
        for getter in ("currentText", "text"):
            method = getattr(self._editor, getter, None)
            if callable(method):
                return method()
        return ""
