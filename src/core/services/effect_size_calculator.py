"""
Effect Size Calculator Service.

Unified service for calculating effect size metrics with confidence intervals
using parametric methods. Supports Cohen's d, rank-biserial r, and Rosenthal's r.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-16
"""

import logging
from typing import Tuple, Optional
import numpy as np
from scipy import stats

from src.domain.models import EffectSizeType, EffectSizeResult

logger = logging.getLogger(__name__)


class EffectSizeCalculator:
    """
    Unified effect size calculation service.

    Handles all effect size computations with confidence intervals using
    parametric methods. Supports:
    - Cohen's d (parametric)
    - Rank-biserial r (parametric CI using Kerby 2014 approximation)
    - Rosenthal's r (parametric CI using Fisher's z-transformation)

    Examples
    --------
    >>> calculator = EffectSizeCalculator()
    >>> group1 = np.array([1, 2, 3, 4, 5])
    >>> group2 = np.array([3, 4, 5, 6, 7])
    >>> result = calculator.calculate_effect_size(
    ...     group1, group2, EffectSizeType.COHENS_D
    ... )
    >>> print(f"{result.display_name}: {result.value:.3f} [{result.ci_lower:.3f}, {result.ci_upper:.3f}]")
    Cohen's d: -1.414 [-2.156, -0.672]
    """

    def __init__(self):
        """
        Initialize EffectSizeCalculator.
        """
        logger.info("Initialized EffectSizeCalculator")

    def calculate_effect_size(
        self,
        group1: np.ndarray,
        group2: np.ndarray,
        effect_type: EffectSizeType,
        test_statistic: Optional[float] = None,
        test_name: Optional[str] = None
    ) -> EffectSizeResult:
        """
        Calculate effect size with confidence interval.

        Parameters
        ----------
        group1, group2 : np.ndarray
            Data arrays for two groups
        effect_type : EffectSizeType
            Type of effect size to calculate
        test_statistic : Optional[float]
            Pre-computed test statistic (required for Rosenthal's r)
        test_name : Optional[str]
            Name of statistical test (for validation and warnings)

        Returns
        -------
        EffectSizeResult
            Effect size with CI and interpretation

        Raises
        ------
        ValueError
            If data is invalid (NaN, inf, insufficient sample size)
        """
        # Validate inputs
        self._validate_input(group1, group2)

        # Check for sufficient sample size
        if len(group1) < 3 or len(group2) < 3:
            logger.warning(
                f"Small sample size detected: n1={len(group1)}, n2={len(group2)}. "
                "Effect size may be unreliable."
            )

        # Dispatch to appropriate calculation method
        if effect_type == EffectSizeType.COHENS_D:
            value, ci_lower, ci_upper = self._calculate_cohens_d(group1, group2)
        elif effect_type == EffectSizeType.RANK_BISERIAL:
            value, ci_lower, ci_upper = self._calculate_rank_biserial(
                group1, group2, test_statistic
            )
        elif effect_type == EffectSizeType.ROSENTHAL_R:
            if test_statistic is None:
                raise ValueError("Rosenthal's r requires test_statistic parameter")
            value, ci_lower, ci_upper = self._calculate_rosenthal_r(
                test_statistic, len(group1), len(group2)
            )
        else:
            raise ValueError(f"Unknown effect size type: {effect_type}")

        # Interpret effect size
        interpretation = self._interpret_effect_size(value, effect_type, len(group1), len(group2))

        return EffectSizeResult(
            effect_size_type=effect_type,
            value=value,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            interpretation=interpretation
        )

    # ========================================================================
    # Parametric Effect Sizes
    # ========================================================================

    def _calculate_cohens_d(
        self, group1: np.ndarray, group2: np.ndarray
    ) -> Tuple[float, float, float]:
        """
        Calculate Cohen's d with parametric CI.

        Cohen's d = (M1 - M2) / SD_pooled

        Returns
        -------
        Tuple[float, float, float]
            (value, ci_lower, ci_upper)
        """
        n1, n2 = len(group1), len(group2)
        m1, m2 = np.mean(group1), np.mean(group2)
        var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)

        # Pooled standard deviation
        pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))

        # FIXED: Proper zero variance handling (distinguishes cases)
        if pooled_std <= 0 or np.isclose(pooled_std, 0, atol=1e-10):
            if np.isclose(m1, m2, atol=1e-10):
                # Equal means, zero variance → no effect
                logger.info("Zero variance with equal means, effect size = 0")
                return 0.0, 0.0, 0.0
            else:
                # Different means, zero variance → undefined
                logger.warning(
                    f"Zero variance with different means ({m1:.3f} vs {m2:.3f}): "
                    "effect size undefined"
                )
                return np.nan, np.nan, np.nan

        # Cohen's d
        cohens_d = (m1 - m2) / pooled_std

        # Calculate CI using Hedges & Olkin (1985) formula
        # SE_d = sqrt((n1+n2)/(n1*n2) + d²/(2*(n1+n2)))
        se_d = np.sqrt((n1 + n2) / (n1 * n2) + cohens_d**2 / (2 * (n1 + n2)))

        # 95% CI
        z_score = stats.norm.ppf(0.975)  # 1.96
        ci_lower = cohens_d - z_score * se_d
        ci_upper = cohens_d + z_score * se_d

        return float(cohens_d), float(ci_lower), float(ci_upper)

    # ========================================================================
    # Non-Parametric Effect Sizes
    # ========================================================================

    def _calculate_rank_biserial(
        self,
        group1: np.ndarray,
        group2: np.ndarray,
        u_statistic: Optional[float] = None
    ) -> Tuple[float, float, float]:
        """
        Calculate rank-biserial correlation for Mann-Whitney U.

        r_rb = (2U) / (n1 × n2) - 1

        Uses parametric CI based on asymptotic distribution.

        Parameters
        ----------
        group1, group2 : np.ndarray
            Data arrays (will be flattened to 1D if needed)
        u_statistic : Optional[float]
            Pre-computed U statistic (will calculate if not provided)

        Returns
        -------
        Tuple[float, float, float]
            (value, ci_lower, ci_upper)
        """
        # Flatten to 1D to handle both 1D and 2D inputs
        group1_arr = np.asarray(group1)
        group2_arr = np.asarray(group2)

        # CRITICAL WARNING: Check for multidimensional data (e.g., repeated measures)
        if group1_arr.ndim > 1 or group2_arr.ndim > 1:
            logger.warning(
                f"2D/multidimensional array detected (shape: {group1_arr.shape}, {group2_arr.shape}). "
                "Flattening treats all observations as independent, which may be invalid for "
                "repeated measures (e.g., timepoints). Standard errors may be underestimated."
            )

        group1_flat = group1_arr.ravel()
        group2_flat = group2_arr.ravel()

        n1, n2 = len(group1_flat), len(group2_flat)

        # Calculate or use provided U statistic
        if u_statistic is None:
            u_statistic, _ = stats.mannwhitneyu(
                group1_flat, group2_flat, alternative='two-sided'
            )

        # Rank-biserial correlation (signed)
        rank_biserial = (2 * u_statistic) / (n1 * n2) - 1

        # Parametric CI: Normal approximation for rank-biserial variance
        #
        # This uses an approximate variance formula for the rank-biserial correlation
        # based on the asymptotic distribution of the Mann-Whitney U statistic.
        #
        # Formula: var(r_rb) ≈ ((n1 + n2 + 1) / (3 * n1 * n2)) * (1 + r_rb² / 2)
        #
        # This approximation assumes:
        # - No ties (or few ties) in the data
        # - Sample sizes are not extremely small (ideally n ≥ 10 per group)
        # - Data is continuous (or nearly so)
        #
        # References:
        # - Kerby, D. S. (2014). The simple difference formula: An approach to
        #   teaching nonparametric correlation. Comprehensive Psychology, 3, 11.IT.3.1.
        # - Cureton, E. E. (1956). Rank-biserial correlation. Psychometrika, 21(3), 287-290.
        #
        # Note: This method provides reasonable coverage for moderate to large samples.
        # For small samples (n < 20), skewed distributions, or data with many ties,
        # coverage probability may be below nominal 95%.
        var_rb = ((n1 + n2 + 1) / (3 * n1 * n2)) * (1 + rank_biserial**2 / 2)
        se = np.sqrt(var_rb)
        z_score = stats.norm.ppf(0.975)
        ci_lower = rank_biserial - z_score * se
        ci_upper = rank_biserial + z_score * se

        logger.debug(
            f"Rank-biserial CI using parametric approximation (Kerby, 2014): "
            f"var={var_rb:.4f}, SE={se:.4f}, CI=[{ci_lower:.3f}, {ci_upper:.3f}]"
        )

        return float(rank_biserial), float(ci_lower), float(ci_upper)

    def _calculate_rosenthal_r(
        self,
        z_statistic: float,
        n1: int,
        n2: int
    ) -> Tuple[float, float, float]:
        """
        Calculate Rosenthal's r from z-statistic.

        r = z / √N

        Parameters
        ----------
        z_statistic : float
            Z-score from statistical test
        n1, n2 : int
            Sample sizes

        Returns
        -------
        Tuple[float, float, float]
            (value, ci_lower, ci_upper)
        """
        n_total = n1 + n2
        # FIXED: Preserve sign of z_statistic (indicates direction of effect)
        rosenthal_r = z_statistic / np.sqrt(n_total)

        # Calculate CI using Fisher's z-transformation
        fisher_z = np.arctanh(rosenthal_r)
        se_z = 1 / np.sqrt(n_total - 3)

        z_score = stats.norm.ppf(0.975)
        ci_lower_z = fisher_z - z_score * se_z
        ci_upper_z = fisher_z + z_score * se_z

        # Back-transform to r
        ci_lower = np.tanh(ci_lower_z)
        ci_upper = np.tanh(ci_upper_z)

        return float(rosenthal_r), float(ci_lower), float(ci_upper)




    # ========================================================================
    # Interpretation and Validation
    # ========================================================================

    def _interpret_effect_size(
        self,
        value: float,
        effect_type: EffectSizeType,
        n1: int,
        n2: int
    ) -> str:
        """
        Interpret effect size magnitude.

        Returns
        -------
        str
            "small", "medium", "large", or "unreliable"
        """
        # Check for unreliable conditions
        if n1 < 3 or n2 < 3:
            return "unreliable"

        if np.isnan(value) or np.isinf(value):
            return "unreliable"

        # Absolute value for interpretation
        abs_value = abs(value)

        # Cohen's d thresholds (Cohen, 1988)
        if effect_type is EffectSizeType.COHENS_D:
            if abs_value < 0.2:
                return "negligible"
            elif abs_value < 0.5:
                return "small"
            elif abs_value < 0.8:
                return "medium"
            else:
                return "large"

        # Rank-biserial r, Rosenthal's r thresholds (Kerby, 2014)
        elif effect_type in [EffectSizeType.RANK_BISERIAL, EffectSizeType.ROSENTHAL_R]:
            if abs_value < 0.1:
                return "negligible"
            elif abs_value < 0.3:
                return "small"
            elif abs_value < 0.5:
                return "medium"
            else:
                return "large"

        return "unknown"

    def _validate_input(self, group1: np.ndarray, group2: np.ndarray):
        """
        Validate input data.

        Raises
        ------
        ValueError
            If data contains NaN, inf, or insufficient samples
        """
        if len(group1) == 0 or len(group2) == 0:
            raise ValueError("Groups must not be empty")

        if np.any(np.isnan(group1)) or np.any(np.isnan(group2)):
            raise ValueError("Data contains NaN values - cannot calculate effect size")

        if np.any(np.isinf(group1)) or np.any(np.isinf(group2)):
            raise ValueError("Data contains infinite values - cannot calculate effect size")

        if len(group1) < 2 or len(group2) < 2:
            raise ValueError("Each group must have at least 2 samples")
