"""
Bootstrap Statistics Service

Provides bootstrap-based confidence interval calculations for non-parametric statistics.
Particularly useful for median confidence intervals where parametric assumptions
(normality) may not hold.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-16
"""

import logging
from typing import Tuple
import numpy as np

logger = logging.getLogger(__name__)

# Constants
DEFAULT_BOOTSTRAP_ITERATIONS = 5000
BOOTSTRAP_SEED = 2025
MIN_SAMPLES_FOR_BOOTSTRAP = 3


class BootstrapStatistics:
    """
    Service for calculating bootstrap confidence intervals.

    Uses the percentile method for computing confidence intervals,
    which is non-parametric and doesn't assume normality of the data.

    This is appropriate for median confidence intervals where:
    - Data may be skewed or non-normal
    - Sample sizes are small to moderate
    - Non-parametric tests (Mann-Whitney U) are used for comparisons

    Examples
    --------
    >>> service = BootstrapStatistics(n_bootstrap=1000, random_seed=42)
    >>> data = np.array([1.2, 2.3, 3.1, 2.8, 3.9, 2.1])
    >>> median, ci_lower, ci_upper = service.calculate_median_ci(data)
    >>> print(f"Median: {median:.2f}, 95% CI: [{ci_lower:.2f}, {ci_upper:.2f}]")
    Median: 2.55, 95% CI: [1.65, 3.45]
    """

    def __init__(
        self,
        n_bootstrap: int = DEFAULT_BOOTSTRAP_ITERATIONS,
        random_seed: int = BOOTSTRAP_SEED
    ):
        """
        Initialize BootstrapStatistics service.

        Parameters
        ----------
        n_bootstrap : int
            Number of bootstrap resamples (default 5000)
            Higher values give more stable estimates but take longer
        random_seed : int
            Random seed for reproducibility (default 2025)
        """
        self.n_bootstrap = n_bootstrap
        self.rng = np.random.default_rng(seed=random_seed)
        logger.info(
            f"Initialized BootstrapStatistics: "
            f"n_bootstrap={n_bootstrap}, seed={random_seed}"
        )

    def calculate_median_ci(
        self,
        data: np.ndarray,
        confidence_level: float = 0.95
    ) -> Tuple[float, float, float]:
        """
        Calculate bootstrap confidence interval for median.

        Uses the percentile method: the CI bounds are the percentiles
        of the bootstrap distribution corresponding to the confidence level.

        Parameters
        ----------
        data : np.ndarray
            1D array of data values
        confidence_level : float
            Confidence level (default 0.95 for 95% CI)

        Returns
        -------
        tuple[float, float, float]
            (median, ci_lower, ci_upper)

        Notes
        -----
        Edge cases:
        - If data has < 3 samples, returns degenerate CI (median, median, median)
        - NaN values are ignored in median calculation
        - If all values are NaN, returns (nan, nan, nan)

        References
        ----------
        Efron, B., & Tibshirani, R. J. (1994). An Introduction to the Bootstrap.
        Chapman and Hall/CRC.
        """
        # Handle empty or all-NaN data
        valid_data = data[~np.isnan(data)]

        if len(valid_data) == 0:
            logger.warning("Cannot compute CI: all data values are NaN")
            return np.nan, np.nan, np.nan

        # Calculate median
        median = np.median(valid_data)

        # Edge case: too few samples for meaningful bootstrap
        if len(valid_data) < MIN_SAMPLES_FOR_BOOTSTRAP:
            logger.debug(
                f"Only {len(valid_data)} valid samples - returning degenerate CI"
            )
            return float(median), float(median), float(median)

        # Perform bootstrap resampling
        bootstrap_medians = self._bootstrap_resample(valid_data)

        # Calculate CI using percentile method
        ci_lower, ci_upper = self._percentile_ci(
            bootstrap_medians, confidence_level
        )

        return float(median), float(ci_lower), float(ci_upper)

    def calculate_median_ci_matrix(
        self,
        data_matrix: np.ndarray,
        confidence_level: float = 0.95
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Calculate bootstrap CIs for median across multiple columns.

        This is optimized for PSD data where each column represents
        a frequency bin and each row represents an event/sample.

        Parameters
        ----------
        data_matrix : np.ndarray
            2D array with shape (n_samples, n_features)
            For PSD: (n_events, n_frequencies)
        confidence_level : float
            Confidence level (default 0.95)

        Returns
        -------
        tuple[np.ndarray, np.ndarray, np.ndarray]
            (medians, ci_lowers, ci_uppers)
            Each array has shape (n_features,)

        Examples
        --------
        >>> # PSD data: 50 events x 100 frequencies
        >>> psd_matrix = np.random.lognormal(0, 0.5, (50, 100))
        >>> medians, ci_lower, ci_upper = service.calculate_median_ci_matrix(psd_matrix)
        >>> medians.shape
        (100,)
        """
        if data_matrix.ndim != 2:
            raise ValueError(
                f"Expected 2D array, got {data_matrix.ndim}D array"
            )

        n_samples, n_features = data_matrix.shape

        if n_samples == 0:
            logger.warning("Cannot compute CI: no samples in data matrix")
            return (
                np.array([]),
                np.array([]),
                np.array([])
            )

        # Initialize output arrays
        medians = np.zeros(n_features)
        ci_lowers = np.zeros(n_features)
        ci_uppers = np.zeros(n_features)

        # Calculate CI for each feature (frequency bin)
        for i in range(n_features):
            column_data = data_matrix[:, i]
            medians[i], ci_lowers[i], ci_uppers[i] = self.calculate_median_ci(
                column_data, confidence_level
            )

        return medians, ci_lowers, ci_uppers

    def _bootstrap_resample(self, data: np.ndarray) -> np.ndarray:
        """
        Generate bootstrap samples and calculate medians.

        Parameters
        ----------
        data : np.ndarray
            1D array of data

        Returns
        -------
        np.ndarray
            Array of bootstrap median estimates, shape (n_bootstrap,)
        """
        n = len(data)
        bootstrap_medians = np.zeros(self.n_bootstrap)

        for i in range(self.n_bootstrap):
            # Resample with replacement
            resample_indices = self.rng.integers(0, n, size=n)
            resample = data[resample_indices]
            bootstrap_medians[i] = np.median(resample)

        return bootstrap_medians

    def _percentile_ci(
        self,
        bootstrap_stats: np.ndarray,
        confidence_level: float
    ) -> Tuple[float, float]:
        """
        Calculate confidence interval using percentile method.

        Parameters
        ----------
        bootstrap_stats : np.ndarray
            Bootstrap distribution of statistic
        confidence_level : float
            Confidence level (e.g., 0.95 for 95% CI)

        Returns
        -------
        tuple[float, float]
            (ci_lower, ci_upper)

        Notes
        -----
        For a 95% CI (confidence_level=0.95):
        - Lower bound = 2.5th percentile of bootstrap distribution
        - Upper bound = 97.5th percentile of bootstrap distribution
        """
        alpha = 1 - confidence_level
        lower_percentile = (alpha / 2) * 100
        upper_percentile = (1 - alpha / 2) * 100

        ci_lower = np.percentile(bootstrap_stats, lower_percentile)
        ci_upper = np.percentile(bootstrap_stats, upper_percentile)

        return float(ci_lower), float(ci_upper)
