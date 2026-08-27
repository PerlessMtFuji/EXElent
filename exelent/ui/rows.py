"""Wiersz faktu: znacznik pewności, zdanie po ludzku, edytor obok.

Każdy wiersz ma edytor — nie ma faktu, którego użytkownik nie mógłby poprawić.
Wersja z planu dopuszczała wiersz bez edytora i trzymała na tę okazję osobną
etykietę z metodą `set_value`; ta etykieta nigdy nie trafiała do układu, gdy
edytor istniał, więc `set_value` na wierszu z edytorem po cichu nie robiła nic.
API, które milczy zamiast działać, jest gorsze od jego braku.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

CERTAIN = "✓"
UNCERTAIN = "?"


class FactRow(QWidget):
    def __init__(self, caption: str, editor: QWidget) -> None:
        super().__init__()
        self._marker = QLabel(CERTAIN)
        self._marker.setFixedWidth(18)
        self._caption = QLabel(caption, objectName="Muted")
        self._caption.setMinimumWidth(150)
        self._editor = editor

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)
        layout.addWidget(self._marker)
        layout.addWidget(self._caption)
        layout.addWidget(editor, stretch=1)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    def set_certain(self, certain: bool) -> None:
        """Znacznik pewności. `?` nie jest ozdobą: analiza, która nie wie,
        mówi to wprost, a zdanie z tym samym rozpoznaniem stoi w ostrzeżeniach
        ekranu — użytkownik dostaje sygnał i jego wyjaśnienie."""
        self._marker.setText(CERTAIN if certain else UNCERTAIN)

    def marker(self) -> str:
        return self._marker.text()

    def caption_text(self) -> str:
        return self._caption.text()

    def value_text(self) -> str:
        """To, co w tym wierszu widać jako wartość — bez względu na to, czy
        edytorem jest lista, pole tekstowe czy przycisk."""
        for getter in ("currentText", "text"):
            method = getattr(self._editor, getter, None)
            if callable(method):
                return method()
        return ""
