"""
MlProgressDialog — minimalistic modal popup that shows per-step progress
during a Timeline LFP Threshold / Snapshots 5 Hz Band "Compare" run.

Visibility is commanded explicitly by the owning View, which maps the
ViewModel's analysis lifecycle onto three methods:

* :meth:`start` — show the popup (on ``analysis_started``); the ONLY
  path that makes the dialog visible, so data loading / patient
  switches never pop it open,
* :meth:`update_progress` — refresh the step label + bar value only
  (content; never shows or hides),
* :meth:`reset` — hide + clear (on analysis complete / error / cancel,
  and defensively on patient switch).

The dialog uses ``Qt.WindowModal`` (not application-modal) so the Qt
event loop continues processing the worker thread's queued
``progress_updated`` signals — without that, the bar would never
advance.

A ``cancel_requested`` signal is emitted when the user presses Cancel
(or hits Esc); each view wires this to its viewmodel's cancel method.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontInfo, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.components.dialog_fit import screen_limit
from src.ui.policy.tokens import TYPE_PX, Dim, TypeRole
from src.ui.theme import Theme

# Width in ems of the step text: Dim.DIALOG_W (360 px) at its 12-px font.
_WIDTH_EM = Dim.DIALOG_W / TYPE_PX[TypeRole.SMALL]


class MlProgressDialog(QDialog):
    """Shared progress popup for ML "Compare" runs."""

    cancel_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Analyzing")
        # Window-modal: blocks the parent page only, but the event loop
        # keeps running so queued worker-thread signals still arrive.
        self.setWindowModality(Qt.WindowModal)
        # Hide the system close button — Cancel is the only manual
        # dismiss path. CustomizeWindowHint + WindowTitleHint = title
        # bar with no min/max/close buttons.
        self.setWindowFlags(
            Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint
        )
        self.setStyleSheet(
            f"QDialog {{ background-color: {Theme.CARD_BG}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        self._step_label = QLabel("")
        self._step_label.setWordWrap(True)
        self._step_label.setStyleSheet(
            f"font-size: 12px; color: {Theme.NEUTRAL_DARK}; "
            "background-color: transparent;"
        )
        layout.addWidget(self._step_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: {Theme.MUTED};
            }}
            QProgressBar::chunk {{
                border-radius: 4px;
                background-color: {Theme.NEUTRAL_MID};
            }}
            """
        )
        layout.addWidget(self._progress_bar)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addStretch(1)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._cancel_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {Theme.NEUTRAL_DARK};
                color: white;
                border: none;
                padding: 6px 14px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {Theme.NEUTRAL_DARK_HOVER};
            }}
            QPushButton:disabled {{
                background-color: #d4d4d4;
                color: {Theme.NEUTRAL_LIGHT};
            }}
            """
        )
        button_row.addWidget(self._cancel_btn)
        layout.addLayout(button_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, message: str = "") -> None:
        """Show the popup for a new analysis run.

        The ONLY path that makes the dialog visible. Views call this in
        response to the ViewModel's ``analysis_started`` signal, so the
        popup appears for analysis runs and nothing else — data loading,
        patient switches, and page navigation never reach this method.
        """
        self._step_label.setText(message or "")
        self._progress_bar.setValue(0)
        self._cancel_btn.setEnabled(True)
        if not self.isVisible():
            self._fit_width()
            self.show()

    def update_progress(self, percent: int, message: str) -> None:
        """Refresh the step label + bar value. Content only.

        Visibility is owned by :meth:`start` / :meth:`reset`; this method
        never shows or hides the dialog, so a stray progress emission can
        never pop the popup open.
        """
        clamped = max(0, min(100, int(percent)))
        self._step_label.setText(message or "")
        self._progress_bar.setValue(clamped)
        self._cancel_btn.setEnabled(True)

    def reset(self) -> None:
        """Hide the dialog and clear progress state — the explicit "stop".

        Called from analysis-complete, error, and cancel paths so the
        dialog is in a clean state for the next run.
        """
        self._progress_bar.setValue(0)
        self._step_label.setText("")
        self._cancel_btn.setEnabled(True)
        if self.isVisible():
            self.hide()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fit_width(self) -> None:
        # From the step text's font, and within 90 % of the screen the
        # dialog opens on (its parent's), which may change between runs.
        self.ensurePolished()
        em = QFontInfo(self._step_label.font()).pixelSize()
        self.setFixedWidth(min(round(_WIDTH_EM * em), screen_limit(self).width()))

    def _on_cancel_clicked(self) -> None:
        # Disable the button immediately so the user gets feedback that
        # Cancel was registered. The owning view will call reset() once
        # the VM signals analysis_complete / error.
        self._cancel_btn.setEnabled(False)
        self._step_label.setText("Cancelling…")
        self.cancel_requested.emit()

    def closeEvent(self, event) -> None:
        # Window-close attempts (alt-F4, etc.) should route through the
        # Cancel button instead of dismissing the dialog with no signal.
        event.ignore()
        if self._cancel_btn.isEnabled():
            self._on_cancel_clicked()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Esc would default to QDialog.reject(); route it through Cancel
        # so the VM sees a real cancel instead of a silent dismiss.
        if event.key() == Qt.Key_Escape:
            if self._cancel_btn.isEnabled():
                self._on_cancel_clicked()
            event.accept()
            return
        super().keyPressEvent(event)
