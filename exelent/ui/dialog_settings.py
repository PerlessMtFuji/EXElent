"""Ustawienia programu. Dwa przełączniki — i oba mają widoczny skutek."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)

from exelent.i18n import t
from exelent.settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings_title"))

        self.ask_checkbox = QCheckBox(t("settings_ask_download"))
        self.ask_checkbox.setChecked(settings.ask_before_download)

        self.language_combo = QComboBox()
        # `None` znaczy "idz za systemem" — to zachowanie domyslne i musi dac
        # sie do niego wrocic, a nie tylko z niego wyjsc.
        self.language_combo.addItem(t("settings_language_system"), None)
        self.language_combo.addItem("Polski", "pl")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(settings.language), 0))

        form = QFormLayout()
        form.addRow(self.ask_checkbox)
        form.addRow(t("settings_language"), self.language_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def chosen(self) -> Settings:
        return Settings(
            ask_before_download=self.ask_checkbox.isChecked(),
            language=self.language_combo.currentData(),
        )
