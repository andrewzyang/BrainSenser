"""
Significance Evaluation Service

Service layer for determining statistical significance display logic.
Implements business rules for when to show significance indicators.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-15
"""

import logging
from typing import Optional

from src.domain.significance_info import SignificanceInfo

logger = logging.getLogger(__name__)


class SignificanceService:
    """
    Service for evaluating statistical significance and determining indicator display.

    This service encapsulates the business logic for determining when and how
    significance indicators should be displayed based on p-values and q-values.

    Business Rules:
    1. Priority 1: If corrected q-value exists and < 0.05 → Show indicator for q-value
    2. Priority 2: If no correction (q-value is None or equals p-value) and p-value < 0.05 → Show indicator for p-value
    3. Otherwise: No indicator shown
    """

    DEFAULT_SIGNIFICANCE_THRESHOLD = 0.05

    def __init__(self, significance_threshold: float = DEFAULT_SIGNIFICANCE_THRESHOLD):
        """
        Initialize the significance service.

        Parameters
        ----------
        significance_threshold : float
            Threshold for determining significance (default: 0.05)
        """
        self._significance_threshold = significance_threshold

    def evaluate_significance(
        self,
        p_value: float,
        q_value: Optional[float] = None
    ) -> SignificanceInfo:
        """
        Evaluate statistical significance and return display information.

        Parameters
        ----------
        p_value : float
            Uncorrected p-value from statistical test
        q_value : Optional[float]
            Corrected q-value (FDR), None if no correction applied

        Returns
        -------
        SignificanceInfo
            Object containing significance state and display logic
        """
        return SignificanceInfo(
            p_value=p_value,
            q_value=q_value,
            significance_threshold=self._significance_threshold
        )

    def should_show_indicator_for_p(
        self,
        p_value: float,
        q_value: Optional[float] = None
    ) -> bool:
        """
        Determine if significance indicator should be shown for p-value.

        Parameters
        ----------
        p_value : float
            Uncorrected p-value
        q_value : Optional[float]
            Corrected q-value (if available)

        Returns
        -------
        bool
            True if indicator should be shown for p-value
        """
        sig_info = self.evaluate_significance(p_value, q_value)
        return sig_info.show_indicator_for_p

    def should_show_indicator_for_q(
        self,
        p_value: float,
        q_value: Optional[float] = None
    ) -> bool:
        """
        Determine if significance indicator should be shown for q-value.

        Parameters
        ----------
        p_value : float
            Uncorrected p-value
        q_value : Optional[float]
            Corrected q-value

        Returns
        -------
        bool
            True if indicator should be shown for q-value
        """
        sig_info = self.evaluate_significance(p_value, q_value)
        return sig_info.show_indicator_for_q

    def set_significance_threshold(self, threshold: float):
        """
        Update the significance threshold.

        Parameters
        ----------
        threshold : float
            New significance threshold (e.g., 0.05, 0.01)
        """
        if threshold <= 0 or threshold >= 1:
            raise ValueError(f"Significance threshold must be between 0 and 1, got {threshold}")

        self._significance_threshold = threshold
        logger.info(f"Significance threshold updated to {threshold}")

    @property
    def significance_threshold(self) -> float:
        """Get current significance threshold"""
        return self._significance_threshold
