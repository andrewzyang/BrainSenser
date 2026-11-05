"""
Unit tests for StreamingArtifactDetector.

Tests artifact detection with synthetic data containing known artifacts.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import pytest
import numpy as np
from src.core.services.artifact_detector import (
    StreamingArtifactDetector,
    ArtifactDetectionConfig
)


class TestArtifactDetectionConfig:
    """Test ArtifactDetectionConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ArtifactDetectionConfig()

        assert config.saturation_percentile == 99.9
        assert config.outlier_std_threshold == 5.0
        assert config.flatline_min_consecutive == 5
        assert config.jump_threshold == 1000.0
        assert config.detect_saturation is True
        assert config.detect_outliers is True
        assert config.detect_flatline is True
        assert config.detect_jumps is True
        assert config.detect_invalid is True

    def test_custom_config(self):
        """Test custom configuration values."""
        config = ArtifactDetectionConfig(
            saturation_percentile=99.0,
            outlier_std_threshold=3.0,
            flatline_min_consecutive=10,
            jump_threshold=500.0,
            detect_saturation=False
        )

        assert config.saturation_percentile == 99.0
        assert config.outlier_std_threshold == 3.0
        assert config.flatline_min_consecutive == 10
        assert config.jump_threshold == 500.0
        assert config.detect_saturation is False


