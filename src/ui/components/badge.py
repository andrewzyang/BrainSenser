"""
Badge component for displaying labels and tags.

Provides shadcn-styled badges with different variants.
Used in upload history table to show data types.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

from PySide6.QtWidgets import QLabel, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.ui.theme import Theme


class Badge(QLabel):
    """
    Badge component for displaying labels and tags.

    Matches shadcn/ui badge component styling.

    Variants:
        - default: Primary badge (default)
        - secondary: Gray badge (most common)
        - success: Green badge
        - destructive: Red badge
        - snapshot: Blue badge (for Snapshots data type)
        - timeline: Purple badge (for Timeline data type)
        - streaming_indefinite: Green badge (for Indefinite Streaming)
        - streaming_definite: Orange badge (for Definite Streaming)

    Example:
        >>> badge = Badge("Snapshots", variant="snapshot")
        >>> badge = Badge("Timeline", variant="timeline")
        >>> badge = Badge("Stream (I)", variant="streaming_indefinite")
    """

    def __init__(
        self,
        text: str,
        variant: str = "secondary",
        parent=None
    ):
        """
        Initialize Badge.

        Args:
            text: Badge text
            variant: Badge variant (default, secondary, success, destructive)
            parent: Parent widget (optional)
        """
        super().__init__(text, parent)

        self.variant = variant
        self._setup_ui()

    def _setup_ui(self):
        """Setup the badge styling."""
        # Medium weight; the font size comes from the app stylesheet
        badge_font = QFont()
        badge_font.setWeight(QFont.Weight.Medium)
        self.setFont(badge_font)

        # Set alignment
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Apply styling based on variant
        self._apply_variant_styles()

        # Exactly as large as its text plus padding, so it never clips
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.adjustSize()

    def _apply_variant_styles(self):
        """Apply styling based on variant."""
        styles = {
            'default': {
                'bg': Theme.PRIMARY,
                'text': '#ffffff',
            },
            'secondary': {
                'bg': '#e2e8f0',  # slate-200 - better contrast than MUTED
                'text': Theme.TEXT_SECONDARY,
            },
            'success': {
                'bg': '#dcfce7',  # green-100
                'text': '#166534',  # green-800
            },
            'destructive': {
                'bg': '#fee2e2',  # red-100
                'text': '#991b1b',  # red-800
            },
            # Data type specific variants (color-coded for distinction)
            'snapshot': {
                'bg': '#3b82f6',  # blue-500 - Most important data type
                'text': '#ffffff',
            },
            'timeline': {
                'bg': '#a855f7',  # purple-500 - Continuous tracking
                'text': '#ffffff',
            },
            'streaming_indefinite': {
                'bg': '#10b981',  # emerald-500 - High-resolution waveforms
                'text': '#ffffff',
            },
            'streaming_definite': {
                'bg': '#f59e0b',  # amber-500 - High-resolution waveforms
                'text': '#ffffff',
            },
        }

        style = styles.get(self.variant, styles['secondary'])

        self.setStyleSheet(f"""
            QLabel {{
                background-color: {style['bg']};
                color: {style['text']};
                border-radius: 4px;
                padding: 2px 8px;
                border: none;
            }}
        """)

    def set_text(self, text: str):
        """
        Update badge text.

        Args:
            text: New badge text
        """
        self.setText(text)
        self.adjustSize()

    def set_variant(self, variant: str):
        """
        Update badge variant.

        Args:
            variant: New variant (default, secondary, success, destructive)
        """
        self.variant = variant
        self._apply_variant_styles()
