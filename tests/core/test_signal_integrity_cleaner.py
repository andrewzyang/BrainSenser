import numpy as np
import pytest

from src.core.preprocessing.signal_integrity_cleaner import (
    SignalIntegrityCleaner,
    SignalIntegrityConfig
)


class TestSignalIntegrityCleaner:
    """Unit tests for SignalIntegrityCleaner."""

    def test_clean_interpolates_short_nan_run(self):
        data = np.array([
            [0.0, 0.0],
            [1.0, 1.0],
            [2.0, 2.0],
            [np.nan, 3.0],
            [np.nan, 4.0],
            [5.0, 5.0]
        ])

        cleaner = SignalIntegrityCleaner(
            SignalIntegrityConfig(max_interpolation_samples=4, min_frozen_run_length=3)
        )
        cleaned, stats = cleaner.clean(data, sampling_rate=250)

        assert np.isfinite(cleaned[3, 0])
        assert np.isfinite(cleaned[4, 0])
        assert pytest.approx(cleaned[3, 0]) == 3.0
        assert pytest.approx(cleaned[4, 0]) == 4.0
        assert stats['total_interpolated_samples'] == 2
        assert stats['total_dropped_samples'] == 0

    def test_clean_drops_long_nan_run(self):
        data = np.array([
            [0.0],
            [1.0],
            [np.nan],
            [np.nan],
            [np.nan],
            [np.nan],
            [np.nan],
            [6.0]
        ])

        cleaner = SignalIntegrityCleaner(
            SignalIntegrityConfig(max_interpolation_samples=2, min_frozen_run_length=3)
        )
        cleaned, stats = cleaner.clean(data, sampling_rate=250)

        # Long NaN block should be removed entirely
        assert cleaned.shape[0] == 3
        assert np.allclose(cleaned[:, 0], [0.0, 1.0, 6.0])
        assert stats['total_dropped_samples'] == 5
        assert stats['total_dropped_segments'] == 1
        assert stats['dropped_intervals'][0]['length'] == 5

    def test_clean_interpolates_frozen_run(self):
        data = np.array([
            [0.0],
            [1.0],
            [1.0],
            [1.0],
            [1.0],
            [5.0]
        ])

        cleaner = SignalIntegrityCleaner(
            SignalIntegrityConfig(max_interpolation_samples=10, min_frozen_run_length=3)
        )
        cleaned, stats = cleaner.clean(data, sampling_rate=250)

        assert not np.allclose(cleaned[1:5, 0], 1.0)
        assert np.allclose(cleaned[:, 0], [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        assert stats['total_interpolated_segments'] == 1
        assert stats['channels'][0]['frozen_segments_found'] == 1

    def test_clean_drops_large_frozen_run(self):
        data = np.array([
            [0.0],
            [2.0],
            [2.0],
            [2.0],
            [2.0],
            [2.0],
            [2.0],
            [2.0],
            [2.0],
            [2.0],
            [10.0]
        ])

        cleaner = SignalIntegrityCleaner(
            SignalIntegrityConfig(max_interpolation_samples=3, min_frozen_run_length=3)
        )
        cleaned, stats = cleaner.clean(data, sampling_rate=250)

        assert cleaned.shape[0] == 2
        assert np.allclose(cleaned[:, 0], [0.0, 10.0])
        assert stats['total_dropped_segments'] == 1

    def test_drop_applies_to_all_channels(self):
        data = np.array([
            [0.0, 10.0],
            [1.0, 11.0],
            [np.nan, 12.0],
            [np.nan, 13.0],
            [np.nan, 14.0],
            [5.0, 15.0]
        ])

        cleaner = SignalIntegrityCleaner(
            SignalIntegrityConfig(max_interpolation_samples=2, min_frozen_run_length=3)
        )
        cleaned, _ = cleaner.clean(data, sampling_rate=250)

        # Rows with NaNs removed for both channels
        assert cleaned.shape == (3, 2)
        assert np.allclose(cleaned[:, 0], [0.0, 1.0, 5.0])
        assert np.allclose(cleaned[:, 1], [10.0, 11.0, 15.0])
