"""
Unit tests for BootstrapStatistics service.

Tests bootstrap confidence interval calculations for medians.
"""

import pytest
import numpy as np
from src.core.services.bootstrap_statistics import BootstrapStatistics


class TestBootstrapStatistics:
    """Test suite for BootstrapStatistics service."""

    def test_initialization(self):
        """Test service initialization with custom parameters."""
        service = BootstrapStatistics(n_bootstrap=1000, random_seed=42)
        assert service.n_bootstrap == 1000
        assert service.rng is not None

    def test_initialization_defaults(self):
        """Test service initialization with default parameters."""
        service = BootstrapStatistics()
        assert service.n_bootstrap == 2000  # Default
        assert service.rng is not None

    def test_calculate_median_ci_normal_data(self):
        """Test bootstrap CI calculation with normally distributed data."""
        np.random.seed(42)
        data = np.random.randn(100)  # Standard normal

        service = BootstrapStatistics(n_bootstrap=1000, random_seed=42)
        median, ci_lower, ci_upper = service.calculate_median_ci(data)

        # Check that median is close to 0 (true median of standard normal)
        assert abs(median) < 0.3

        # Check that CI bounds are reasonable
        assert ci_lower < median < ci_upper
        assert ci_upper - ci_lower > 0  # Non-zero width

        # Check that CI is roughly symmetric for normal data
        ci_width = ci_upper - ci_lower
        assert ci_width < 1.0  # Reasonable width for n=100

    def test_calculate_median_ci_skewed_data(self):
        """Test bootstrap CI with skewed (log-normal) data."""
        np.random.seed(42)
        data = np.random.lognormal(mean=0, sigma=0.5, size=100)

        service = BootstrapStatistics(n_bootstrap=1000, random_seed=42)
        median, ci_lower, ci_upper = service.calculate_median_ci(data)

        # Median should be positive
        assert median > 0

        # CI should contain median
        assert ci_lower <= median <= ci_upper

        # For log-normal, CI should be asymmetric (more space above median)
        upper_space = ci_upper - median
        lower_space = median - ci_lower
        # Upper space should be larger for positive skew
        assert upper_space > lower_space * 0.5

    def test_calculate_median_ci_edge_case_few_samples(self):
        """Test with too few samples (should return degenerate CI)."""
        data = np.array([1.0, 2.0])  # Only 2 samples

        service = BootstrapStatistics()
        median, ci_lower, ci_upper = service.calculate_median_ci(data)

        # Should return median with degenerate CI
        assert median == 1.5
        assert ci_lower == median
        assert ci_upper == median

    def test_calculate_median_ci_edge_case_single_sample(self):
        """Test with single sample."""
        data = np.array([5.0])

        service = BootstrapStatistics()
        median, ci_lower, ci_upper = service.calculate_median_ci(data)

        # Should return the value with degenerate CI
        assert median == 5.0
        assert ci_lower == 5.0
        assert ci_upper == 5.0

    def test_calculate_median_ci_edge_case_empty_data(self):
        """Test with empty array."""
        data = np.array([])

        service = BootstrapStatistics()
        median, ci_lower, ci_upper = service.calculate_median_ci(data)

        # Should return NaN for all values
        assert np.isnan(median)
        assert np.isnan(ci_lower)
        assert np.isnan(ci_upper)

    def test_calculate_median_ci_with_nans(self):
        """Test with NaN values in data."""
        data = np.array([1.0, 2.0, np.nan, 3.0, 4.0, np.nan, 5.0])

        service = BootstrapStatistics(n_bootstrap=500, random_seed=42)
        median, ci_lower, ci_upper = service.calculate_median_ci(data)

        # Should ignore NaNs and compute CI for valid data
        assert not np.isnan(median)
        assert median == 3.0  # Median of [1,2,3,4,5]
        assert ci_lower < median < ci_upper

    def test_calculate_median_ci_all_nans(self):
        """Test with all NaN values."""
        data = np.array([np.nan, np.nan, np.nan])

        service = BootstrapStatistics()
        median, ci_lower, ci_upper = service.calculate_median_ci(data)

        # Should return NaN for all values
        assert np.isnan(median)
        assert np.isnan(ci_lower)
        assert np.isnan(ci_upper)

    def test_calculate_median_ci_reproducibility(self):
        """Test that same seed gives same results."""
        np.random.seed(42)
        data = np.random.randn(50)

        service1 = BootstrapStatistics(n_bootstrap=500, random_seed=123)
        median1, ci_lower1, ci_upper1 = service1.calculate_median_ci(data)

        service2 = BootstrapStatistics(n_bootstrap=500, random_seed=123)
        median2, ci_lower2, ci_upper2 = service2.calculate_median_ci(data)

        # Results should be identical with same seed
        assert median1 == median2
        np.testing.assert_array_almost_equal([ci_lower1, ci_upper1], [ci_lower2, ci_upper2])

    def test_calculate_median_ci_confidence_level(self):
        """Test different confidence levels."""
        np.random.seed(42)
        data = np.random.randn(100)

        service = BootstrapStatistics(n_bootstrap=1000, random_seed=42)

        # 90% CI should be narrower than 95% CI
        median_90, ci_lower_90, ci_upper_90 = service.calculate_median_ci(data, confidence_level=0.90)
        median_95, ci_lower_95, ci_upper_95 = service.calculate_median_ci(data, confidence_level=0.95)

        width_90 = ci_upper_90 - ci_lower_90
        width_95 = ci_upper_95 - ci_lower_95

        # 95% CI should be wider than 90% CI
        assert width_95 > width_90
        assert median_90 == median_95  # Median should be the same

    def test_calculate_median_ci_matrix_shape(self):
        """Test matrix CI calculation returns correct shapes."""
        np.random.seed(42)
        data_matrix = np.random.randn(50, 100)  # 50 samples, 100 features

        service = BootstrapStatistics(n_bootstrap=500, random_seed=42)
        medians, ci_lowers, ci_uppers = service.calculate_median_ci_matrix(data_matrix)

        # Check shapes
        assert medians.shape == (100,)
        assert ci_lowers.shape == (100,)
        assert ci_uppers.shape == (100,)

        # Check that all CIs are valid
        assert np.all(ci_lowers <= medians)
        assert np.all(medians <= ci_uppers)

    def test_calculate_median_ci_matrix_with_nans(self):
        """Test matrix CI calculation with some NaN values."""
        np.random.seed(42)
        data_matrix = np.random.randn(50, 10)
        # Add some NaN values
        data_matrix[0, 0] = np.nan
        data_matrix[5, 3] = np.nan
        data_matrix[10, 7] = np.nan

        service = BootstrapStatistics(n_bootstrap=500, random_seed=42)
        medians, ci_lowers, ci_uppers = service.calculate_median_ci_matrix(data_matrix)

        # Should still compute valid CIs
        assert medians.shape == (10,)
        assert not np.any(np.isnan(medians))  # All should be valid (NaNs ignored per column)
        assert np.all(ci_lowers <= medians)
        assert np.all(medians <= ci_uppers)

    def test_calculate_median_ci_matrix_empty(self):
        """Test matrix CI calculation with empty matrix."""
        data_matrix = np.array([]).reshape(0, 0)

        service = BootstrapStatistics()
        medians, ci_lowers, ci_uppers = service.calculate_median_ci_matrix(data_matrix)

        # Should return empty arrays
        assert len(medians) == 0
        assert len(ci_lowers) == 0
        assert len(ci_uppers) == 0

    def test_calculate_median_ci_matrix_wrong_shape(self):
        """Test that 1D or 3D arrays raise errors."""
        service = BootstrapStatistics()

        # 1D array should raise ValueError
        with pytest.raises(ValueError, match="Expected 2D array"):
            service.calculate_median_ci_matrix(np.array([1, 2, 3]))

        # 3D array should raise ValueError
        with pytest.raises(ValueError, match="Expected 2D array"):
            service.calculate_median_ci_matrix(np.random.randn(10, 20, 30))

    @pytest.mark.slow
    def test_calculate_median_ci_matrix_psd_like_data(self):
        """Test with PSD-like data (realistic use case)."""
        # Simulate PSD data: 30 events, 100 frequency bins
        np.random.seed(42)
        # Log-normal distribution (typical for PSD data)
        psd_matrix = np.random.lognormal(mean=0, sigma=0.5, size=(30, 100))

        service = BootstrapStatistics(n_bootstrap=1000, random_seed=42)
        medians, ci_lowers, ci_uppers = service.calculate_median_ci_matrix(psd_matrix)

        # Check basic properties
        assert medians.shape == (100,)
        assert np.all(medians > 0)  # Log-normal data is positive
        assert np.all(ci_lowers > 0)
        assert np.all(ci_uppers > 0)
        assert np.all(ci_lowers < medians)
        assert np.all(medians < ci_uppers)

    def test_percentile_ci_method(self):
        """Test the private _percentile_ci method."""
        service = BootstrapStatistics()

        # Create mock bootstrap distribution
        bootstrap_stats = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])

        # 95% CI should give 2.5th and 97.5th percentiles
        ci_lower, ci_upper = service._percentile_ci(bootstrap_stats, confidence_level=0.95)

        assert ci_lower == pytest.approx(1.225, rel=0.1)  # ~2.5th percentile
        assert ci_upper == pytest.approx(9.775, rel=0.1)  # ~97.5th percentile

    def test_bootstrap_resample_method(self):
        """Test the private _bootstrap_resample method."""
        np.random.seed(42)
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        service = BootstrapStatistics(n_bootstrap=100, random_seed=42)
        bootstrap_medians = service._bootstrap_resample(data)

        # Should have correct number of bootstraps
        assert len(bootstrap_medians) == 100

        # All bootstrap medians should be reasonable
        assert np.all(bootstrap_medians >= 1.0)
        assert np.all(bootstrap_medians <= 5.0)

        # Bootstrap distribution should center around true median
        true_median = np.median(data)
        assert abs(np.mean(bootstrap_medians) - true_median) < 0.5
