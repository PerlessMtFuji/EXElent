"""Download consent with a real megabyte count.

The dialog does not appear when there is nothing to download. Asking permission
to download zero megabytes teaches users to click "OK" without reading, making
the prompt ineffective when it actually has something to say.
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

# Number of items named explicitly. A full list of fourteen packages is a wall
# of text nobody reads.
_NAMED = 3


def should_ask(plan: DownloadPlan, settings: Settings) -> bool:
    return (
        plan.status in {"complete", "empty"}
        and bool(plan.would_download)
        and settings.ask_before_download
    )


def should_ask_offline(plan: DownloadPlan, settings: Settings, estimate_high_mb: int) -> bool:
    """Preflight timed out or failed; ask based on the estimate table.

    Specification §9.2 requires this explicitly: after the deadline, show the
    estimate from table §7.2. Without this branch, a slow connection would
    reproduce issue 4: a build starting without consent and downloading
    hundreds of megabytes in the background.

    Empty `specs` is the only distinction between "preflight has no answer" and
    "preflight calculated that nothing must be downloaded": in the latter case
    the resolved-version list is non-empty and the question would be about zero.
    """
    unresolved_components = plan.status in {"pending", "offline", "error", "partial", "missing_uv"}
    return settings.ask_before_download and (
        (not plan.specs and estimate_high_mb > 0) or unresolved_components
    )


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
            body = (
                t("dialog_download_body_estimate", low=str(low), high=str(high))
                if high
                else t("dialog_download_body_unknown")
            )
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