class TestStreamingArtifactDetector:
    """Test StreamingArtifactDetector class."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = StreamingArtifactDetector()
        assert detector.config is not None
        assert isinstance(detector.config, ArtifactDetectionConfig)

    def test_initialization_with_custom_config(self):
        """Test detector initialization with custom config."""
        config = ArtifactDetectionConfig(outlier_std_threshold=3.0)
        detector = StreamingArtifactDetector(config)
        assert detector.config.outlier_std_threshold == 3.0

    def test_empty_data_raises_error(self):
        """Test that empty data raises ValueError."""
        detector = StreamingArtifactDetector()

        with pytest.raises(ValueError, match="cannot be empty"):
            detector.detect_artifacts(np.array([]), sampling_rate=250.0)

    def test_none_data_raises_error(self):
        """Test that None data raises ValueError."""
        detector = StreamingArtifactDetector()

        with pytest.raises(ValueError, match="cannot be empty"):
            detector.detect_artifacts(None, sampling_rate=250.0)

    def test_clean_data_no_artifacts(self):
        """Test that clean data produces minimal artifacts."""
        # Disable saturation detection (which always flags top percentile)
        config = ArtifactDetectionConfig(
            detect_saturation=False  # Saturation always flags top 0.1%
        )
        detector = StreamingArtifactDetector(config)

        # Generate clean sine wave data
        t = np.linspace(0, 10, 2500)  # 10 seconds at 250 Hz
        data = np.sin(2 * np.pi * 10 * t).reshape(-1, 1)  # 10 Hz sine wave

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        assert artifact_mask.shape == data.shape
        # Should have very few artifacts (allow < 1%)
        artifact_rate = np.sum(artifact_mask) / artifact_mask.size * 100
        assert artifact_rate < 1.0  # Less than 1% artifacts

    def test_1d_array_handling(self):
        """Test that 1D arrays are handled correctly."""
        detector = StreamingArtifactDetector()

        # 1D array
        data = np.sin(np.linspace(0, 10, 1000))

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should be reshaped to (samples, 1)
        assert artifact_mask.shape == (1000, 1)


class TestInvalidValueDetection:
    """Test detection of NaN and Inf values."""

    def test_detect_nan_values(self):
        """Test detection of NaN values."""
        detector = StreamingArtifactDetector()

        # Data with NaN values
        data = np.array([1.0, 2.0, np.nan, 4.0, 5.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        assert artifact_mask[2, 0] == True  # NaN detected
        assert np.sum(artifact_mask) >= 1

    def test_detect_inf_values(self):
        """Test detection of Inf values."""
        detector = StreamingArtifactDetector()

        # Data with Inf values
        data = np.array([1.0, 2.0, np.inf, 4.0, 5.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        assert artifact_mask[2, 0] == True  # Inf detected
        assert np.sum(artifact_mask) >= 1

    def test_detect_negative_inf_values(self):
        """Test detection of -Inf values."""
        detector = StreamingArtifactDetector()

        # Data with -Inf values
        data = np.array([1.0, 2.0, -np.inf, 4.0, 5.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        assert artifact_mask[2, 0] == True  # -Inf detected


class TestSaturationDetection:
    """Test detection of saturation artifacts."""

    def test_detect_saturation(self):
        """Test detection of saturation at high values."""
        config = ArtifactDetectionConfig(
            saturation_percentile=95.0,  # Lower threshold for testing
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # Data with saturation at high values
        data = np.array([1.0, 2.0, 3.0, 4.0, 100.0, 101.0, 102.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Top 5% (above 95th percentile) should be flagged
        assert np.sum(artifact_mask) > 0
        assert artifact_mask[-1, 0] == True  # Highest value flagged


class TestOutlierDetection:
    """Test detection of statistical outliers."""

    def test_detect_outliers(self):
        """Test detection of outlier values."""
        config = ArtifactDetectionConfig(
            outlier_std_threshold=3.0,
            detect_saturation=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # Normal data with outliers
        np.random.seed(42)
        data = np.random.randn(1000, 1)  # Mean=0, Std=1
        data[500] = 10.0  # Outlier (10 std from mean)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Outlier should be detected
        assert artifact_mask[500, 0] == True
        assert np.sum(artifact_mask) >= 1


class TestFlatlineDetection:
    """Test detection of flatline artifacts."""

    def test_detect_flatline(self):
        """Test detection of consecutive identical values."""
        config = ArtifactDetectionConfig(
            flatline_min_consecutive=5,
            detect_saturation=False,
            detect_outliers=False,
            detect_jumps=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # Data with flatline (10 consecutive identical values)
        data = np.array([1.0, 2.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 3.0, 4.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Flatline region (indices 2-9) should be detected
        assert np.sum(artifact_mask) >= 5
        assert artifact_mask[5, 0] == True  # Middle of flatline

    def test_short_flatline_not_detected(self):
        """Test that short flatlines below threshold are not detected."""
        config = ArtifactDetectionConfig(
            flatline_min_consecutive=5,
            detect_saturation=False,
            detect_outliers=False,
            detect_jumps=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # Data with short flatline (only 3 consecutive)
        data = np.array([1.0, 2.0, 5.0, 5.0, 5.0, 3.0, 4.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should not be detected (below threshold)
        assert np.sum(artifact_mask) == 0


class TestJumpDetection:
    """Test detection of large instantaneous jumps."""

    def test_detect_jumps(self):
        """Test detection of large jumps."""
        config = ArtifactDetectionConfig(
            jump_threshold=50.0,
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # Data with large jump
        data = np.array([1.0, 2.0, 3.0, 100.0, 4.0, 5.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Jump at index 3 should be detected
        assert np.sum(artifact_mask) >= 1
        assert artifact_mask[3, 0] == True  # Sample after jump

    def test_small_jumps_not_detected(self):
        """Test that small jumps below threshold are not detected."""
        config = ArtifactDetectionConfig(
            jump_threshold=50.0,
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # Data with small jumps
        data = np.array([1.0, 2.0, 3.0, 10.0, 4.0, 5.0]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should not be detected (below threshold)
        assert np.sum(artifact_mask) == 0


class TestMultiChannelDetection:
    """Test artifact detection on multi-channel data."""

    def test_multi_channel_artifacts(self):
        """Test detection across multiple channels."""
        detector = StreamingArtifactDetector()

        # 2 channels: channel 0 clean, channel 1 has outlier
        np.random.seed(42)
        channel0 = np.random.randn(1000)
        channel1 = np.random.randn(1000)
        channel1[500] = 10.0  # Outlier in channel 1

        data = np.column_stack([channel0, channel1])

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        assert artifact_mask.shape == (1000, 2)
        # Channel 1 should have artifact at index 500
        assert artifact_mask[500, 1] == True

    def test_per_channel_statistics(self):
        """Test that artifacts are detected per-channel (not globally)."""
        config = ArtifactDetectionConfig(
            outlier_std_threshold=3.0,
            detect_saturation=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # Two channels with different scales
        # Channel 0: mean=0, std=1
        # Channel 1: mean=100, std=10
        np.random.seed(42)
        channel0 = np.random.randn(1000)
        channel1 = np.random.randn(1000) * 10 + 100

        # Add outlier to each channel (relative to its own distribution)
        channel0[500] = 10.0  # 10 std from channel 0 mean
        channel1[600] = 200.0  # 10 std from channel 1 mean

        data = np.column_stack([channel0, channel1])

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Both outliers should be detected independently
        assert artifact_mask[500, 0] == True
        assert artifact_mask[600, 1] == True


class TestArtifactSummary:
    """Test artifact summary statistics."""

    def test_get_artifact_summary(self):
        """Test generation of artifact summary."""
        detector = StreamingArtifactDetector()

        # Simple test data
        artifact_mask = np.array([
            [True, False],
            [False, False],
            [True, True],
            [False, True]
        ])

        summary = detector.get_artifact_summary(artifact_mask)

        assert summary['total_samples'] == 8
        assert summary['total_artifacts'] == 4
        assert summary['artifact_rate'] == 50.0
        assert summary['num_channels'] == 2
        assert summary['num_timepoints'] == 4

        # Check channel stats
        assert len(summary['channel_stats']) == 2
        assert summary['channel_stats'][0]['artifacts'] == 2
        assert summary['channel_stats'][1]['artifacts'] == 2

    def test_summary_with_no_artifacts(self):
        """Test summary when no artifacts detected."""
        detector = StreamingArtifactDetector()

        artifact_mask = np.zeros((100, 2), dtype=bool)

        summary = detector.get_artifact_summary(artifact_mask)

        assert summary['total_artifacts'] == 0
        assert summary['artifact_rate'] == 0.0


class TestConfigOverride:
    """Test configuration override in detect_artifacts."""

    def test_config_override(self):
        """Test that config parameter overrides instance config."""
        # Instance config with high threshold - all detectors disabled except outlier
        instance_config = ArtifactDetectionConfig(
            outlier_std_threshold=10.0,
            detect_saturation=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(instance_config)

        # Override config with lower threshold
        override_config = ArtifactDetectionConfig(
            outlier_std_threshold=2.0,
            detect_saturation=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False
        )

        # Data with moderate outlier
        np.random.seed(42)
        data = np.random.randn(1000, 1)
        data[500] = 5.0  # 5 std from mean

        # Should detect with override config (threshold=2.0)
        artifact_mask = detector.detect_artifacts(
            data,
            sampling_rate=250.0,
            config=override_config
        )

        assert artifact_mask[500, 0] == True

        # Should not detect with instance config (threshold=10.0)
        artifact_mask2 = detector.detect_artifacts(data, sampling_rate=250.0)
        assert artifact_mask2[500, 0] == False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_sample(self):
        """Test detection with single sample."""
        detector = StreamingArtifactDetector()

        data = np.array([1.0]).reshape(-1, 1)
        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        assert artifact_mask.shape == (1, 1)

    def test_all_nan_data(self):
        """Test detection with all NaN data."""
        detector = StreamingArtifactDetector()

        data = np.full((100, 2), np.nan)
        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # All values should be detected as artifacts
        assert np.sum(artifact_mask) == 200

    def test_zero_variance_data(self):
        """Test detection with constant (zero variance) data."""
        config = ArtifactDetectionConfig(
            flatline_min_consecutive=5,
            detect_saturation=False,
            detect_outliers=False,
            detect_jumps=False,
            detect_invalid=False
        )
        detector = StreamingArtifactDetector(config)

        # All values are identical
        data = np.full((100, 1), 5.0)
        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should be detected as flatline
        assert np.sum(artifact_mask) > 0


class TestHighFreqNoiseDetection:
    """Test detection of high-frequency noise (requires scipy)."""

    @pytest.mark.skipif(
        not hasattr(__import__('sys').modules.get('scipy', None), 'signal'),
        reason="scipy not installed"
    )
    def test_detect_highfreq_noise(self):
        """Test detection of high-frequency noise."""
        pytest.importorskip("scipy")

        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_highfreq_noise=True,
            highfreq_cutoff=50.0,  # Lower cutoff to detect 150 Hz better
            highfreq_power_threshold=0.1  # Very low threshold for testing
        )
        detector = StreamingArtifactDetector(config)

        # Generate data with high-frequency noise burst
        t = np.linspace(0, 4, 1000)  # 4 seconds at 250 Hz
        # Low-frequency base signal (5 Hz) - very clean
        base_signal = 0.5 * np.sin(2 * np.pi * 5 * t)
        # Add strong high-frequency noise to middle section (150 Hz)
        noise_start = 250
        noise_end = 750
        base_signal[noise_start:noise_end] += 5.0 * np.sin(2 * np.pi * 150 * t[noise_start:noise_end])

        data = base_signal.reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should detect artifacts somewhere (may not be exact region due to windowing)
        total_artifacts = np.sum(artifact_mask)
        assert total_artifacts > 0, "Should detect some high-frequency artifacts"

    def test_highfreq_disabled_by_default(self):
        """Test that high-frequency detection is disabled by default."""
        detector = StreamingArtifactDetector()
        assert detector.config.detect_highfreq_noise is False

    def test_highfreq_clean_signal(self):
        """Test that clean low-frequency signal is not flagged."""
        pytest.importorskip("scipy")

        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_highfreq_noise=True,
            highfreq_cutoff=100.0
        )
        detector = StreamingArtifactDetector(config)

        # Generate clean low-frequency signal (20 Hz)
        t = np.linspace(0, 2, 500)
        data = np.sin(2 * np.pi * 20 * t).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should have minimal artifacts
        artifact_rate = np.sum(artifact_mask) / artifact_mask.size * 100
        assert artifact_rate < 10.0  # Less than 10%


class TestLineNoiseDetection:
    """Test detection of 60 Hz line noise (requires scipy)."""

    @pytest.mark.skipif(
        not hasattr(__import__('sys').modules.get('scipy', None), 'signal'),
        reason="scipy not installed"
    )
    def test_detect_line_noise(self):
        """Test detection of 60 Hz line noise."""
        pytest.importorskip("scipy")

        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_line_noise=True,
            line_freq=60.0,
            line_noise_threshold=2.0  # Lower threshold for testing
        )
        detector = StreamingArtifactDetector(config)

        # Generate signal with strong 60 Hz component
        t = np.linspace(0, 2, 500)  # 2 seconds at 250 Hz
        base_signal = np.sin(2 * np.pi * 10 * t)  # 10 Hz base
        line_noise = 3.0 * np.sin(2 * np.pi * 60 * t)  # Strong 60 Hz

        data = (base_signal + line_noise).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should detect line noise (may flag entire channel)
        assert np.sum(artifact_mask) > 0

    def test_line_noise_disabled_by_default(self):
        """Test that line noise detection is disabled by default."""
        detector = StreamingArtifactDetector()
        assert detector.config.detect_line_noise is False

    def test_line_noise_clean_signal(self):
        """Test that signal without line noise is not flagged."""
        pytest.importorskip("scipy")

        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_line_noise=True,
            line_freq=60.0
        )
        detector = StreamingArtifactDetector(config)

        # Generate clean signal without 60 Hz component
        t = np.linspace(0, 2, 500)
        data = np.sin(2 * np.pi * 20 * t).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should have no or minimal artifacts
        assert np.sum(artifact_mask) == 0


class TestNonstationarityDetection:
    """Test detection of non-stationarity artifacts."""

    def test_detect_nonstationarity(self):
        """Test detection of variance changes."""
        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_nonstationarity=True,
            nonstationarity_window_sec=1.0,
            nonstationarity_threshold=3.0  # Lower threshold for easier detection
        )
        detector = StreamingArtifactDetector(config)

        # Generate signal with sudden variance change
        np.random.seed(42)
        # First section: very low variance (stable baseline)
        signal1 = np.random.randn(500) * 0.05
        # Second section: very high variance (burst) - 40x higher std
        signal2 = np.random.randn(500) * 2.0

        data = np.concatenate([signal1, signal2]).reshape(-1, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should detect artifacts somewhere (variance change should be detected)
        total_artifacts = np.sum(artifact_mask)
        assert total_artifacts > 0, "Should detect variance change artifacts"

    def test_nonstationarity_disabled_by_default(self):
        """Test that non-stationarity detection is disabled by default."""
        detector = StreamingArtifactDetector()
        assert detector.config.detect_nonstationarity is False

    def test_nonstationarity_stationary_signal(self):
        """Test that stationary signal is not flagged."""
        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_nonstationarity=True,
            nonstationarity_window_sec=0.5
        )
        detector = StreamingArtifactDetector(config)

        # Generate stationary signal (constant variance)
        np.random.seed(42)
        data = np.random.randn(1000, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should have minimal artifacts
        artifact_rate = np.sum(artifact_mask) / artifact_mask.size * 100
        assert artifact_rate < 10.0


class TestLowCoherenceDetection:
    """Test detection of low cross-channel coherence."""

    def test_detect_low_coherence(self):
        """Test detection of channel-specific artifacts."""
        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_low_coherence=True,
            coherence_threshold=0.5
        )
        detector = StreamingArtifactDetector(config)

        # Generate two channels with different patterns
        np.random.seed(42)
        # Channel 0: coherent with channel 1 in first half
        shared_signal = np.sin(2 * np.pi * 10 * np.linspace(0, 2, 500))
        channel0 = shared_signal + np.random.randn(500) * 0.1
        channel1 = shared_signal + np.random.randn(500) * 0.1

        # Add isolated artifact to channel 0 in second half
        channel0[250:] += np.random.randn(250) * 5.0  # Uncorrelated noise

        data = np.column_stack([channel0, channel1])

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should detect low coherence in channel 0's second half
        ch0_artifacts = np.sum(artifact_mask[250:, 0])
        assert ch0_artifacts > 0

    def test_coherence_disabled_by_default(self):
        """Test that coherence detection is disabled by default."""
        detector = StreamingArtifactDetector()
        assert detector.config.detect_low_coherence is False

    def test_coherence_requires_multiple_channels(self):
        """Test that coherence detection requires >1 channel."""
        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_low_coherence=True
        )
        detector = StreamingArtifactDetector(config)

        # Single channel data
        data = np.random.randn(1000, 1)

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should not detect anything (need multiple channels)
        assert np.sum(artifact_mask) == 0

    def test_coherence_high_correlation(self):
        """Test that highly correlated channels are not flagged."""
        config = ArtifactDetectionConfig(
            detect_saturation=False,
            detect_outliers=False,
            detect_flatline=False,
            detect_jumps=False,
            detect_invalid=False,
            detect_low_coherence=True,
            coherence_threshold=0.5
        )
        detector = StreamingArtifactDetector(config)

        # Two highly correlated channels
        np.random.seed(42)
        base_signal = np.sin(2 * np.pi * 10 * np.linspace(0, 4, 1000))
        channel0 = base_signal + np.random.randn(1000) * 0.1
        channel1 = base_signal + np.random.randn(1000) * 0.1

        data = np.column_stack([channel0, channel1])

        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        # Should have minimal artifacts (high coherence)
        artifact_rate = np.sum(artifact_mask) / artifact_mask.size * 100
        assert artifact_rate < 20.0


class TestAdvancedDetectorsCombined:
    """Test combinations of advanced detectors."""

    def test_all_advanced_detectors_enabled(self):
        """Test that all advanced detectors can be enabled together."""
        pytest.importorskip("scipy")

        config = ArtifactDetectionConfig(
            detect_saturation=True,
            detect_outliers=True,
            detect_flatline=True,
            detect_jumps=True,
            detect_invalid=True,
            detect_highfreq_noise=True,
            detect_line_noise=True,
            detect_nonstationarity=True,
            detect_low_coherence=True
        )
        detector = StreamingArtifactDetector(config)

        # Generate multi-channel clean data
        t = np.linspace(0, 2, 500)
        channel0 = np.sin(2 * np.pi * 15 * t)
        channel1 = np.sin(2 * np.pi * 20 * t)
        data = np.column_stack([channel0, channel1])

        # Should not raise errors
        artifact_mask = detector.detect_artifacts(data, sampling_rate=250.0)

        assert artifact_mask.shape == data.shape

    def test_config_new_parameters(self):
        """Test that new config parameters have correct defaults."""
        config = ArtifactDetectionConfig()

        # High-frequency noise
        assert config.highfreq_cutoff == 100.0
        assert config.highfreq_power_threshold == 2.0
        assert config.detect_highfreq_noise is False

        # Line noise
        assert config.line_freq == 60.0
        assert config.line_noise_threshold == 3.0
        assert config.detect_line_noise is False

        # Non-stationarity
        assert config.nonstationarity_window_sec == 1.0
        assert config.nonstationarity_threshold == 3.0
        assert config.detect_nonstationarity is False

        # Coherence
        assert config.coherence_threshold == 0.3
        assert config.detect_low_coherence is False
