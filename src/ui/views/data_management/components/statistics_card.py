"""
StatisticsCard for displaying patient statistics.

Reusable card component that displays:
- Icon (for data type)
- Title (Snapshots, Timeline, etc.)
- Original count
- Deduplicated count

Uses shadcn design system for consistent styling.
Sized by its content, at least 128 px tall as in the reference React design.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon

from src.ui.policy.tokens import Dim
from src.ui.theme import Theme

# Counts keep room for six digits, so a card's minimum width — and with it the
# data page's column count — doesn't change as the counts grow.
_COUNT_RESERVE = "999,999"


class _CountLabel(QLabel):
    """A count label never narrower than ``_COUNT_RESERVE`` in its own font."""

    def minimumSizeHint(self) -> QSize:
        # Measured as QLabel measures plain text, in a 2000-px box
        # (horizontalAdvance can come out 1 px narrower)
        reserve = self.fontMetrics().boundingRect(
            0, 0, 2000, 2000, Qt.AlignmentFlag.AlignLeft, _COUNT_RESERVE
        )
        return super().minimumSizeHint().expandedTo(QSize(reserve.width(), 0))


class StatisticsCard(QWidget):
    """
    Reusable statistics card component.

    Displays statistics for a specific data type (snapshots, timeline, etc.).
    Shows original count and deduplicated count in a clean, consistent format.

    Example:
        >>> # Create card for snapshots
        >>> card = StatisticsCard(title="Snapshots")
        >>> card.set_values(156, 142)
    """

    def __init__(
        self,
        title: str,
        icon: Optional[QIcon] = None,
        original_count: int = 0,
        deduplicated_count: int = 0,
        parent=None
    ):
        """
        Initialize StatisticsCard.

        Args:
            title: Card title (e.g., "Snapshots")
            icon: QtAwesome icon for the card type
            original_count: Original record count before deduplication
            deduplicated_count: Final record count after deduplication
            parent: Parent widget (optional)
        """
        super().__init__(parent)

        self.title = title
        self.icon = icon
        self._original_count = original_count
        self._deduplicated_count = deduplicated_count

        self._setup_ui()
        self._apply_styles()
        self._update_display()

    def _setup_ui(self):
        """Setup the UI layout and widgets."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)  # p-6 = 24px
        layout.setSpacing(0)

        # Header: Icon + Title (horizontal layout)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)  # gap-3 = 12px

        # Icon container (muted background box)
        if self.icon:
            icon_container = QLabel()
            icon_container.setPixmap(self.icon.pixmap(16, 16))  # h-4 w-4 = 16px
            icon_container.setFixedSize(32, 32)  # p-2 (8px) + icon (16px) = 32px
            icon_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_container.setStyleSheet(f"""
                QLabel {{
                    background-color: {Theme.MUTED};
                    border-radius: {Theme.RADIUS_MD};
                    border: none;
                }}
            """)
            header_layout.addWidget(icon_container)

        # Title (text-sm = 14px, font-medium). Word-wraps to a second line when
        # the card is too narrow for one line (e.g. "Indefinite Streaming" →
        # "Indefinite" / "Streaming") instead of being cut off. Takes the row
        # stretch so it uses the full width after the icon before it wraps.
        self.title_label = QLabel(self.title)
        title_font = QFont()
        title_font.setWeight(QFont.Weight.Medium)
        self.title_label.setFont(title_font)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header_layout.addWidget(self.title_label, stretch=1)

        layout.addLayout(header_layout)

        # Add flexible spacer to push counts to bottom
        layout.addStretch()

        # Counts container (text-xs = 12px, space-y-1 = 4px)
        counts_container = QVBoxLayout()
        counts_container.setSpacing(4)  # space-y-1 = 4px

        # Original count row
        original_row = QHBoxLayout()
        original_row.setSpacing(4)
        self.original_label_text = QLabel("Original:")

        self.original_count_label = _CountLabel()
        original_count_font = QFont()
        original_count_font.setWeight(QFont.Weight.Medium)
        self.original_count_label.setFont(original_count_font)

        original_row.addWidget(self.original_label_text)
        original_row.addWidget(self.original_count_label)
        counts_container.addLayout(original_row)

        # Deduplicated count row
        dedup_row = QHBoxLayout()
        dedup_row.setSpacing(4)
        self.dedup_label_text = QLabel("Deduplicated:")

        self.dedup_count_label = _CountLabel()
        dedup_count_font = QFont()
        dedup_count_font.setWeight(QFont.Weight.Medium)
        self.dedup_count_label.setFont(dedup_count_font)

        dedup_row.addWidget(self.dedup_label_text)
        dedup_row.addWidget(self.dedup_count_label)
        counts_container.addLayout(dedup_row)

        layout.addLayout(counts_container)

        # Sized by its content, never below the reference height (h-32 = 128px).
        # Its minimum width is what the content needs (counts included), so the
        # data page puts fewer cards in a row rather than clip one.
        self.setMinimumHeight(Dim.STAT_CARD_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def _apply_styles(self):
        """Apply styling using Theme constants."""
        self.setStyleSheet("""
            StatisticsCard {
                background-color: #ffffff;
                border: none;
            }
        """)

        # Apply text colors using Theme
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_PRIMARY};
                border: none;
                background: transparent;
            }}
        """)

        # Count labels use muted color (text-xs text-muted-foreground)
        self.original_label_text.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_MUTED};
                border: none;
                background: transparent;
            }}
        """)

        self.original_count_label.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_MUTED};
                border: none;
                background: transparent;
            }}
        """)

        self.dedup_label_text.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_MUTED};
                border: none;
                background: transparent;
            }}
        """)

        self.dedup_count_label.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_MUTED};
                border: none;
                background: transparent;
            }}
        """)

    def set_values(self, original_count: int, deduplicated_count: int) -> None:
        """
        Update the displayed values.

        Args:
            original_count: Original record count before deduplication
            deduplicated_count: Final record count after deduplication

        Example:
            >>> card.set_values(1500, 1200)
        """
        self._original_count = original_count
        self._deduplicated_count = deduplicated_count
        self._update_display()

    def _update_display(self):
        """Update the labels with current values."""
        # Original count (with thousands separator for readability)
        self.original_count_label.setText(f"{self._original_count:,}")

        # Deduplicated count (with thousands separator for readability)
        self.dedup_count_label.setText(f"{self._deduplicated_count:,}")

    def get_original_count(self) -> int:
        """Get the original count value."""
        return self._original_count

    def get_deduplicated_count(self) -> int:
        """Get the deduplicated count value."""
        return self._deduplicated_count
