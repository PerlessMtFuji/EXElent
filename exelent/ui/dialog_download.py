"""Zgoda na pobranie — z prawdziwą liczbą megabajtów.

Okno nie pojawia się, gdy nie ma czego pobierać. Pytanie o zgodę na pobranie
zera megabajtów uczy użytkownika klikać „OK" bez czytania, a wtedy przestaje
działać także wtedy, gdy naprawdę ma coś do powiedzenia.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from exelent.deps.sizes import DownloadPlan
from exelent.i18n import t
from exelent.settings import Settings
from exelent.ui.format import human_size

# Ile pozycji wymieniamy z nazwy. Pelna lista czternastu paczek to sciana
# tekstu, ktorej nikt nie czyta.
_NAMED = 3


def should_ask(plan: DownloadPlan, settings: Settings) -> bool:
    return bool(plan.would_download) and settings.ask_before_download


def should_ask_offline(plan: DownloadPlan, settings: Settings, estimate_high_mb: int) -> bool:
    """Preflight nie zdążył albo odpadł — pytamy na podstawie tabeli.

    Specyfikacja §9.2 wymaga tego wprost: po upływie limitu okno pokazuje
    szacunek z tabeli §7.2. Bez tej gałęzi wolne łącze dawałoby dokładnie to,
    przed czym broni zgłoszenie 4 — build startujący bez pytania i ściągający
    setki megabajtów w tle.

    Pusty `specs` to jedyna rzecz, która odróżnia „preflight nie ma odpowiedzi"
    od „preflight policzył i nie ma czego pobierać": w tym drugim przypadku
    lista rozwiązanych wersji jest niepusta, a pytanie byłoby o zero.
    """
    return settings.ask_before_download and not plan.specs and estimate_high_mb > 0


class DownloadDialog(QDialog):
    def __init__(
        self,
        plan: DownloadPlan,
        parent=None,
        *,
        estimate: tuple[int, int] | None = None,
        estimate_packages: Sequence[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("dialog_download_title"))

        if estimate is None:
            body = t(
                "dialog_download_body",
                count=str(plan.would_download),
                size=human_size(plan.total_bytes),
            )
            names = ", ".join(spec.split("==")[0] for spec in plan.specs[:_NAMED])
        else:
            low, high = estimate
            body = t("dialog_download_body_estimate", low=str(low), high=str(high))
            names = ", ".join(estimate_packages[:_NAMED])

        self.summary_label = QLabel(body)
        self.summary_label.setWordWrap(True)

        self.packages_label = QLabel(names, objectName="Muted")
        self.packages_label.setWordWrap(True)

        self.dont_ask_checkbox = QCheckBox(t("dialog_download_dont_ask"))

        buttons = QDialogButtonBox()
        buttons.addButton(t("dialog_download_ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(t("dialog_download_cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.packages_label)
        layout.addWidget(self.dont_ask_checkbox)
        layout.addWidget(buttons)

    def dont_ask_again(self) -> bool:
        return self.dont_ask_checkbox.isChecked()
