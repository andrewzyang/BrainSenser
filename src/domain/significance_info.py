"""
Significance Information Model

Domain model for statistical significance state, used to determine when and how
to display significance indicators in the UI.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-15
"""

from dataclasses import dataclass
from typing import Optional
from enum import Enum


class SignificanceType(Enum):
    """Type of significance being displayed"""
    NONE = "none"  # No significance
    UNCORRECTED = "uncorrected"  # Uncorrected p-value < 0.05
    CORRECTED = "corrected"  # Corrected q-value < 0.05


@dataclass(frozen=True)
class SignificanceInfo:
    """
    Information about statistical significance for a test result.

    This model encapsulates the logic for determining which significance
    indicator should be shown based on p-values and q-values.

    Attributes
    ----------
    p_value : float
        Uncorrected p-value from statistical test
    q_value : Optional[float]
        Corrected q-value (FDR), None if no correction applied
    significance_threshold : float
        Threshold for significance (default 0.05)
    show_indicator_for_p : bool
        Whether to show indicator for significant uncorrected p-value
    show_indicator_for_q : bool
        Whether to show indicator for significant corrected q-value
    significance_type : SignificanceType
        Type of significance detected

    Priority Logic:
    1. If q-value exists and < threshold → show indicator for q-value (corrected)
    2. If no correction (q-value is None) and p-value < threshold → show indicator for p-value
    3. Otherwise → no indicator
    """

    p_value: float
    q_value: Optional[float]
    significance_threshold: float = 0.05

    @property
    def p_is_significant(self) -> bool:
        """Check if uncorrected p-value is significant"""
        return self.p_value < self.significance_threshold

    @property
    def q_is_significant(self) -> bool:
        """Check if corrected q-value is significant"""
        return self.q_value is not None and self.q_value < self.significance_threshold

    @property
    def has_correction(self) -> bool:
        """Check if multiple comparison correction was applied"""
        # If q_value equals p_value, no correction was actually applied
        if self.q_value is None:
            return False
        # Allow for small floating point differences
        return abs(self.q_value - self.p_value) > 1e-10

    @property
    def show_indicator_for_p(self) -> bool:
        """
        Determine if indicator should be shown for p-value.

        Returns True only if:
        - No correction was applied (q_value is None or equals p_value)
        - Uncorrected p-value is significant
        """
        if self.has_correction:
            # If correction was applied, don't show indicator for p-value
            return False

        return self.p_is_significant

    @property
    def show_indicator_for_q(self) -> bool:
        """
        Determine if indicator should be shown for q-value.

        Returns True only if:
        - Correction was applied (q_value exists and differs from p_value)
        - Corrected q-value is significant
        """
        if not self.has_correction:
            # If no correction, don't show indicator for q-value
            return False

        return self.q_is_significant

    @property
    def significance_type(self) -> SignificanceType:
        """Determine the type of significance"""
        if self.show_indicator_for_q:
            return SignificanceType.CORRECTED
        elif self.show_indicator_for_p:
            return SignificanceType.UNCORRECTED
        else:
            return SignificanceType.NONE

    def get_display_value_for_p(self) -> Optional[float]:
        """Get the value to display in p-value tooltip, if indicator is shown"""
        return self.p_value if self.show_indicator_for_p else None

    def get_display_value_for_q(self) -> Optional[float]:
        """Get the value to display in q-value tooltip, if indicator is shown"""
        return self.q_value if self.show_indicator_for_q else None
