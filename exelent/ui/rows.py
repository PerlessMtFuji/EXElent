"""Wiersz faktu: znacznik pewności, zdanie po ludzku, edytor obok.

Każdy wiersz ma edytor — nie ma faktu, którego użytkownik nie mógłby poprawić.
Wersja z planu dopuszczała wiersz bez edytora i trzymała na tę okazję osobną
etykietę z metodą `set_value`; ta etykieta nigdy nie trafiała do układu, gdy
edytor istniał, więc `set_value` na wierszu z edytorem po cichu nie robiła nic.
API, które milczy zamiast działać, jest gorsze od jego braku.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from exelent.i18n import t

CERTAIN = "✓"
UNCERTAIN = "?"

# Sygnaly zmiany, ktore moze miec edytor. Kolejnosc ma znaczenie: `QComboBox`
# ma `currentIndexChanged`, `QLineEdit` ma `textChanged`. Kolej prioretyzuje
# `currentIndexChanged` bo jest bardziej niezawodny.
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
        """Przepisuje napisy wiersza po zmianie języka.

        Link powrotu do rekomendacji też jest tekstem — zostawiony po polsku
        w angielskim oknie byłby dokładnie tą niespodzianką, którą przełącznik
        języka ma usuwać.
        """
        self._caption.setText(caption)
        self._restore.setText(t("review_restore"))

    def set_certain(self, certain: bool) -> None:
        """Znacznik pewności. `?` nie jest ozdobą: analiza, która nie wie,
        mówi to wprost, a zdanie z tym samym rozpoznaniem stoi w ostrzeżeniach
        ekranu — użytkownik dostaje sygnał i jego wyjaśnienie.

        Pewność jest NIEZALEŻNA od rekomendacji: mówi, czy analiza wiedziała,
        a nie czy użytkownik coś zmienił. Jeden symbol na dwa znaczenia był
        wariantem odrzuconym w specyfikacji.
        """
        self._marker.setText(CERTAIN if certain else UNCERTAIN)

    def set_recommended(self, value: str) -> None:
        """Zapamiętuje, co zaproponowała analiza. Ustalane RAZ, przy wczytaniu.

        Rekomendacja przeliczana po każdej zmianie użytkownika goniłaby jego
        wybór i nigdy nie zapaliłaby linku — czyli nie byłaby rekomendacją.
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
        # `*_args` bo Qt poda numer indeksu albo nowy tekst, zaleznie od tego,
        # ktory sygnal edytora sie podpial.
        differs = self._recommended is not None and self.value_text() != self._recommended
        self._restore.setVisible(differs)

    def recommended_text(self) -> str | None:
        return self._recommended

    def restore_visible(self) -> bool:
        """Czy link jest POKAZANY jako element wiersza.

        Świadomie nie `isVisible()`: ono mówi o widoczności NA EKRANIE i oddaje
        False dla wszystkiego, dopóki okno nie zostało pokazane — czyli w
        każdym teście. Ten sam błąd zjadł już `_toggle_advanced` i `_toggle_log`
        (patrz ich komentarze).
        """
        return not self._restore.isHidden()

    def restore_button(self) -> QPushButton:
        return self._restore

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
