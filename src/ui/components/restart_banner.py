"""
RestartBanner - The interface-size notice under the top bar.

Shows the current display's ``ZoomState.notice`` (plan M4.3, D2), which
UiScaleViewModel decides:

- RESTART, a size chosen in this session waits for a restart: "Interface size
  changes after restart" with Restart Now and Later;
- SUGGESTION, a size is offered for this display (once per display): the
  offer, with Use and Keep buttons;
- NONE: hidden.

The banner holds no ViewModel and decides nothing: ShellActions shows the state
on it and connects its signals to UiScaleViewModel. MainLayout.add_banner
places it full width.

Author: iEEG BrainSense Development Team
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from src.ui.policy.scale import ZoomNotice, ZoomState
from src.ui.policy.tokens import Space


class RestartBanner(QFrame):
    """
    Full-width interface-size notice: a pending restart, or the D2 suggestion.

    Signals:
        restart_requested: Restart Now was clicked.
        restart_postponed: Later was clicked.
        suggestion_accepted: The suggested size was taken.
        suggestion_dismissed: The suggestion was declined (for good, on this display).
    """

    restart_requested = Signal()
    restart_postponed = Signal()
    suggestion_accepted = Signal()
    suggestion_dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("restart_banner")
        self._notice = ZoomNotice.NONE  # the notice shown, which the buttons answer

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Space.X4, Space.X2, Space.X6, Space.X2)
        layout.setSpacing(Space.X3)

        self.message = QLabel()
        self.message.setObjectName("restart_banner_message")
        self.message.setWordWrap(True)
        layout.addWidget(self.message, 1)

        # Primary: Restart Now / Use …; secondary: Later / Keep …
        self.primary_button = QPushButton()
        self.primary_button.setObjectName("restart_banner_primary")
        self.primary_button.clicked.connect(self._on_primary)
        layout.addWidget(self.primary_button)

        self.secondary_button = QPushButton()
        self.secondary_button.setProperty("variant", "outline")
        self.secondary_button.clicked.connect(self._on_secondary)
        layout.addWidget(self.secondary_button)

        self.setVisible(False)

    def show_state(self, state: ZoomState) -> None:
        """Show ``state.notice``: the restart notice, the suggestion, or nothing."""
        self._notice = state.notice
        if state.notice is ZoomNotice.RESTART:
            self.message.setText("Interface size changes after restart")
            self.primary_button.setText("Restart Now")
            self.secondary_button.setText("Later")
        elif state.notice is ZoomNotice.SUGGESTION:
            self.message.setText(f"Text on this display may be easier to read at "
                                 f"{state.suggest_percent} %.")
            self.primary_button.setText(f"Use {state.suggest_percent} %")
            self.secondary_button.setText(f"Keep {state.label}")
        self.setVisible(state.notice is not ZoomNotice.NONE)

    def _on_primary(self) -> None:
        if self._notice is ZoomNotice.RESTART:
            self.restart_requested.emit()
        elif self._notice is ZoomNotice.SUGGESTION:
            self.suggestion_accepted.emit()

    def _on_secondary(self) -> None:
        if self._notice is ZoomNotice.RESTART:
            self.restart_postponed.emit()
        elif self._notice is ZoomNotice.SUGGESTION:
            self.suggestion_dismissed.emit()
