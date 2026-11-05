"""
EmptyStateWidget - shared empty state shown when no patient is selected.

Centered icon-in-pill, "No Patient Selected" title, and prompting description.
Used by Data Management, Timeline (Classic Stats / Machine Learning), and
Snapshots (Canonical Bands / 5 Hz Band) so the no-patient view is
identical across the app.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.ui.icons import Icons
from src.ui.policy.tokens import Dim, Space
from src.ui.theme import Theme

# Share of the height beyond Dim.EMPTY_STATE_REGULAR_H that the block moves
# down by, so on huge screens it sits in the upper area (D18).
_EXTRA_HEIGHT_SHARE = 0.15


class EmptyStateWidget(QWidget):
    """Centered "No Patient Selected" placeholder with icon, title, and prompt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(Space.X10, Space.X10, Space.X10, Space.X10)
        layout.setSpacing(16)

        icon_container = QLabel()
        icon_container.setPixmap(Icons.user_x(Theme.TEXT_MUTED).pixmap(48, 48))
        icon_container.setFixedSize(96, 96)
        icon_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_container.setStyleSheet(f"""
            QLabel {{
                background-color: {Theme.MUTED};
                border-radius: 48px;
                border: none;
            }}
        """)
        layout.addWidget(icon_container, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("No Patient Selected")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #1e293b;
                border: none;
            }
        """)
        layout.addWidget(self.title_label)

        self.description_label = QLabel(
            "Select a patient from the dropdown above to view their data."
        )
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("""
            QLabel {
                color: #64748b;
                border: none;
            }
        """)
        layout.addWidget(self.description_label)

        layout.addStretch()

        self.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border: none;
            }
        """)

    def resizeEvent(self, event):
        """Keep the block in the upper area when the page is taller than regular.

        Up to Dim.EMPTY_STATE_REGULAR_H the block sits at the top margin as it
        always has; on taller (huge-screen) pages it moves down with the extra
        height, so it is neither stranded at the top edge nor centred far below
        the patient dropdown its text points to (D18).
        """
        super().resizeEvent(event)
        extra = max(0, event.size().height() - Dim.EMPTY_STATE_REGULAR_H)
        top = min(Space.X10 + round(_EXTRA_HEIGHT_SHARE * extra), Dim.EMPTY_STATE_TOP_MAX)
        layout = self.layout()
        if layout.contentsMargins().top() != top:
            layout.setContentsMargins(Space.X10, top, Space.X10, Space.X10)
