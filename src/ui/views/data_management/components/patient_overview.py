"""
PatientOverviewWidget for displaying patient data overview.

Shows patient statistics in cards and upload history table.
Professional medical software design - clean, no emojis.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from typing import List
from PySide6.QtWidgets import QWidget, QVBoxLayout

from src.core.models import PatientStatistics, UploadedFile
from src.ui.icons import Icons
from src.ui.policy.layout import Density, HeightClass
from src.ui.policy.tokens import Space
from src.ui.widgets.equal_columns_layout import EqualColumnsLayout
from .statistics_card import StatisticsCard
from .patient_metadata_panel import PatientMetadataPanel
from .upload_history_table import UploadHistoryTable

# Margins (left, top, right, bottom) and the gap between the metadata, the cards
# and the table, by density: regular is today's; compact leaves the content room.
_MARGINS = {HeightClass.REGULAR: (Space.X8, Space.X4, Space.X8, Space.X8),
            HeightClass.COMPACT: (Space.X2, Space.X1, Space.X2, Space.X2)}
_SPACING = {HeightClass.REGULAR: Space.X5, HeightClass.COMPACT: Space.X3}


class PatientOverviewWidget(QWidget):
    """
    Patient overview widget displaying statistics and upload history.

    Components:
    - Patient title with name
    - 4 statistics cards in one row, 2 × 2 or one column (Snapshots, Timeline, Indefinite Stream, Definite Stream)
    - Upload history table
    """

    def __init__(self, parent=None):
        """
        Initialize PatientOverviewWidget.

        Args:
            parent: Parent widget (optional)
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI layout and widgets."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*_MARGINS[HeightClass.REGULAR])
        layout.setSpacing(_SPACING[HeightClass.REGULAR])

        # Patient metadata panel (NEW: displays patient and device info)
        self.metadata_panel = PatientMetadataPanel()
        layout.addWidget(self.metadata_panel)

        # Statistics cards in equal columns across the page width: one row of
        # four, two rows of two or one column — as many as fit by the cards' own
        # minimum widths, so no card is ever squeezed below its content. Card
        # titles word-wrap (see StatisticsCard).
        cards_container = QWidget()
        cards_grid = EqualColumnsLayout(
            cards_container, column_counts=(4, 2, 1),
            horizontal_spacing=Space.X6, vertical_spacing=Space.X6,
        )

        # Create 4 statistics cards with icons (matching reference design)
        self.snapshots_card = StatisticsCard(
            title="Snapshots",
            icon=Icons.camera()
        )
        cards_grid.addWidget(self.snapshots_card)

        self.timeline_card = StatisticsCard(
            title="Timeline",
            icon=Icons.clock()
        )
        cards_grid.addWidget(self.timeline_card)

        # Two-word streaming titles are explicitly stacked (one word per line)
        # so both read identically regardless of window width — "Definite" is
        # shorter than "Indefinite", so on-demand wrapping alone would stack
        # them at different widths.
        self.indefinite_stream_card = StatisticsCard(
            title="Indefinite\nStreaming",
            icon=Icons.radio()
        )
        cards_grid.addWidget(self.indefinite_stream_card)

        self.definite_stream_card = StatisticsCard(
            title="Definite\nStreaming",
            icon=Icons.zap()
        )
        cards_grid.addWidget(self.definite_stream_card)

        layout.addWidget(cards_container)

        # Upload history table — give it the stretch so it fills the remaining
        # vertical space (grows on tall windows instead of leaving dead space).
        self.upload_history_table = UploadHistoryTable()
        layout.addWidget(self.upload_history_table, stretch=1)

        # Set background to white
        self.setStyleSheet("""
            PatientOverviewWidget {
                background-color: #ffffff;
            }
        """)

    def apply_density(self, density: Density) -> None:
        """
        Tighten the margins and the gaps between sections on short windows.

        Args:
            density: The page's density
        """
        layout = self.layout()
        layout.setContentsMargins(*_MARGINS[density.height])
        if layout.spacing() != _SPACING[density.height]:
            layout.setSpacing(_SPACING[density.height])

    def update_statistics(self, statistics: PatientStatistics):
        """
        Update the statistics cards with new data.

        Args:
            statistics: PatientStatistics object
        """
        # Update Snapshots card
        self.snapshots_card.set_values(
            statistics.snapshots_original,
            statistics.snapshots_deduplicated
        )

        # Update Timeline card
        self.timeline_card.set_values(
            statistics.timeline_original,
            statistics.timeline_deduplicated
        )

        # Update Indefinite Streaming card
        self.indefinite_stream_card.set_values(
            statistics.indefinite_streaming_original,
            statistics.indefinite_streaming_deduplicated
        )

        # Update Definite Streaming card
        self.definite_stream_card.set_values(
            statistics.definite_streaming_original,
            statistics.definite_streaming_deduplicated
        )

    def update_metadata(self, metadata: dict):
        """
        Update the metadata panel with patient metadata.

        Args:
            metadata: Patient metadata dictionary
        """
        self.metadata_panel.set_metadata(metadata)

    def update_upload_history(self, uploads: List[UploadedFile]) -> None:
        """
        Update the upload history table with new data.

        Args:
            uploads: List of UploadedFile objects
        """
        self.upload_history_table.populate_uploads(uploads)

    def clear(self):
        """
        Clear the overview (reset all statistics to 0).
        """
        # Clear metadata panel
        self.metadata_panel.clear()

        # Reset all cards to 0
        self.snapshots_card.set_values(0, 0)
        self.timeline_card.set_values(0, 0)
        self.indefinite_stream_card.set_values(0, 0)
        self.definite_stream_card.set_values(0, 0)

        # Clear upload history table
        self.upload_history_table.clear_table()
