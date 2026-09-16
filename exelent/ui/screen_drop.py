"""Screen 1: drop target for a folder or a single code file."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from exelent.i18n import t
from exelent.ui import recent


def _source_from(mime) -> Path | None:
    """Path represented by dropped data, or None when it is not a path.

    A file is NOT replaced by its parent directory. The previous version used
    `path.parent`, so dropping `test.txt` from Downloads selected the entire
    Downloads folder and copied it into the workspace.

    Explicitly reject anything that is not a local path (a browser link or
    selected text). Empty `toLocalFile()` becomes the current directory after
    `Path(...)`, so silent tolerance would analyze an arbitrary location.
    """
    for url in mime.urls():
        local = url.toLocalFile()
        if not local:
            continue
        return Path(local)
    return None


class SourceDialog(QFileDialog):
    """Selection dialog accepting BOTH files and directories.

    Qt has no such mode. `getExistingDirectory` accepts only a directory, so a
    user asked to select `program.txt` selected its folder and EXElent took the
    whole thing, including Downloads. `getOpenFileName` has the opposite flaw:
    it cannot select a multi-file project.

    Use directory mode (so a directory can be confirmed) with visible files,
    plus `accept()` below to admit a file. The dialog must be non-native: the
    native Windows dialog implements directory mode differently and hides files
    entirely, leaving nothing to click.
    """

    def __init__(self, parent: QWidget | None, caption: str) -> None:
        super().__init__(parent, caption)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setFileMode(QFileDialog.FileMode.Directory)
        self.setOption(QFileDialog.Option.ShowDirsOnly, False)

    def accept(self) -> None:
        selected = self.selectedFiles()
        if selected and Path(selected[0]).is_file():
            # QFileDialog.accept() in directory mode would reject the file (or
            # treat it as a directory to enter). QDialog.accept() closes the
            # dialog without that validation while preserving selectedFiles().
            QDialog.accept(self)
            return
        super().accept()


def choose_source(parent: QWidget | None, caption: str) -> Path | None:
    """Path from the selection dialog, or None when the user cancels.

    A module function rather than a screen method: this is the only place that
    actually opens the dialog, so screen tests replace it instead of launching
    a modal window.
    """
    dialog = SourceDialog(parent, caption)
    if not dialog.exec():
        return None
    selected = dialog.selectedFiles()
    return Path(selected[0]) if selected else None


class DropScreen(QWidget):
    folder_chosen = Signal(Path)
    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

        self.settings_button = QPushButton("⚙", objectName="Link")
        self.settings_button.setToolTip(t("settings_title"))
        self.settings_button.clicked.connect(self.settings_requested)

        self.zone = QFrame(objectName="DropZone")
        self.zone.setProperty("active", False)
        zone_layout = QVBoxLayout(self.zone)
        zone_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone_layout.setSpacing(14)

        arrow = QLabel("⬇", objectName="Title")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.headline = QLabel(t("drop_headline"), objectName="Title")
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browse = QPushButton(t("drop_browse"))
        self.browse.clicked.connect(self._browse)

        zone_layout.addWidget(arrow)
        zone_layout.addWidget(self.headline)
        zone_layout.addWidget(self.browse, alignment=Qt.AlignmentFlag.AlignCenter)

        self.recent_row = QHBoxLayout()
        self.recent_label = QLabel(t("drop_recent"), objectName="Muted")

        top_row = QHBoxLayout()
        top_row.addStretch(1)
        top_row.addWidget(self.settings_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 48, 48, 32)
        outer.setSpacing(20)
        outer.addLayout(top_row)
        outer.addWidget(self.zone, stretch=1)
        outer.addWidget(self.recent_label)
        outer.addLayout(self.recent_row)

        self.refresh_recent()

    def retranslate(self) -> None:
        """Rewrite text after a language change.

        Screens obtain text from `t()` in their constructors, so without this
        method the language switch would take effect only after a restart.
        """
        self.headline.setText(t("drop_headline"))
        self.browse.setText(t("drop_browse"))
        self.recent_label.setText(t("drop_recent"))
        self.settings_button.setToolTip(t("settings_title"))

    def refresh_recent(self) -> None:
        while self.recent_row.count():
            item = self.recent_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = recent.load_recent()
        self.recent_label.setVisible(bool(entries))
        # Compute labels for the WHOLE list at once: an abbreviation is unique
        # only in the context of other entries (see `recent.display_labels`).
        for path, label in zip(entries, recent.display_labels(entries), strict=True):
            button = QPushButton(label, objectName="Link")
            button.setToolTip(str(path))
            button.clicked.connect(lambda _checked=False, p=path: self._choose(p))
            self.recent_row.addWidget(button)
        self.recent_row.addStretch(1)

    def _browse(self) -> None:
        chosen = choose_source(self, t("drop_browse"))
        if chosen is not None:
            self._choose(chosen)

    def set_analyzing(self, analyzing: bool) -> None:
        """B11: loading state keeps Qt processing events and shows that analysis
        is running instead of presenting a frozen window."""
        if analyzing:
            self.headline.setText(t("drop_analyzing"))
            self.browse.setEnabled(False)
            self.setAcceptDrops(False)
        else:
            self.headline.setText(t("drop_headline"))
            self.browse.setEnabled(True)
            self.setAcceptDrops(True)

    def _choose(self, path: Path) -> None:
        recent.remember(path)
        self.folder_chosen.emit(path)

    def _set_active(self, active: bool) -> None:
        self.zone.setProperty("active", active)
        self.zone.style().unpolish(self.zone)
        self.zone.style().polish(self.zone)

    # Qt dictates the camelCase names of the three methods below; they override
    # `QWidget` rather than establish a local convention.
    def dragEnterEvent(self, event) -> None:
        if _source_from(event.mimeData()) is None:
            event.ignore()
            return
        self._set_active(True)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event) -> None:
        self._set_active(False)
        source = _source_from(event.mimeData())
        if source is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self._choose(source)
