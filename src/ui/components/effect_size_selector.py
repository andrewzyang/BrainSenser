"""
Effect Size Selector Widget.

Dropdown widget for selecting effect size metric.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-09
"""

from typing import List, Optional
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Signal

from src.domain.models import EffectSizeType
from src.ui.policy.tokens import Dim
from src.ui.theme import Theme
from src.ui.components.selector_combo_style import SELECTOR_COMBO_QSS


class EffectSizeSelector(QWidget):
    """
    Dropdown widget for effect size selection.

    Displays:
    - Label: "Effect Size:"
    - Dropdown with available effect size options

    Signals
    -------
    effect_size_changed : Signal(str)
        Emitted when user selects new effect size (emits effect_type.value)

    Examples
    --------
    >>> selector = EffectSizeSelector()
    >>> selector.effect_size_changed.connect(on_effect_size_changed)
    >>> selector.set_current_effect_size("rank_biserial")
    """

    # Signal emitted when user changes selection
    effect_size_changed = Signal(str)  # effect_type value

    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize EffectSizeSelector.

        Parameters
        ----------
        parent : Optional[QWidget]
            Parent widget
        """
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Create label + dropdown + info button layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Label
        label = QLabel("Effect Size:")
        label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: 11px;
                color: {Theme.TEXT_PRIMARY};
                background-color: transparent;
            }}
        """)
        layout.addWidget(label)

        # Dropdown
        self.dropdown = QComboBox()
        # Rank-biserial is added first so the combo's intrinsic default (index 0,
        # auto-selected with no transient currentIndexChanged) matches the domain
        # default (EffectSizePreference.DEFAULT_EFFECT_SIZE, which is RANK_BISERIAL).
        # Bound pages override this via their ViewModel; the order only governs
        # unbound / first-paint display. Kept as a literal order here so the widget
        # stays domain-agnostic (no import of the preference singleton).
        self.dropdown.addItem("Rank-biserial r", EffectSizeType.RANK_BISERIAL.value)
        self.dropdown.addItem("Cohen's d", EffectSizeType.COHENS_D.value)
        self.dropdown.addItem("Rosenthal's r", EffectSizeType.ROSENTHAL_R.value)

        self.dropdown.currentIndexChanged.connect(self._on_selection_changed)
        # Shared selector look (single source of truth in selector_combo_style)
        # so Effect Size, Test, and Correction render identically. Not an
        # eliding combo: its items are short, so it is never the controls-column
        # width bottleneck. Capped like every controls field so a wide column
        # doesn't stretch it.
        self.dropdown.setStyleSheet(SELECTOR_COMBO_QSS)
        self.dropdown.setMaximumWidth(Dim.FIELD_MAX_W)
        layout.addWidget(self.dropdown)

    def _on_selection_changed(self, index: int):
        """Emit signal when user changes selection."""
        if index >= 0:
            effect_type = self.dropdown.itemData(index)
            self.effect_size_changed.emit(effect_type)

    def set_current_effect_size(self, effect_type: str):
        """
        Programmatically set the selected effect size.

        Parameters
        ----------
        effect_type : str
            Effect size type value (e.g., "cohens_d")

        Examples
        --------
        >>> selector.set_current_effect_size("rank_biserial")
        """
        for i in range(self.dropdown.count()):
            if self.dropdown.itemData(i) == effect_type:
                self.dropdown.blockSignals(True)  # Prevent signal emission
                self.dropdown.setCurrentIndex(i)
                self.dropdown.blockSignals(False)
                break

    def get_current_effect_size(self) -> str:
        """
        Get currently selected effect size.

        Returns
        -------
        str
            Current effect size type value (e.g., "rank_biserial")

        Examples
        --------
        >>> current = selector.get_current_effect_size()
        >>> print(current)
        rank_biserial
        """
        return self.dropdown.currentData()

    def set_available_options(self, effect_types: List[str]):
        """
        Filter dropdown to show only specified effect sizes.

        Used to show only test-appropriate options. For example, when
        Mann-Whitney U test is selected, only show rank-biserial and
        Rosenthal's r.

        Parameters
        ----------
        effect_types : List[str]
            List of effect type values to show (e.g., ['cohens_d', 'rank_biserial'])

        Examples
        --------
        >>> # Show only non-parametric effect sizes
        >>> selector.set_available_options(['rank_biserial', 'rosenthal_r'])
        """
        # Store current selection
        current = self.dropdown.currentData()

        # Block signals to prevent unnecessary emissions
        self.dropdown.blockSignals(True)
        self.dropdown.clear()

        # All possible options — same order as _setup_ui (rank-biserial first), so
        # the setCurrentIndex(0) fallback below also lands on the default when a
        # filter drops the previously-selected effect size.
        all_options = [
            ("Rank-biserial r", EffectSizeType.RANK_BISERIAL.value),
            ("Cohen's d", EffectSizeType.COHENS_D.value),
            ("Rosenthal's r", EffectSizeType.ROSENTHAL_R.value)
        ]

        # Add only allowed options
        for label, value in all_options:
            if value in effect_types:
                self.dropdown.addItem(label, value)

        # Restore previous selection if still available
        restored = False
        for i in range(self.dropdown.count()):
            if self.dropdown.itemData(i) == current:
                self.dropdown.setCurrentIndex(i)
                restored = True
                break

        # If previous selection not available, select first option
        if not restored and self.dropdown.count() > 0:
            self.dropdown.setCurrentIndex(0)
            # Emit signal since we changed to a new effect size
            self.dropdown.blockSignals(False)
            self.effect_size_changed.emit(self.dropdown.currentData())
        else:
            self.dropdown.blockSignals(False)

    def reset_to_all_options(self):
        """
        Reset dropdown to show all effect size options.

        Examples
        --------
        >>> selector.reset_to_all_options()
        """
        all_types = [e.value for e in EffectSizeType]
        self.set_available_options(all_types)
